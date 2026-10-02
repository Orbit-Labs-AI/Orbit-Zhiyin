"""Synthetic evidence checks for the feature-to-display diagnostic mapping."""

import copy
import json
from pathlib import Path

import pytest

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.presentation.diagnostics import build_diagnostics
from tandem_backend.analytics.service import analyze_bundle


def _call(uid, *, sid="s", seq=1, name="shell", state="success"):
    return {"session_uid": sid, "call_uid": uid, "seq": seq, "name_raw": name,
            "kind": "shell", "tool_result_status": state}


def _analysis(calls=None, *, status="available", messages=None, durations=None):
    return {"bottleneck_features": {
        "interaction": {"status": status, "message_intents": messages,
                        "unknown_counts": {"human_origin": 0, "session_kind_messages": 0}},
        "respond": {"status": status, "tool_sequence": calls,
                    "failure_reasons": None if calls is None else [], "subagent_relations": []},
        "cost_time": {"durations": {"execution_durations": durations}},
    }}


def _intent(uid, state, intents, *, sid="s"):
    return {"session_uid": sid, "event_uid": uid, "state": state, "intents": intents}


def test_large_tool_vocabulary_reduces_matrix_without_losing_transitions():
    calls = [_call(f"c{i}", seq=i, name=f"tool-{i:03d}") for i in range(100)]
    matrix = build_diagnostics(_analysis(calls))["tools"]["transition_matrix"]
    assert len(matrix["nodes"]) == 20
    assert matrix["reduction"]["original_node_count"] == 100
    assert len(matrix["reduction"]["other_node_members"]) == 81
    assert matrix["nodes"][-1]["group"] == "other"
    assert matrix["counts"][-1][-1] == 80
    assert matrix["transition_count"] == sum(map(sum, matrix["counts"])) == 99
    assert all(sum(row) == pytest.approx(1) for row in matrix["probabilities"] if row[0] is not None)
    shuffled = build_diagnostics(_analysis(list(reversed(calls))))["tools"]["transition_matrix"]
    assert shuffled == matrix


def test_missing_empty_and_unreviewed_intents_are_distinct():
    missing = build_diagnostics({})
    assert missing["correction_rate"]["value"] is None
    assert missing["correction_rate"]["status"] == "unavailable"
    assert missing["tools"]["call_count"] is None
    assert missing["tools"]["transition_matrix"]["counts"] is None
    assert missing["findings"] == missing["recommendations"] == []

    empty = build_diagnostics(_analysis([], messages=[]))
    assert empty["tools"]["call_count"] == 0
    assert empty["tools"]["success_rate"]["value"] is None
    assert empty["correction_rate"]["numerator"] == 0
    assert empty["correction_rate"]["denominator"] == 0
    unknown = build_diagnostics(_analysis([], messages=[_intent("candidate", "candidate", None)]))
    assert unknown["correction_rate"]["numerator"] is None
    assert unknown["correction_rate"]["value"] is None
    assert unknown["correction_rate"]["unknown_n"] == 1
    assert unknown["findings"] == []


def test_empty_partial_source_is_not_a_known_zero():
    data = _analysis([], status="partial", messages=[])
    data["bottleneck_features"]["respond"]["retry_links"] = []
    data["bottleneck_features"]["outcome"] = {
        "status": "partial", "validation_runs": [], "acceptance_results": []}
    result = build_diagnostics(data)
    assert result["tools"]["call_count"] is None
    assert result["tools"]["transition_matrix"]["transition_count"] is None
    assert result["tools"]["failure_reasons"]["total_failure_records"] is None
    assert result["tools"]["confirmed_retry_count"] is None
    assert result["tools"]["candidate_retry_count"] is None
    for name in ("validation_failure_rate", "declared_criterion_pass_rate"):
        metric = result["outcomes"]["objective"][name]
        assert metric["value"] is None
        assert metric["numerator"] is None
        assert metric["known_n"] is None
        assert metric["unknown_n"] is None
    assert result["correction_rate"]["numerator"] is None
    assert result["recommendations"] == []


