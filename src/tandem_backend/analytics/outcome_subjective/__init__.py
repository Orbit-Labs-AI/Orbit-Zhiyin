"""Outcome subjective family: extraction, object linkage and evidence-only summaries."""

from .extraction import RULE_VERSION, collect_deliveries, extract_subjective_feedback
from .summary import summarize_subjective_outcomes


def analyze_subjective_outcomes(events, main_ids, event_status="available"):
    """Run the family on already selected events; never recover out-of-window feedback."""
    if events is None or event_status in ("unavailable", "excluded"):
        return {**summarize_subjective_outcomes(None, None, status=event_status),
                "feedback": None, "deliveries": None, "rule_version": RULE_VERSION}
    eligible = [e for e in events if e["session_uid"] in main_ids and e["kind"] == "message.user"
                and not e.get("attrs", {}).get("replayed_from") and not e.get("attrs", {}).get("duplicate_of")]
    humans = [e for e in eligible if e.get("attrs", {}).get("origin") == "human"
              and e.get("actor") in ("human", "user")]
    unknown = sum(e.get("attrs", {}).get("origin", "unknown") == "unknown"
                  or (e.get("attrs", {}).get("origin") == "human" and e.get("actor") not in ("human", "user"))
                  for e in eligible)
    # Unknown session kinds cannot contribute semantics, but their user rows are not observed zeros.
    unknown += sum(e["session_uid"] not in main_ids and e["kind"] == "message.user" for e in events)
    deliveries = collect_deliveries(events, main_ids)
    feedback = extract_subjective_feedback(humans, deliveries, main_ids)
    recognized = {f["event_uid"] for f in feedback}
    missing = sum(e.get("text") is None or (bool(e.get("text_truncated")) and e["event_uid"] not in recognized) for e in humans)
    return {**summarize_subjective_outcomes(feedback, deliveries, status=event_status,
                human_message_count=len(humans), unknown_origin_count=unknown, unmeasurable_text_count=missing),
            "feedback": feedback, "deliveries": deliveries, "rule_version": RULE_VERSION}


def aggregate_subjective_outcomes(reports, event_status="available"):
    """Reuse session evidence for project/global totals with the same denominator."""
    if event_status in ("unavailable", "excluded"):
        return summarize_subjective_outcomes(None, None, status=event_status)
    result = summarize_subjective_outcomes(
        [f for report in reports for f in report["feedback"] or []],
        [d for report in reports for d in report["deliveries"] or []],
        status="partial" if any(r["status"] != "available" for r in reports) else event_status,
        human_message_count=sum((r["counts"] or {}).get("human_message_count", 0) for r in reports),
        unknown_origin_count=sum((r["unknown_reasons"] or {}).get("human_origin", 0) for r in reports),
        unmeasurable_text_count=sum((r["unknown_reasons"] or {}).get("unmeasurable_text", 0) for r in reports))
    # Evidence and version histories live in session detail, keeping overview responses compact.
    result.pop("delivery_states", None)
    return result
