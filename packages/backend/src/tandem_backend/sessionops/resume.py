"""Copyable resume commands per session (DT-24). Builds strings only: never executes
anything and never touches the clipboard. CLI flags are unverified, hence ``verified``."""

from __future__ import annotations

import shlex

RUNNING_WINDOW_MS = 120_000
TEMPLATES = {
    "claude_code": {"label": "在 Claude Code 中继续", "argv": ["claude", "--resume", "{id}"]},
    "codex": {"label": "在 Codex 中继续", "argv": ["codex", "resume", "{id}"]},
}


def is_running(session_row: dict, now_ms: int) -> bool:
    """Running = any event with ``ts >= now - 120 s`` (``last_event_ts``), or the session
    reports ``status == 'active'`` with no ``ended_at``."""
    last = session_row.get("last_event_ts")
    if last is not None and last >= now_ms - RUNNING_WINDOW_MS:
        return True
    return session_row.get("status") == "active" and session_row.get("ended_at") is None


def build(session_row: dict, now_ms: int) -> dict:
    """``session_row``: session_uid, agent, native_id, cwd, status, ended_at, last_event_ts."""
    agent, native_id, cwd = (session_row.get(k) for k in ("agent", "native_id", "cwd"))
    running = is_running(session_row, now_ms)
    template = TEMPLATES.get(agent)
    commands = []
    if template and native_id and cwd:
        argv = [a.replace("{id}", native_id) for a in template["argv"]]
        commands.append({"label": template["label"],
                         "shell": f"cd {shlex.quote(cwd)} && {shlex.join(argv)}",
                         "argv": argv, "cwd": cwd, "verified": False, "note": "参数待验证"})
    if template is None:
        reason = "unsupported_agent"
    elif not native_id:
        reason = "unknown_session"
    elif not cwd:
        reason = "no_cwd"
    elif running:
        reason = "running"
    else:
        reason = None
    return {"session_uid": session_row.get("session_uid"), "agent": agent,
            "native_id": native_id, "cwd": cwd, "running": running,
            "available": reason is None, "disabled_reason": reason, "commands": commands}