@pytest.mark.parametrize("status", ["unavailable", "excluded"])
def test_unavailable_source_masks_stale_rate_counts_and_evidence(status):
    data = _analysis([_call("failed", state="failed")], status=status,
                     messages=[_intent("c", "confirmed", ["correction"])])
    result = build_diagnostics(data)
    for metric in (result["correction_rate"], result["tools"]["error_rate"], result["tools"]["success_rate"]):
        assert metric["value"] is None
        assert metric["numerator"] is None
        assert metric["denominator"] is None
        assert metric["evidence_refs"] == []
        assert metric["status"] == "unavailable"
    assert result["findings"] == result["recommendations"] == []


def test_only_unknown_human_origins_do_not_imply_zero_confirmed_corrections():
    data = _analysis([], messages=[])
    data["bottleneck_features"]["interaction"]["unknown_counts"]["human_origin"] = 2
    correction = build_diagnostics(data)["correction_rate"]
    assert correction["value"] is None
    assert correction["numerator"] is None
    assert correction["denominator"] == 0
    assert correction["unknown_n"] == 2


def test_observed_empty_retry_source_preserves_known_zero():
    data = _analysis([], messages=[])
    data["bottleneck_features"]["respond"]["retry_links"] = []
    tools = build_diagnostics(data)["tools"]
    assert tools["confirmed_retry_count"] == tools["candidate_retry_count"] == 0


def test_correction_rate_pools_confirmed_messages_and_does_not_average_sessions():
    messages = [_intent("c", "confirmed", ["correction", "feedback"], sid="a")]
    messages += [_intent(str(i), "confirmed", ["request"], sid="b") for i in range(9)]
    messages += [_intent("lexical", "candidate", None), _intent("unlabeled", "unknown", None)]
    data = _analysis([], messages=messages)
    data["overview"] = {"counts": {"human_messages": 99, "correction_signal_rate": .99}}
    result = build_diagnostics(data)
    metric = result["correction_rate"]
    assert metric["numerator"] == 1
    assert metric["denominator"] == 10
    assert metric["value"] == .1  # not (1/1 + 0/9) / 2, nor lexical 0.99
    assert metric["unknown_n"] == 2
    assert metric["status"] == "partial"
    finding = result["findings"][0]
    assert finding["evidence_refs"] == [{"session_uid": "a", "event_uid": "c"}]
    assert finding["priority_score"] == pytest.approx(100 * .1 * 10 / 12, abs=.0001)
    assert result["recommendations"][0]["expected_effect"] is None
    assert result["recommendations"][0]["installable"] is False


def test_tool_success_is_pooled_known_completed_calls_with_nonterminal_states_separate():
    calls = [_call("failed", state="failed", name="a")]
    calls += [_call(str(i), seq=i, name="b", sid="b") for i in range(9)]
    calls += [_call(s, seq=i, state=s, sid="extra")
              for i, s in enumerate(("unknown", "running", "interrupted", "rejected"))]
    result = build_diagnostics(_analysis(calls))
    tools = result["tools"]
    assert tools["call_count"] == 14
    assert tools["success_rate"]["value"] == .9
    assert tools["error_rate"]["value"] == .1
    assert tools["success_rate"]["denominator"] == 10
    assert tools["unknown_status_count"] == 1
    assert [tools[k + "_count"] for k in ("running", "interrupted", "rejected")] == [1, 1, 1]
    assert tools["by_tool"][0]["success_rate"]["value"] == 1


def test_average_duration_excludes_estimates_missing_provenance_and_nonfinite_values():
    calls = [_call(str(i), seq=i) for i in range(5)]
    durations = [
        {"session_uid": "s", "call_uid": "0", "quality": "reliable", "execution_duration_ms": 0},
        {"session_uid": "s", "call_uid": "1", "quality": "reliable", "execution_duration_ms": 20},
        {"session_uid": "s", "call_uid": "2", "quality": "estimated", "estimated_log_gap_ms": 1000},
        {"session_uid": "s", "call_uid": "3", "execution_duration_ms": 90},
        {"session_uid": "s", "call_uid": "4", "quality": "reliable", "execution_duration_ms": float("nan")},
    ]
    duration = build_diagnostics(_analysis(calls, durations=durations))["tools"]["average_execution_duration_ms"]
    assert duration["value"] == 10
    assert duration["known_n"] == 2
    assert duration["estimated_n"] == 1
    assert duration["unknown_n"] == 2
    assert duration["estimated_log_gap_mean_ms"] == 1000
    assert duration["status"] == "partial"
    json.dumps(duration, allow_nan=False)


