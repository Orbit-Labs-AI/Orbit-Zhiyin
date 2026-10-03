"""Evidence counts and per-delivery history; silence remains an unknown outcome."""

from collections import Counter


def summarize_subjective_outcomes(feedback, deliveries, *, status="available", human_message_count=None,
                                  unknown_origin_count=0, unmeasurable_text_count=0):
    """Count linked messages, never satisfaction or task success; silence stays unknown."""
    if feedback is None or deliveries is None or status in ("unavailable", "excluded"):
        return {"status": status if status in ("unavailable", "excluded") else "unavailable",
                "counts": None, "effective_n": 0, "unknown_n": None,
                "unknown_reasons": None, "delivery_states": None, "task_success": None}
    linked = [f for f in feedback if f["link_status"] == "linked"]
    unresolved = [f for f in feedback if f["link_status"] != "linked"]
    states = {(d["session_uid"], d["delivery_event_uid"]): {
        "session_uid": d["session_uid"], "task_id": d.get("task_id"),
        "delivery_event_uid": d["delivery_event_uid"], "artifact_id": d.get("artifact_id"),
        "artifact_version": d.get("artifact_version"), "feedback_event_uids": [],
        "latest_feedback_event_uid": None, "latest_user_acceptance": None,
        "latest_user_confirmed_completion": None, "completion_scope": None,
        "latest_rework_requested": None, "available_at": None} for d in deliveries}
    for f in sorted(linked, key=lambda f: (f["session_uid"], f["seq"], f["event_uid"])):
        state = states[(f["session_uid"], f["delivery_event_uid"])]
        state["feedback_event_uids"].append(f["event_uid"])
        state.update(latest_feedback_event_uid=f["event_uid"], latest_user_acceptance=f["user_acceptance"],
                     latest_user_confirmed_completion=f["user_confirmed_completion"],
                     completion_scope=f["completion_scope"], latest_rework_requested=bool(f["rework_feedback"]),
                     available_at=f["available_at"])
    human_message_count = len(feedback) if human_message_count is None else human_message_count
    counts = {"recognized_feedback_count": len(feedback), "linked_feedback_count": len(linked),
              "unresolved_feedback_count": len(unresolved), "observed_delivery_count": len(states),
              "deliveries_without_feedback": sum(not s["feedback_event_uids"] for s in states.values()),
              "human_message_count": human_message_count,
              "unclassified_message_count": human_message_count - len(feedback),
              "accepted_feedback_count": sum(f["user_acceptance"] == "accepted" for f in linked),
              "rejected_feedback_count": sum(f["user_acceptance"] == "rejected" for f in linked),
              "mixed_acceptance_count": sum(f["user_acceptance"] == "mixed" for f in linked),
              "confirmed_completion_count": sum(f["user_confirmed_completion"] is True for f in linked),
              "confirmed_incompletion_count": sum(f["user_confirmed_completion"] is False for f in linked),
              "rework_feedback_count": sum(bool(f["rework_feedback"]) for f in linked)}
    unknowns = dict(Counter(f["link_reason"] for f in unresolved))
    unknowns.update(human_origin=unknown_origin_count, unmeasurable_text=unmeasurable_text_count)
    inferred = [f for f in feedback if f.get("label_source") == "semantic_model"]
    return {"status": "partial" if status != "available" or unresolved or unknown_origin_count or unmeasurable_text_count else "available",
            "counts": counts, "effective_n": len(linked), "unknown_n": len(unresolved) + unknown_origin_count + unmeasurable_text_count,
            "unknown_reasons": unknowns, "delivery_states": list(states.values()), "task_success": None,
            **({"semantic_observations": {"feedback_count": len(inferred),
                "targeted_feedback_count": sum(bool(f["delivery_event_uid"]) for f in inferred),
                "partial_acceptance_count": sum(f["user_acceptance"] == "partial" for f in inferred),
                "rework_count": sum(bool(f["rework_feedback"]) for f in inferred),
                "quality": "model_inferred", "calibrated_probability": None,
                "evidence_event_uids": [f["event_uid"] for f in inferred]}} if inferred else {})}
