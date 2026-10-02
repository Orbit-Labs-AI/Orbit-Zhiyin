"""Interaction composition entry point; extraction lives in features and rules."""

from .features import classify_message_intents, locate_interventions, summarize_interactions
from .rules import correction_terms


def analyze_interaction(events, main_ids, until_ts=None, dataset_status="available", unknown_session_ids=()):
    if events is None:
        return {"status": "unavailable", "message_intents": None, "intervention_points": None,
                "confirmed_correction_count": None, "confirmed_correction_rate": None,
                "repeated_requirement_count": None, "friction_types": None,
                "effective_samples": {"human_messages": 0}, "unknown_counts": {"human_origin": None}}
    rows = classify_message_intents(events, main_ids, until_ts)
    summary = summarize_interactions(rows)
    summary["unknown_counts"]["human_origin"] = sum(
        e["kind"] == "message.user" and e["session_uid"] in main_ids
        and (e.get("attrs", {}).get("origin") in (None, "unknown")
             or (e.get("attrs", {}).get("origin") == "human" and e.get("actor") not in ("human", "user")))
        for e in events)
    summary["unknown_counts"]["session_kind_messages"] = sum(
        e["kind"] == "message.user" and e["session_uid"] in unknown_session_ids for e in events)
    if not rows and (dataset_status != "available" or summary["unknown_counts"]["human_origin"]
                    or summary["unknown_counts"]["session_kind_messages"]):
        summary.update(confirmed_correction_count=None, repeated_requirement_count=None)
    return {"status": dataset_status, "grain": "human_message", **summary,
            "message_intents": rows, "intervention_points": locate_interventions(events, main_ids)}


__all__ = ['analyze_interaction', 'classify_message_intents', 'correction_terms', 'locate_interventions', 'summarize_interactions']
