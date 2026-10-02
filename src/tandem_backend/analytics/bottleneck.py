"""Compose the four non-semantic bottleneck families after one shared selection."""

from .cost_time import analyze_cost_time
from .interaction import analyze_interaction
from .outcome import analyze_outcome
from .respond import analyze_respond

FAMILY_VERSION = "bottleneck-features-v1"


def analyze_bottleneck(sessions, events, calls, model_calls, main_ids, scope, coverage,
                       context_events=(), supported_kinds=None):
    execution_events = None if events is None else list({
        (e["session_uid"], e["event_uid"]): e for e in [*events, *context_events]}.values())
    event_status = coverage.get("events", {}).get("status", "partial")
    tool_status = coverage.get("tool_calls", {}).get("status", "partial")
    respond = analyze_respond(execution_events, calls, sessions, main_ids, tool_status, supported_kinds,
                              event_status=event_status)
    effective_calls = respond["tool_sequence"]
    return {"schema_version": FAMILY_VERSION,
            "included_session_uids": sorted(s["session_uid"] for s in sessions),
            "source_coverage": {k: coverage.get(k, {"status": "unavailable"})
                                for k in ("events", "tool_calls", "model_calls", "turns", "lineage")},
            "interaction": analyze_interaction(events, main_ids, scope.until_ts, event_status,
                unknown_session_ids={s["session_uid"] for s in sessions if s.get("kind") in (None, "unknown")}),
            "respond": respond,
            "cost_time": analyze_cost_time(sessions, events, effective_calls, model_calls, main_ids, scope,
                records_complete=coverage.get("model_calls", {}).get("status") == "available",
                intervals=respond["execution_intervals"]),
            "outcome": analyze_outcome(effective_calls, events, main_ids, scope.until_ts, respond["status"])}
