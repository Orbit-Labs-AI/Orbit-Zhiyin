"""Constructed quality cases are separate from mock transport and real-data checks.

Cases without a ``split`` are the rule contract and must match exactly. Cases with a ``split``
are recall/precision probes: they are scored in aggregate and the misses are reported, so a
missed weak acceptance shows up as a lower recall instead of being fitted away case by case.
``recall-v1.1`` (fixture) was written alongside the v1.1 rules; ``heldout-r2`` (below) was
labelled by reading each message before running the rule, and its misses stay in the set.
"""

import json
from pathlib import Path

import pytest

from tandem_backend.analytics.outcome_subjective import analyze_subjective_outcomes

CASES = json.loads((Path(__file__).parents[1] / "fixtures/subjective-outcome-quality.json").read_text())
CONTRACT = [case for case in CASES if not case.get("split")]
ACCEPT = ["accepted", None, False]
# Labelled before running the rule (round-2 audit). Positive = a plain acceptance of the
# delivered work; negative = question, hypothetical, quotation, follow-up request or rejection.
HELDOUT = [
    {"id": "r2-pos-01", "text": "可以，就这样", "expected": ACCEPT},
    {"id": "r2-pos-02", "text": "搞定了，谢谢", "expected": ACCEPT},
    {"id": "r2-pos-03", "text": "looks good", "expected": ACCEPT},
    {"id": "r2-pos-04", "text": "works now, thanks", "expected": ACCEPT},
    {"id": "r2-pos-05", "text": "没毛病", "expected": ACCEPT},
    {"id": "r2-pos-06", "text": "行，就这么办", "expected": ACCEPT},
    {"id": "r2-pos-07", "text": "great, that works", "expected": ACCEPT},
    {"id": "r2-pos-08", "text": "效果不错，辛苦", "expected": ACCEPT},
    {"id": "r2-neg-01", "text": "looks good?", "expected": None},
    {"id": "r2-neg-02", "text": "行不行啊", "expected": None},
    {"id": "r2-neg-03", "text": "搞定了吗", "expected": None},
    {"id": "r2-neg-04", "text": "works now? check the logs", "expected": None},
    {"id": "r2-neg-05", "text": "如果效果不错就发布", "expected": None},
]
PROBES = [case for case in CASES if case.get("split")] + [{**c, "split": "heldout-r2"} for c in HELDOUT]


def observe(text):
    events = [
        {"event_uid": "d", "session_uid": "s", "seq": 1, "kind": "message.assistant",
         "actor": "assistant", "text": "已交付", "attrs": {"phase": "final", "task_id": "task"}},
        {"event_uid": "f", "session_uid": "s", "seq": 2, "kind": "message.user",
         "actor": "human", "text": text, "attrs": {"origin": "human", "task_id": "task"}},
    ]
    result = analyze_subjective_outcomes(events, {"s"})
    feedback = result["feedback"]
    observed = [feedback[0]["user_acceptance"], feedback[0]["user_confirmed_completion"],
                bool(feedback[0]["rework_feedback"])] if feedback else None
    return observed, result


@pytest.mark.parametrize("case", CONTRACT, ids=[case["id"] for case in CONTRACT])
def test_constructed_feedback_quality(case):
    observed, result = observe(case["text"])
    assert observed == case["expected"]
    assert result["effective_n"] == int(case["expected"] is not None)
    assert result["task_success"] is None


def test_split_probes_report_recall_and_precision(capsys):
    """Aggregate scores per split; no per-case exact match. Floors are regression floors set
    just under the measured values of this commit, not quality targets."""
    lines = []
    for split in sorted({case["split"] for case in PROBES}):
        cases = [case for case in PROBES if case["split"] == split]
        hits = [(case, observe(case["text"])[0]) for case in cases]
        positives = [(c, o) for c, o in hits if c["expected"] is not None]
        tp = sum(o == c["expected"] for c, o in positives)
        fp = sum(o is not None and o != c["expected"] for c, o in hits)
        recall = tp / len(positives)
        precision = tp / (tp + fp) if tp + fp else None
        missed = [c["text"] for c, o in positives if o != c["expected"]]
        false = [c["text"] for c, o in hits if o is not None and o != c["expected"]]
        lines.append(f"{split}: n={len(cases)} recall={recall:.3f} precision={precision} "
                     f"missed={missed} false={false}")
        assert precision is None or precision >= 0.9, (split, false)
        assert recall >= {"recall-v1.1": 0.9, "heldout-r2": 0.3}[split], (split, missed)
    with capsys.disabled():
        print("\n" + "\n".join(lines))
