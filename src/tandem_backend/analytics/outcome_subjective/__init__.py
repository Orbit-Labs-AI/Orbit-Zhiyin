"""Subjective outcomes: explicit human feedback about a prior delivery."""

import re

from ...privacy import direct_user_text


def extract_subjective_feedback(messages, deliveries):
    """Keep the existing same-task feedback contract while separating its family."""
    feedback = []
    for event in messages:
        task_id = event.get("attrs", {}).get("task_id")
        previous = [delivery for delivery in deliveries
                    if delivery["session_uid"] == event["session_uid"]
                    and delivery.get("attrs", {}).get("task_id") == task_id
                    and task_id and delivery["seq"] < event["seq"]]
        if not previous:
            continue
        delivery = max(previous, key=lambda item: item["seq"])
        text = direct_user_text(event.get("text") or "").strip()
        match = re.fullmatch(r"(可以了|这样可以|解决了|还是不行|不对|算了)[。！!\s]*", text)
        if match:
            feedback.append({"event_uid": event["event_uid"],
                             "delivery_event_uid": delivery["event_uid"],
                             "signal": "positive" if match[1] in ("可以了", "这样可以", "解决了") else "negative"})
    return feedback
