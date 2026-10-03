"""Hand-computed confidence / severity / recurrence for each of the seven bottleneck rules.

Default policy (``RecommendationPolicy()``); formulas documented in ``rules.py``:
confidence = coverage * min(1, n / target_n), recurrence = min(1, count / (3 * minimum)).
"""

import pytest

from orbit_backend.analytics.recommendations.policy import RecommendationPolicy
from orbit_backend.analytics.recommendations.rules import evaluate_features

CONTEXT = {"root_session_uid": "s"}


def signal(features, rule):
    signals, _ = evaluate_features(features, RecommendationPolicy(), CONTEXT)
    found = [s for s in signals if s["rule_id"] == rule]
    assert len(found) == 1, [s["rule_id"] for s in signals]
    return found[0]


def scores(s):
    return s["coverage"], s["confidence"], s["severity"], s["recurrence"]


def intent(i, intents, **extra):
    return {"state": "confirmed", "source": "user", "event_uid": f"e{i}", "session_uid": "s",
            "seq": i, "intents": intents, "task_uid": "t", **extra}


def test_correction_density_scores():
    # 10 confirmed of 10 human messages, 4 corrections: coverage 1, rate .4.
    rows = [intent(i, ["correction"] if i < 4 else ["request"], target_event_uid=f"x{i}",
                   evidence_event_uids=[f"x{i}"]) for i in range(10)]
    features = {"interaction": {"message_intents": rows, "effective_samples": {"human_messages": 10}}}
    # confidence 1 * 10/16; severity .4 / .5; recurrence 4 / 9.
    assert scores(signal(features, "correction_density")) == (1.0, 0.625, 0.8, 0.4444)


def test_repeated_requirements_scores_and_evidence_is_the_repeats():
    rows = [intent(i, ["request"], requirements=[{"object_uid": "o", "requirement_uid": r}])
            for i, r in enumerate(["r1", "r1", "r1", "r2", "r3"])]
    features = {"interaction": {"message_intents": rows, "effective_samples": {"human_messages": 5}}}
    s = signal(features, "repeated_requirements")
    # n 5, target 8 → .625; severity 2 / 4; recurrence 2 / 6.
    assert scores(s) == (1.0, 0.625, 0.5, 0.3333)
    assert [e["id"] for e in s["evidence"]] == ["e1", "e2"]


def test_identical_retries_coverage_is_the_decidable_link_share():
    status = {"c0": "failed", "c1": "failed", "c2": "failed", "c3": "success",
              "c4": "failed", "c5": "failed", "c6": "success", "c7": "success"}
    calls = [{"session_uid": "s", "call_uid": uid, "tool_result_status": st} for uid, st in status.items()]
    link = {"session_uid": "s", "state": "confirmed", "same_arguments": True, "task_uid": "t",
            "status_scope": "command"}
    links = [{**link, "from_call_uid": "c0", "to_call_uid": "c1"},
             {**link, "from_call_uid": "c2", "to_call_uid": "c3"},
             {**link, "from_call_uid": "c4", "to_call_uid": "c5", "state": "candidate",
              "status_scope": "unknown"},  # undecidable
             {**link, "from_call_uid": "c6", "to_call_uid": "c7", "same_arguments": False}]
    features = {"respond": {"tool_sequence": calls, "retry_links": links}}
    # 3 of 4 links decidable; n = 2 retries, target 4 → .75 * .5; severity 2/4; recurrence 2/6.
    assert scores(signal(features, "identical_retries")) == (0.75, 0.375, 0.5, 0.3333)


def test_tool_failures_scores():
    statuses = ["failed"] * 4 + ["success"] * 6 + ["unknown"] * 2
    calls = [{"session_uid": "s", "call_uid": f"c{i}", "name_raw": "bash", "kind": "shell",
              "tool_result_status": st, "result_event_uid": f"r{i}"} for i, st in enumerate(statuses)]
    features = {"respond": {"tool_sequence": calls}}
    # coverage 10/12; confidence .8333 * 10/20; severity .4/.4; recurrence 4/9.
    assert scores(signal(features, "tool_failures")) == (0.8333, 0.4167, 1.0, 0.4444)


def test_validation_failures_scores():
    scope = {"project_id": "p", "artifact_uid": "a", "artifact_revision": "1", "coverage": "unit"}
    runs = [{"session_uid": "s", "root_session_uid": "s", "task_uid": "t", "kind": "test",
             "validation_uid": f"v{i}", "validation_scope": scope, "validation_result": result,
             "validation_evidence": {"result_event_uid": f"r{i}"}}
            for i, result in enumerate(["failed", "failed", "passed"])]
    features = {"outcome": {"validation_runs": runs}}
    # n 3 known, target 4 → 1 * .75; severity 2/3; recurrence 2/6.
    assert scores(signal(features, "validation_failures")) == (1.0, 0.75, 0.6667, 0.3333)


def test_acceptance_evidence_gap_scores():
    results = [{"session_uid": "s", "task_uid": "t", "criteria_set_uid": "cs", "criterion_uid": f"k{i}",
                "source": "user", "evidence_event_uid": f"e{i}", "acceptance_result": result,
                "missing_reason": "no_matching_validation" if result == "unknown" else None}
               for i, result in enumerate(["unknown", "unknown", "unknown", "passed"])]
    features = {"outcome": {"acceptance_results": results},
                "source_coverage": {"tool_calls": {"status": "available"}}}
    # n 4, target 4 → 1; severity 3/4; recurrence 3/6.
    assert scores(signal(features, "acceptance_evidence_gap")) == (1.0, 1.0, 0.75, 0.5)


def test_context_pressure_scores():
    usage = {"status": "available", "total_basis": "call_delta", "request_count": 5,
             "total_tokens": 100_000, "token_buckets": {"input_tokens": 90_000},
             "request_evidence": [{"session_uid": "s", "call_uid": f"m{i}"} for i in range(5)]}
    features = {"cost_time": {"usage": usage},
                "respond": {"workflow": {"sequences": {"s": [["COMPACTION", "ev1"]]}}}}
    # n 5, target 10 → .5; severity 90k/100k; recurrence 1 corroboration / 3.
    assert scores(signal(features, "context_pressure")) == (1.0, 0.5, 0.9, 0.3333)


@pytest.mark.parametrize("bump", [1, 3])
def test_retry_coverage_counts_unrecorded_candidate_links_as_undecidable(bump):
    calls = [{"session_uid": "s", "call_uid": f"c{i}", "tool_result_status": "failed"} for i in range(4)]
    link = {"session_uid": "s", "state": "confirmed", "same_arguments": True, "task_uid": "t",
            "status_scope": "command"}
    links = [{**link, "from_call_uid": "c0", "to_call_uid": "c1"},
             {**link, "from_call_uid": "c2", "to_call_uid": "c3"}]
    extra = [{**link, "from_call_uid": f"u{i}", "to_call_uid": f"v{i}", "state": "candidate"}
             for i in range(bump)]  # calls not recorded → undecidable
    base = signal({"respond": {"tool_sequence": calls, "retry_links": links}}, "identical_retries")
    noisy = signal({"respond": {"tool_sequence": calls, "retry_links": links + extra}},
                   "identical_retries")
    assert base["coverage"] == 1.0
    assert noisy["coverage"] == round(2 / (2 + bump), 4)  # undecidable links do lower coverage
