"""Copyable resume commands per session (DT-24). Builds strings only: never executes
anything and never touches the clipboard.

The per-agent CLI entry (argv, whether it needs the session's cwd, and the evidence for the
flag) is owned by the data layer, ``orbit_data.resume.TEMPLATES`` — seven agents, each with
the upstream source that confirms the flag. This module only adds what the gateway knows
better: whether the session is *running now* (recent events), stable ``disabled_reason``
codes for the UI and a Chinese label.
"""

from __future__ import annotations

from orbit_data.resume import TEMPLATES, resume_template

RUNNING_WINDOW_MS = 120_000
LABELS = {
    "claude_code": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "pi": "pi",
    "hermes": "Hermes", "dsh": "DeepSeek Harness", "kimi": "Kimi",
}


def is_running(session_row: dict, now_ms: int) -> bool:
    """Running = any event with ``ts >= now - 120 s`` (``last_event_ts``), or the session
    reports ``status == 'active'`` with no ``ended_at``."""
    last = session_row.get("last_event_ts")
    if last is not None and last >= now_ms - RUNNING_WINDOW_MS:
        return True
    return session_row.get("status") == "active" and session_row.get("ended_at") is None


def _reason(session_row: dict, template) -> str:
    """Why ``resume_template`` refused; mirrors its check order (id/file, then cwd)."""
    if (session_row.get("kind") or "main") != "main":
        return "not_root_session"
    for part in template.argv:
        if part in ("{id}", "{file}"):
            value = session_row.get("native_id" if part == "{id}" else "session_file")
            if not value:
                return "unknown_session"
            if value.startswith("-") or any(ord(char) < 32 for char in value):
                return "unsafe_session_id"
    return "no_cwd"


def build(session_row: dict, now_ms: int) -> dict:
    """``session_row``: session_uid, agent, native_id, cwd, status, ended_at, last_event_ts,
    optional ``kind`` (default main) and ``session_file`` (pi resumes by transcript path)."""
    agent, native_id, cwd = (session_row.get(k) for k in ("agent", "native_id", "cwd"))
    running = is_running(session_row, now_ms)
    template = TEMPLATES.get(agent)
    commands = []
    if template is None:
        reason = "unsupported_agent"
    else:
        result = resume_template(agent, native_id, kind=session_row.get("kind") or "main", cwd=cwd,
                                 session_file=session_row.get("session_file"))
        if result["supported"]:
            commands.append({"label": f"在 {LABELS.get(agent, agent)} 中继续", "shell": result["command"],
                             "argv": result["argv"], "cwd": cwd if template.needs_cwd else None,
                             "verified": result["verified"], "evidence": result["evidence"],
                             "note": None if result["verified"] else "参数待验证"})
            reason = "running" if running else None
        else:
            reason = _reason(session_row, template)
    return {"session_uid": session_row.get("session_uid"), "agent": agent,
            "native_id": native_id, "cwd": cwd, "running": running,
            "available": reason is None, "disabled_reason": reason, "commands": commands}
