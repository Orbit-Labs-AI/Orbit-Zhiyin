"""Constructed quality cases are separate from mock transport and real-data checks."""

import json
from pathlib import Path

import pytest

from tandem_backend.analytics.outcome_subjective import analyze_subjective_outcomes

CASES = json.loads((Path(__file__).parents[1] / "fixtures/subjective-outcome-quality.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_constructed_feedback_quality(case):
    events = [
        {"event_uid": "d", "session_uid": "s", "seq": 1, "kind": "message.assistant",
         "actor": "assistant", "text": "已交付", "attrs": {"phase": "final", "task_id": "task"}},
        {"event_uid": "f", "session_uid": "s", "seq": 2, "kind": "message.user",
         "actor": "human", "text": case["text"], "attrs": {"origin": "human", "task_id": "task"}},
    ]
    result = analyze_subjective_outcomes(events, {"s"})
    feedback = result["feedback"]
    observed = [feedback[0]["user_acceptance"], feedback[0]["user_confirmed_completion"],
                bool(feedback[0]["rework_feedback"])] if feedback else None
    assert observed == case["expected"]
    assert result["effective_n"] == int(case["expected"] is not None)
    assert result["task_success"] is None
