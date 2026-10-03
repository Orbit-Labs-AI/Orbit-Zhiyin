"""Constructed expected labels: executable regression corpus, not human accuracy claims.

Cases with ``split = recall-v1.3`` were written as everyday phrasings *before* checking the
rules (audit B9) and are scored per feature instead of requiring an exact match, so a
known miss stays visible as recall < 1 rather than being edited out of the corpus.
"""

import json
from pathlib import Path

import pytest

from orbit_backend.analytics.instruction import extract_instruction_constraints

CASES = json.loads((Path(__file__).parents[2] / "fixtures" / "instruction-quality.json").read_text())


def labels(case):
    event = {"event_uid": case["id"], "session_uid": "s", "seq": 0, "ts": 0,
             "kind": "message.user", "actor": "human", "text": case["text"], "attrs": {"origin": "human"}}
    row = extract_instruction_constraints([event], main_ids={"s"})[0]
    return {name: sorted({c["value"] for c in items}) for name, items in row["features"].items() if items}


@pytest.mark.parametrize("case", [c for c in CASES if "split" not in c], ids=lambda c: c["id"])
def test_expected_fields_values_and_no_false_positive(case):
    assert labels(case) == case["expected"]


RECALL = [c for c in CASES if c.get("split") == "recall-v1.3"]
# Floors sit just under the measured v1.3 values (recall 41/42 messages, no false positive
# on 41 negatives); a regression below them fails, an improvement does not.
MIN_RECALL, MIN_PRECISION = 0.9, 0.95


def test_recall_corpus_size():
    assert sum(bool(c["expected"]) for c in RECALL) >= 40
    assert sum(not c["expected"] for c in RECALL) >= 40


def test_per_feature_recall_and_precision():
    tp, fp, fn = {}, {}, {}
    for case in RECALL:
        actual, expected = labels(case), case["expected"]
        for feature in set(actual) | set(expected):
            got, want = set(actual.get(feature, [])), set(expected.get(feature, []))
            tp[feature] = tp.get(feature, 0) + len(got & want)
            fp[feature] = fp.get(feature, 0) + len(got - want)
            fn[feature] = fn.get(feature, 0) + len(want - got)
    report = {f: {"recall": tp[f] / (tp[f] + fn[f]) if tp[f] + fn[f] else None,
                  "precision": tp[f] / (tp[f] + fp[f]) if tp[f] + fp[f] else None,
                  "tp": tp[f], "fp": fp[f], "fn": fn[f]} for f in sorted(tp)}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    total_tp, total_fp, total_fn = sum(tp.values()), sum(fp.values()), sum(fn.values())
    assert total_tp / (total_tp + total_fn) >= MIN_RECALL, report
    assert total_tp / (total_tp + total_fp) >= MIN_PRECISION, report
    for feature, row in report.items():
        if row["tp"] + row["fn"] >= 5:  # per-feature floors only where the sample is not tiny
            assert row["recall"] >= 0.75, (feature, row)
        assert row["precision"] is None or row["precision"] >= 0.9, (feature, row)


SUBJECTIVE = [c for c in json.loads(
    (Path(__file__).parents[2] / "fixtures" / "subjective-outcome-quality.json").read_text())
    if c.get("split") == "recall-v1.1"]


def test_short_acknowledgements_are_accepted_only_without_follow_up_request():
    """Explicit-feedback recall for closing acknowledgements (audit B10) with precision on negatives."""
    from orbit_backend.analytics.outcome_subjective.extraction import classify_feedback

    positives = [c for c in SUBJECTIVE if c["expected"]]
    negatives = [c for c in SUBJECTIVE if not c["expected"]]
    assert len(positives) >= 15 and len(negatives) >= 15
    hits = [c["text"] for c in positives
            if (classify_feedback(c["text"]) or {}).get("user_acceptance") == "accepted"]
    false = [c["text"] for c in negatives if classify_feedback(c["text"]) is not None]
    recall = len(hits) / len(positives)
    precision = len(hits) / (len(hits) + len(false)) if hits else 0.0
    print({"accepted_recall": recall, "accepted_precision": precision})
    assert recall >= 0.9, sorted({c["text"] for c in positives} - set(hits))
    assert precision >= 0.95, false
