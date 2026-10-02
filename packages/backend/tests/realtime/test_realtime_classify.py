from __future__ import annotations

from tandem_backend.realtime import classify as c
from tandem_backend.realtime.context_windows import lookup
from tandem_backend.realtime.model import SessionTail, TailCall, TailEvent

NOW = 1_800_000_000_000
S = 1000


def tail(quiet_s, actor="tool", status="active", calls=(), usage=None, permission=None,
         agent="claude_code"):
    last = NOW - int(quiet_s * S)
    return SessionTail("s", agent=agent, status=status, last_event_ts=last, last_actor=actor,
                       ended_at=last if status != "active" else None,
                       events=[TailEvent(last - 30 * S, "message", "human"),
                               TailEvent(last, "message", actor)],
                       calls=list(calls), usage=usage, pending_permission=permission)


def fails(n, head="npm install", error_class="network", digest="d"):
    return [TailCall(f"c{i}", "bash", head, digest, "failed", error_class, 1, NOW - (10 - i) * S)
            for i in range(n)]


def test_running_window_boundary():
    assert c.classify(tail(c.RUN_WINDOW_S - 1), NOW).state == "running"
    assert c.classify(tail(c.RUN_WINDOW_S + 1), NOW).state == "idle"


def test_running_since_is_burst_start():
    state = c.classify(tail(5), NOW)
    assert state.since == NOW - 35 * S


def test_quiet_then_just_finished_then_idle():
    assert c.classify(tail(c.QUIET_S - 1, actor="assistant"), NOW).state == "running"
    done = c.classify(tail(c.QUIET_S + 1, actor="assistant"), NOW)
    assert done.state == "just_finished" and done.since == NOW - S
    assert c.classify(tail(c.QUIET_S + c.FINISHED_TTL_S - 1, actor="assistant"),
                      NOW).state == "just_finished"
    assert c.classify(tail(c.QUIET_S + c.FINISHED_TTL_S + 1, actor="assistant"),
                      NOW).state == "idle"


def test_completed_status_finishes_without_waiting():
    assert c.classify(tail(1, status="completed"), NOW).state == "just_finished"


def test_failing_needs_three_identical_failures():
    assert c.classify(tail(1, calls=fails(2)), NOW).state == "running"
    state = c.classify(tail(1, calls=fails(3, error_class="auth_error")), NOW)
    assert state.state == "failing" and "failing" in state.flags
    assert state.failure["n"] == 3 and state.failure["cause_hint"] == "认证失败"
    assert state.failure["error_class_share"] == {"auth_error": 1.0}
    mixed = fails(2) + [TailCall("x", "bash", "npm install", "other", "failed", None, 1, NOW)]
    assert c.classify(tail(1, calls=mixed), NOW).failure is None
    recovered = fails(3) + [TailCall("ok", "bash", "npm install", "d", "ok", None, 0, NOW)]
    assert c.classify(tail(1, calls=recovered), NOW).failure is None


def test_failing_ignores_red_tests():
    calls = fails(4, head="uv run pytest", error_class="test_failure")
    assert c.classify(tail(1, calls=calls), NOW).failure is None
    assert c.failure(fails(3, head="make", error_class="test_failure")) is not None


def test_awaiting_approval_only_from_permission_event():
    assert "awaiting_approval" not in c.classify(tail(300), NOW).flags
    permission = {"ts": NOW - 40 * S, "command": "curl -H 'Authorization: Bearer abcdefghijklmnop'"}
    state = c.classify(tail(40, permission=permission), NOW)
    assert state.state == "awaiting_approval" and state.approval["wait_s"] == 40
    assert state.approval["basis"] == "hook" and "abcdefghijklmnop" not in state.approval["command"]
    stale = {"ts": NOW - (c.APPROVAL_MAX_S + 1) * S, "command": "x"}
    assert c.classify(tail(c.APPROVAL_MAX_S + 1, permission=stale), NOW).approval is None


def test_context_pressure_threshold_and_unknown():
    window = lookup("claude_code", "claude-sonnet-4-5")["window_tokens"]
    below = {"used_tokens": int(window * 0.89), "model": "claude-sonnet-4-5"}
    above = {"used_tokens": int(window * 0.9), "model": "claude-sonnet-4-5"}
    assert "context_pressure" not in c.classify(tail(1, usage=below), NOW).flags
    state = c.classify(tail(1, usage=above), NOW)
    assert "context_pressure" in state.flags and state.context["basis"] == "last_call_input"
    unknown = c.classify(tail(1, usage={"used_tokens": 10**9, "model": "mystery-1"}), NOW)
    assert unknown.context["ratio"] is None and unknown.context["basis"] == "unknown"
    assert "context_pressure" not in unknown.flags
    missing = c.classify(tail(1, usage={"used_tokens": None, "model": "gpt-5"}), NOW)
    assert missing.context["ratio"] is None and not missing.flags


def test_context_window_lookup():
    assert lookup("codex", "gpt-5-codex")["window_tokens"] == 272_000
    assert lookup("other", "openai/gpt-5")["window_tokens"] == 400_000
    assert lookup("claude_code", "claude-sonnet-4-5[1m]")["window_tokens"] == 1_000_000
    assert lookup("codex", "gpt-5", {"gpt-5": 123})["window_tokens"] == 123
    assert lookup("codex", None) is None and lookup("codex", "llama-3") is None
