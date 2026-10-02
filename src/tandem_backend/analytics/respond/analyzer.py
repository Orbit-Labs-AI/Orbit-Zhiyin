"""Respond composition entry point with compatible public imports."""

from .calls import normalize_tool_calls, pair_tool_calls
from .features import tool_summary
from .relations import build_execution_relations, execution_intervals
from .rules import result_status
from .sequence import analyze_execution_sequence, workflow


def analyze_respond(events, calls, sessions, main_ids, dataset_status="available", supported_kinds=None,
                    event_status="available"):
    paired = pair_tool_calls(events or [])
    normalized = normalize_tool_calls(calls)
    effective = normalized["calls"] if calls is not None else paired["calls"] if paired["calls"] else None
    session_lookup = {s["session_uid"]: s for s in sessions}
    for c in effective or []:
        s = session_lookup.get(c["session_uid"], {})
        c.setdefault("root_session_uid", s.get("root_uid"))
    linked_results = {c.get("result_event_uid") for c in effective or [] if c.get("result_event_uid")}
    paired["orphan_result_event_uids"] = [uid for uid in paired["orphan_result_event_uids"] if uid not in linked_results]
    status = dataset_status if calls is not None else "partial" if effective else "unavailable"
    sequence = [] if effective is not None else None
    for c in effective or []:
        sequence.append({**c, "tool_result_status": result_status(c), "raw_status": c.get("status")})
    turn_ids = {(e["session_uid"], e["turn_uid"]) for e in events or [] if e.get("turn_uid")}
    relations = build_execution_relations(events, sessions)
    if events is None or (supported_kinds is not None and "subagent.spawn" not in supported_kinds):
        if not relations["subagent_relations"]:
            relations["subagent_relations"] = None
        relations["unresolved_subagent_events"] = None
    if events is None or (supported_kinds is not None and not {"branch", "context.restart"} & set(supported_kinds)):
        relations["rollback_restart_events"] = None
    return {"status": status, "grain": "tool_call", "tool_sequence": sequence,
            "call_source": "L3" if calls is not None else "paired_L2",
            "turn_count": len(turn_ids) if turn_ids else 0 if events == [] and event_status == "available" else None,
            "event_coverage": event_status,
            "turn_boundary_unknown_n": sum(not e.get("turn_uid") for e in events) if events is not None else None,
            "tools": tool_summary(effective, status),
            "workflow": workflow(events, effective, main_ids, supported_kinds) if events is not None else None,
            **analyze_execution_sequence(effective), **execution_intervals(effective),
            **relations,
            "pairing": {**{k: v for k, v in paired.items() if k != "calls"},
                        **{k: v for k, v in normalized.items() if k != "calls"}}}


__all__ = ['analyze_execution_sequence', 'analyze_respond', 'build_execution_relations', 'execution_intervals', 'normalize_tool_calls', 'pair_tool_calls', 'result_status', 'tool_summary', 'workflow']
