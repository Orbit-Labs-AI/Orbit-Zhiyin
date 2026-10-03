"""AN-01.2 tool-call drilldown: the most recent N calls of one tool within a Scope.

Argument summaries pass through ``privacy.redact`` and are truncated; raw arguments
never leave the backend through this path.
"""

from typing import Any

from ..privacy import redact
from .context import AnalysisContext
from .signals.detectors import call_files, call_text, normalized_head

Record = dict[str, Any]
MAX_LIMIT = 50
SUMMARY_CHARS = 160


def _calls(context: AnalysisContext, result: Record | None) -> list[Record] | None:
    families = (result or {}).get("bottleneck_features") or context.families(set(context.session_map))
    return families["respond"]["tool_sequence"]


def argument_summary(call: Record) -> str | None:
    text = call_text(call) or " ".join(call_files(call))
    if not text:
        return None
    text = redact(" ".join(text.split()))
    return text if len(text) <= SUMMARY_CHARS else text[: SUMMARY_CHARS - 1] + "…"


def _matches(call: Record, name: str, command_head: str | None) -> bool:
    if name not in (call.get("name_raw"), call.get("name")):
        return False
    if command_head is None:
        return True
    wanted = normalized_head({"command_head": command_head})
    return normalized_head(call) == wanted or (call.get("command_head") or "").startswith(command_head)


def tool_calls(context: AnalysisContext, name: str, *, limit: int = 20,
               command_head: str | None = None, result: Record | None = None) -> Record:
    """Most recent calls first (``started_at`` then ``seq``); unclocked calls go last."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit 必须在 1–{MAX_LIMIT}")
    calls = _calls(context, result)
    if calls is None:
        return {"status": "unavailable", "name": name, "total": None, "limit": limit, "items": None}
    matched = [c for c in calls if _matches(c, name, command_head)]
    matched.sort(key=lambda c: (c.get("started_at") is not None, c.get("started_at") or 0,
                                c.get("seq") or 0, c["call_uid"]), reverse=True)
    items = [{"call_uid": c["call_uid"], "session_uid": c["session_uid"],
              "root_session_uid": c.get("root_session_uid"), "event_uid": c.get("call_event_uid"),
              "result_event_uid": c.get("result_event_uid"), "name": c.get("name_raw") or c.get("name"),
              "kind": c.get("kind"),
              "command_head": redact(c["command_head"]) if c.get("command_head") else None,
              "argument_summary": argument_summary(c),
              "status": c.get("tool_result_status"), "exit_code": c.get("exit_code"),
              "duration_ms": c.get("duration_ms"), "duration_quality": c.get("duration_quality"),
              "started_at": c.get("started_at"), "seq": c.get("seq")}
             for c in matched[:limit]]
    return {"status": "available", "name": name, "command_head": command_head,
            "total": len(matched), "limit": limit, "items": items}
