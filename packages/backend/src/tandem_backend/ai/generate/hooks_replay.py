"""Historical replay for hook drafts (AI-07.3): run the template's pure `decide()` in process.

Each historical call becomes a PreToolUse and a PostToolUse event; every session ends with a
Stop event. Evidence sessions should trigger the hook (recall); normal sessions must never be
blocked (false_block == 0), otherwise the draft is blocked.
"""

from __future__ import annotations

import importlib.util
from functools import cache

from ..pack import FAIL_STATUS, OK_STATUS
from .templates import Template


@cache
def _module(path: str, sha256: str):
    spec = importlib.util.spec_from_file_location(f"tandem_hook_{sha256[:12]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decide_fn(template: Template):
    return _module(str(template.path), template.sha256).decide


def _events(call: dict, session_uid: str):
    tool = call.get("tool_name") or ""
    exts = call.get("file_exts") or []
    if call.get("command_head") or tool == "Bash":
        tool_input = {"command": call.get("command_head") or ""}
    else:
        tool_input = {"file_path": "f" + (exts[0] if exts else "")}
    base = {"session_id": session_uid, "tool_name": tool, "tool_input": tool_input}
    yield {**base, "hook_event_name": "PreToolUse"}
    # tool_call.status uses the canonical vocabulary (completed/failed/unknown/declined/orphan_result…).
    # Only a known outcome produces a PostToolUse; an unknown outcome is neither a success (which would
    # reset failure streaks / count as a verification) nor a failure (which would inflate recall).
    status = call.get("status")
    if status in OK_STATUS or status in FAIL_STATUS:
        yield {**base, "hook_event_name": "PostToolUse",
               "tool_response": {"success": status in OK_STATUS, "exit_code": call.get("exit_code")}}


def replay(template: Template, config: dict, replay_calls: list[dict] | None) -> dict:
    if template.kind != "hook" or not replay_calls:
        return {"status": "skipped", "recall": None, "false_block": 0, "sessions": []}
    decide = decide_fn(template)
    sessions, evidence_total, triggered, false_block = [], 0, 0, 0
    for session in replay_calls:
        uid = session.get("session_uid", "")
        state: dict = {}
        fired, blocks, first_block = False, 0, None
        events = [e for call in session.get("calls") or [] for e in _events(call, uid)]
        events.append({"session_id": uid, "hook_event_name": "Stop", "stop_hook_active": False})
        for event in events:
            decision, message = decide(event, config, state)
            if decision in ("warn", "block"):
                fired = True
            if decision == "block":
                blocks += 1
                first_block = first_block or message
        if session.get("evidence"):
            evidence_total += 1
            triggered += fired
            result, reason = ("pass", "已触发") if fired else ("fail", "证据会话未触发")
        else:
            false_block += blocks
            result, reason = ("fail", f"误拦 {blocks} 次：{first_block}") if blocks else ("pass", "未误拦")
        sessions.append({"session_uid": uid, "title": session.get("title") or "", "result": result, "reason": reason})
    recall = triggered / evidence_total if evidence_total else None
    status = "blocked" if false_block else "untriggered" if recall == 0 else "ok"
    return {"status": status, "recall": recall, "false_block": false_block, "sessions": sessions}
