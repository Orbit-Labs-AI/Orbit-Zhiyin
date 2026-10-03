"""Pure live-state rules for one session tail (AN-13). No IO, no clock, no model calls.

Every threshold is a module constant and 待验证 until checked against real sessions.
"""

from __future__ import annotations

import re
from collections import Counter

from ..privacy import redact
from . import context_windows
from .model import SessionState, SessionTail, TailCall

RUN_WINDOW_S = 120  # 待验证: an event this recent means the agent is still working.
QUIET_S = 90  # 待验证: silence after a closed turn before we call the session finished.
FINISHED_TTL_S = 600  # 待验证: how long "just finished" stays visible before idle.
APPROVAL_MAX_S = 3600  # 待验证: older unanswered permission requests are treated as abandoned.
FAILING_MIN_RUN = 3  # 待验证: identical consecutive failures that count as a retry loop.
CONTEXT_PRESSURE = 0.9  # 待验证: used / window ratio that raises the context flag.

CLOSED_STATUSES = {"completed", "failed"}
CLOSED_TURN_ACTORS = {"assistant", "system"}
OPEN_KINDS = {"tool.call", "subagent.spawn", "permission.request", "turn.start"}
FAILED_CALL = {"failed", "error"}
RUNNING_CALL = {"running", "pending", "started"}
TEST_RUNNERS = ("pytest", "jest", "vitest", "go test", "cargo test", "npm test", "pnpm test",
                "swift test", "xcodebuild test")
CAUSE_HINTS = (("auth", "认证失败"), ("timeout", "超时"), ("timed out", "超时"),
               ("not_found", "命令或文件不存在"), ("not found", "命令或文件不存在"),
               ("enoent", "命令或文件不存在"), ("permission", "权限不足"))


def _ms(seconds: float) -> int:
    return int(seconds * 1000)


def is_closed(tail: SessionTail) -> bool:
    """Closed status counts only while no event arrived after ``ended_at`` (resumed sessions)."""
    if tail.status not in CLOSED_STATUSES:
        return False
    return tail.ended_at is None or tail.last_event_ts is None or tail.ended_at >= tail.last_event_ts


def finish_ts(tail: SessionTail) -> int | None:
    """When the session counts as finished, or None while a turn is still open."""
    if tail.last_event_ts is None:
        return None
    if is_closed(tail):
        return tail.last_event_ts
    if turn_closed(tail):
        return tail.last_event_ts + _ms(QUIET_S)
    return None


def turn_closed(tail: SessionTail) -> bool:
    """turn.end, or an assistant/system event that does not open a tool call or subagent."""
    kind = tail.events[-1].kind if tail.events else None
    if kind == "turn.end":
        return True
    return tail.last_actor in CLOSED_TURN_ACTORS and kind not in OPEN_KINDS


def _is_test_runner(head: str) -> bool:
    head = head.lower()
    return any(re.search(rf"(^|\s){re.escape(name)}(\s|$)", head) for name in TEST_RUNNERS)


def retry_streak(calls: list[TailCall]) -> list[TailCall]:
    """Trailing run of failed calls sharing command_head and argument_digest (retry_links rule)."""
    ordered = sorted(calls, key=lambda c: (c.started_at or 0, c.call_uid))
    streak: list[TailCall] = []
    for call in reversed(ordered):
        if call.status not in FAILED_CALL:
            break
        identity = (call.command_head or call.name, call.argument_digest)
        if streak and identity != (streak[0].command_head or streak[0].name,
                                   streak[0].argument_digest):
            break
        streak.append(call)
    return streak[::-1]


def cause_hint(error_class: str | None) -> str | None:
    text = (error_class or "").lower()
    return next((hint for key, hint in CAUSE_HINTS if key in text), None)