def test_transition_matrix_rows_normalize_and_do_not_cross_sessions():
    calls = [_call("a", seq=1, name="a"), _call("b", seq=2, name="b"),
             _call("c", seq=3, name="a"), _call("d", seq=4, name="c"),
             _call("single", sid="second", name="a")]
    matrix = build_diagnostics(_analysis(calls))["tools"]["transition_matrix"]
    assert matrix["transition_count"] == 3
    assert matrix["counts"] == [[0, 1, 1], [1, 0, 0], [0, 0, 0]]
    assert matrix["probabilities"] == [[0, .5, .5], [1, 0, 0], [None, None, None]]
    assert matrix["row_denominators"] == [2, 1, 0]
    assert len(matrix["evidence_refs"]) == 3
    assert "causal" in matrix["limitations"][0]


@pytest.mark.parametrize("second_seq", [None, True, 1])
def test_ambiguous_call_order_excludes_session_instead_of_inventing_edges(second_seq):
    matrix = build_diagnostics(_analysis([_call("a"), _call("b", seq=second_seq)]))["tools"]["transition_matrix"]
    assert matrix["transition_count"] == 0
    assert matrix["excluded_order_call_count"] == 2
    assert matrix["status"] == "partial"


def test_objective_checks_and_linked_subjective_feedback_are_not_merged():
    data = _analysis([])
    data["bottleneck_features"]["outcome"] = {
        "status": "available", "validation_runs": [
            {"session_uid": "s", "validation_uid": "v", "validation_result": "failed"},
            {"session_uid": "s", "validation_uid": "u", "validation_result": "unknown"}],
        "acceptance_results": [], "task_results": [],
    }
    data["overview"] = {"subjective_outcomes": {"status": "available", "unknown_n": 0,
        "counts": {"accepted_feedback_count": 1, "linked_feedback_count": 1, "rework_feedback_count": 0}}}
    outcomes = build_diagnostics(data)["outcomes"]
    assert outcomes["subjective"]["counts"]["accepted_feedback_count"] == 1
    assert outcomes["objective"]["validation_failure_rate"]["value"] == 1
    assert outcomes["objective"]["validation_failure_rate"]["unknown_n"] == 1
    assert outcomes["objective"]["declared_criterion_pass_rate"]["value"] is None
    assert outcomes["objective"]["project_completion"] is None
    assert outcomes["subjective"]["task_success"] is None


def test_failure_reason_unknown_is_not_guessed_and_no_unsupported_configuration_advice():
    data = _analysis([_call("bad", state="failed"), _call("denied", state="rejected", seq=2)])
    data["bottleneck_features"]["respond"]["failure_reasons"] = [
        {"session_uid": "s", "call_uid": "bad", "failure_reason": None},
        {"session_uid": "s", "call_uid": "denied", "failure_reason": "permission_denied"}]
    result = build_diagnostics(data)
    reasons = result["tools"]["failure_reasons"]
    assert reasons["unknown_reason_count"] == 1
    assert reasons["rows"][0]["reason"] == "permission_denied"
    assert reasons["rows"][0]["count"] == 1
    assert [r["category"] for r in result["recommendations"]] == ["workflow"]


def test_real_feature_fixture_maps_consistently_for_global_and_session_scopes():
    data = json.loads((Path(__file__).parents[1] / "fixtures" / "bottleneck-features-v1.json").read_text(encoding="utf-8"))
    analysis = analyze_bundle(AnalysisInputBundle.from_dict(data), Scope(), with_text=False)
    before = copy.deepcopy(analysis)
    result = build_diagnostics(analysis)
    session = analysis["sessions"][0]
    subview = {"bottleneck_features": session["bottleneck_features"], "sessions": [session],
               "overview": {"subjective_outcomes": session["subjective_outcomes"]}}
    scoped = build_diagnostics(subview)
    assert result["correction_rate"] == scoped["correction_rate"]
    assert result["tools"] == scoped["tools"]
    assert result["correction_rate"]["value"] == .5
    assert result["tools"]["success_rate"]["value"] == 1
    assert result["tools"]["average_execution_duration_ms"]["value"] == 8000
    assert result["outcomes"]["objective"]["declared_criterion_pass_rate"]["value"] == 1
    assert result["outcomes"]["objective"]["project_completion"] is None
    assert analysis == before
    assert build_diagnostics(analysis) == result
    json.dumps(result, allow_nan=False)