def failure(calls: list[TailCall]) -> dict | None:
    streak = retry_streak(calls)
    if len(streak) < FAILING_MIN_RUN:
        return None
    classes = Counter(c.error_class or "unknown" for c in streak)
    dominant = classes.most_common(1)[0][0]
    head = streak[-1].command_head or streak[-1].name
    if dominant == "test_failure" and _is_test_runner(head):
        return None  # Expected red tests while iterating are not a stuck loop.
    return {"n": len(streak), "command_head": head, "started_at": streak[0].started_at,
            "error_class_share": {k: round(v / len(streak), 2) for k, v in classes.items()},
            "cause_hint": cause_hint(dominant)}


def context(tail: SessionTail, overrides: dict | None = None) -> dict | None:
    if not tail.usage:
        return None
    used = tail.usage.get("used_tokens")
    window = context_windows.resolve(tail.agent, tail.usage.get("model"), overrides,
                                     tail.usage.get("window_tokens"))
    ratio, basis = context_windows.usage_ratio(used, window)
    if basis == "window_exceeded":  # the window is wrong for this model (e.g. 1M)
        return {"used_tokens": used, "window_tokens": None, "ratio": None,
                "auto_compact_ratio": None, "basis": basis, "window_basis": window["basis"]}
    return {"used_tokens": used, "window_tokens": window and window["window_tokens"],
            "ratio": None if ratio is None else round(ratio, 4),
            "auto_compact_ratio": window and window["auto_compact_ratio"], "basis": basis,
            "window_basis": window and window["basis"]}


def _streak_start(tail: SessionTail) -> int:
    """First event of the current burst: walk back while gaps stay within RUN_WINDOW_S."""
    start = tail.last_event_ts or 0
    for ts in sorted((e.ts for e in tail.events if e.ts is not None and e.ts <= start),
                     reverse=True):
        if start - ts > _ms(RUN_WINDOW_S):
            break
        start = ts
    return start


def _current_tool(tail: SessionTail) -> dict | None:
    if not tail.calls:
        return None
    call = max(tail.calls, key=lambda c: c.started_at or 0)
    if call.status in RUNNING_CALL or (call.ended_at is None and call.status == "unknown"):
        return {"name": call.name, "command_head": call.command_head,
                "started_at": call.started_at}
    return None


def classify(tail: SessionTail, now_ms: int, overrides: dict | None = None) -> SessionState:
    last = tail.last_event_ts
    quiet = now_ms - last if last is not None else None
    done_at = finish_ts(tail)
    recent = quiet is not None and quiet <= _ms(RUN_WINDOW_S)
    running = recent and not is_closed(tail) and (done_at is None or now_ms < done_at)
    finished = done_at is not None and done_at <= now_ms < done_at + _ms(FINISHED_TTL_S)

    state = SessionState(tail.session_uid, "idle", last or 0, finished_at=done_at)
    permission = tail.pending_permission
    if (permission and not is_closed(tail) and permission.get("ts") is not None
            and permission["ts"] >= (last or 0) and now_ms - permission["ts"] <= _ms(APPROVAL_MAX_S)):
        state.approval = {"wait_s": max(0, (now_ms - permission["ts"]) // 1000),
                          "command": redact(str(permission.get("command") or ""))[:200] or None,
                          "basis": "hook"}
        state.flags.add("awaiting_approval")
    if recent and not is_closed(tail):
        state.failure = failure(tail.calls)
        if state.failure:
            state.flags.add("failing")
    if state.approval:
        state.state, state.since = "awaiting_approval", tail.pending_permission["ts"]
    elif state.failure:
        state.state, state.since = "failing", state.failure["started_at"] or last or 0
    elif running:
        state.state, state.since = "running", _streak_start(tail)
        state.current_tool = _current_tool(tail)
    elif finished:
        state.state, state.since = "just_finished", done_at
    state.context = context(tail, overrides)
    ratio = state.context and state.context["ratio"]
    if ratio is not None and ratio >= CONTEXT_PRESSURE and state.state != "idle":
        state.flags.add("context_pressure")
    return state
