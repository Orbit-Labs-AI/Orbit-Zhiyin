"""Fictional records only: recommendations must preserve feature uncertainty."""

import copy
import json

import pytest

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.recommendations import RecommendationPolicy, recommend_bottlenecks
from tandem_backend.analytics.service import analyze_bundle

RULE_IDS = {
    "correction_density", "repeated_requirements", "identical_retries", "tool_failures",
    "validation_failures", "acceptance_evidence_gap", "context_pressure",
}
VALIDATION_SCOPE = {
    "project_id": "p", "artifact_uid": "synthetic-app", "artifact_revision": "v1", "coverage": "full",
}


def event(uid, seq, kind="message.user", **attrs):
    return {
        "event_uid": uid, "session_uid": "s", "turn_uid": "turn-1", "seq": seq,
        "kind": kind, "actor": "human" if kind == "message.user" else "assistant",
        "ts": 100 + seq * 10, "text": "synthetic request",
        "attrs": {"origin": "human", "task_uid": "task-1", **attrs},
    }


def annotation(**values):
    return {
        "state": "confirmed", "source": "synthetic-reviewer", "available_at": 100,
        "intents": ["request"], **values,
    }


def tool_call(uid, seq=10, **values):
    return {
        "call_uid": uid, "session_uid": "s", "turn_uid": "turn-1", "task_uid": "task-1",
        "call_event_uid": "call-" + uid, "result_event_uid": "result-" + uid,
        "seq": seq, "result_seq": seq + 1, "name_raw": "exec_command", "kind": "shell",
        "status": "success", "status_scope": "command", "started_at": 100 + seq * 10,
        "ended_at": 110 + seq * 10, "argument_digest": "digest-" + uid,
        "argument_digest_kind": "sha256", **values,
    }


def model_request(uid, **values):
    return {
        "call_uid": uid, "session_uid": "s", "turn_uid": "turn-1", "model_id": "synthetic-model",
        "usage_scope": "call", "measurement": "delta", "boundary_reliable": True,
        "coverage": "self", "ts": 200, "input_tokens": 4000, "cache_read_tokens": 0,
        "cache_write_tokens": 0, "output_tokens": 100, **values,
    }


def validation(**values):
    return {
        "kind": "test", "executed": True, "source": "synthetic-validator", "available_at": 100,
        "scope": dict(VALIDATION_SCOPE), "criterion_uids": ["unit-tests"], **values,
    }


def acceptance(**values):
    return {
        "state": "confirmed", "source": "synthetic-instructions", "available_at": 100,
        "criteria_set_uid": "acceptance-v1", "complete": True, "scope": dict(VALIDATION_SCOPE),
        "criteria": [{"criterion_uid": "unit-tests", "kind": "test"},
                     {"criterion_uid": "package-build", "kind": "build"}], **values,
    }


def analysis(events=(), calls=(), models=(), *, tool_status="available", scope=None, sessions=None):
    """Pass synthetic records through production selection and feature extraction."""
    events = copy.deepcopy(list(events))
    for c in calls or []:
        start = event(c["call_event_uid"], c["seq"], "tool.call", task_uid=c.get("task_uid"),
                      name_raw=c["name_raw"], category=c["kind"], call_id=c["call_uid"])
        start.update(session_uid=c["session_uid"], ts=c["started_at"])
        result = event(c["result_event_uid"], c["result_seq"], "tool.result",
                       task_uid=c.get("task_uid"), call_id=c["call_uid"])
        result.update(session_uid=c["session_uid"], ts=c["ended_at"])
        events.extend([start, result])
    coverage = {name: {"status": "available"} for name in
                ("events", "sessions", "tool_calls", "model_calls", "turns", "projects", "lineage")}
    coverage["tool_calls"] = {"status": tool_status}
    if calls is None:
        coverage["tool_calls"] = {"status": "unavailable"}
    if models is None:
        coverage["model_calls"] = {"status": "unavailable"}
    bundle = AnalysisInputBundle(
        sessions=sessions if sessions is not None else [
            {"session_uid": "s", "root_uid": "s", "kind": "main", "project_id": "p", "started_at": 0}],
        events=events, tool_calls=copy.deepcopy(calls), model_calls=copy.deepcopy(models), coverage=coverage,
        projects=[{"project_id": "p", "name": "synthetic fixture"}],
    )
    return analyze_bundle(bundle, scope=scope, with_text=False)


def correction_events(known=8, corrected=3, unknown=0):
    rows = [event("delivery", 0, "message.assistant")]
    for i in range(known):
        a = annotation()
        if i < corrected:
            a.update(intents=["correction"], target_event_uid="delivery")
        rows.append(event(f"human-{i}", i + 1, interaction=a))
    rows.extend(event(f"unknown-{i}", known + i + 1) for i in range(unknown))
    return rows


def retry_calls(count=3, **values):
    return [tool_call(f"retry-{i}", seq=10 + i * 2, status="failed", argument_digest="same-arguments", **values)
            for i in range(count)]


def recommend(data, **values):
    return recommend_bottlenecks(data, catalog=[], **values)


def assessment(result, rule_id):
    rows = [r for r in result["assessments"] if r["rule_id"] == rule_id]
    assert len(rows) == 1
    assert rows[0]["reason"]
    return rows[0]["status"]


def test_empty_available_dataset_has_no_recommendations_and_complete_assessments():
    result = recommend(analysis())
    assert result["recommendations"] == []
    assert result["signals"] == []
    assert {a["rule_id"] for a in result["assessments"]} == RULE_IDS
    assert all(a["status"] in {"below_threshold", "insufficient_evidence"} for a in result["assessments"])
    assert result["schema_version"] and result["catalog_digest"]
    json.dumps(result, allow_nan=False)


def test_default_policy_can_be_passed_explicitly_without_changing_results():
    data = analysis(correction_events())
    assert recommend(data) == recommend(data, policy=RecommendationPolicy())


def test_confirmed_correction_boundary_triggers():
    result = recommend(analysis(correction_events()))
    assert assessment(result, "correction_density") == "triggered"


@pytest.mark.parametrize("known,corrected,unknown", [(7, 3, 0), (8, 2, 0), (13, 3, 0), (8, 3, 6)])
def test_correction_requires_samples_rate_count_and_annotation_coverage(known, corrected, unknown):
    result = recommend(analysis(correction_events(known, corrected, unknown)))
    assert assessment(result, "correction_density") != "triggered"


def test_lexical_correction_candidates_never_become_confirmed_recommendation():
    es = correction_events()
    for e in es:
        e["attrs"].pop("interaction", None)
        e["text"] = "不对，你理解错了，请重新处理。"
    data = analysis(es)
    assert data["overview"]["counts"]["correction_signals"] >= 3
    assert assessment(recommend(data), "correction_density") == "insufficient_evidence"


def test_future_annotations_cannot_trigger_historical_recommendation():
    es = correction_events()
    for e in es:
        if "interaction" in e["attrs"]:
            e["attrs"]["interaction"]["available_at"] = 1000
    result = recommend(analysis(es, scope=Scope(until_ts=500)))
    assert assessment(result, "correction_density") == "insufficient_evidence"


def test_repeated_requirements_need_explicit_object_and_requirement_identity():
    es = [event(f"req-{i}", i, interaction=annotation(requirements=[
        {"object_uid": "csv-export", "requirement_uid": "utf-8" if i < 3 else "stable-columns"}]))
        for i in range(4)]
    assert assessment(recommend(analysis(es)), "repeated_requirements") == "triggered"
    for e in es:
        e["attrs"]["interaction"]["requirements"][0].pop("object_uid")
    assert assessment(recommend(analysis(es)), "repeated_requirements") == "insufficient_evidence"


def test_same_requirement_in_different_tasks_is_not_repeated_requirement():
    es = [event(f"req-{i}", i, task_uid=f"task-{i}", interaction=annotation(requirements=[
        {"object_uid": "csv-export", "requirement_uid": "utf-8"}])) for i in range(4)]
    assert assessment(recommend(analysis(es)), "repeated_requirements") != "triggered"


def test_two_confirmed_identical_retry_links_trigger():
    assert assessment(recommend(analysis(calls=retry_calls())), "identical_retries") == "triggered"


@pytest.mark.parametrize("field,value", [("task_uid", None), ("status_scope", "unknown"),
                                         ("argument_digest_kind", "unknown")])
def test_candidate_retry_links_do_not_trigger_even_when_legacy_count_is_positive(field, value):
    calls = retry_calls()
    for c in calls:
        c[field] = value
    result = recommend(analysis(calls=calls))
    assert assessment(result, "identical_retries") != "triggered"


def test_retries_of_different_arguments_do_not_trigger_identical_retry_rule():
    calls = retry_calls()
    for i, c in enumerate(calls):
        c["argument_digest"] = f"changed-{i}"
        if i:
            c["retry_of_call_uid"] = calls[i - 1]["call_uid"]
    assert assessment(recommend(analysis(calls=calls)), "identical_retries") != "triggered"


def test_calls_are_not_retries_across_tasks():
    calls = retry_calls()
    for i, c in enumerate(calls):
        c["task_uid"] = f"task-{i}"
    assert assessment(recommend(analysis(calls=calls)), "identical_retries") != "triggered"


def failure_calls():
    return [tool_call(f"tool-{i}", seq=10 + i * 2, status="failed" if i < 3 else "success",
                      failure_reason="invalid_arguments" if i < 3 else None) for i in range(10)]


def test_tool_failure_minimum_count_and_known_denominator_trigger():
    assert assessment(recommend(analysis(calls=failure_calls())), "tool_failures") == "triggered"


def test_unknown_tool_outcomes_reduce_coverage_without_becoming_successes():
    calls = failure_calls() + [tool_call(f"unknown-{i}", seq=40 + i * 2, status=None) for i in range(5)]
    assert assessment(recommend(analysis(calls=calls)), "tool_failures") != "triggered"


def test_rejected_requests_are_not_execution_failures():
    calls = failure_calls()
    for c in calls[:3]:
        c["status"] = "rejected"
    assert assessment(recommend(analysis(calls=calls)), "tool_failures") != "triggered"


def test_failures_from_unrelated_tools_are_not_pooled_to_hit_threshold():
    calls = failure_calls()
    for i, c in enumerate(calls):
        c["name_raw"] = f"tool-{i}"
    assert assessment(recommend(analysis(calls=calls)), "tool_failures") != "triggered"


def test_repeated_actual_validation_failures_trigger():
    calls = [tool_call(f"check-{i}", seq=10 + i * 2, status="failed", validation=validation()) for i in range(2)]
    assert assessment(recommend(analysis(calls=calls)), "validation_failures") == "triggered"


@pytest.mark.parametrize("change", ["task", "revision"])
def test_failures_in_different_tasks_or_artifact_revisions_are_not_one_failed_check(change):
    calls = [tool_call(f"check-{i}", seq=10 + i * 2, status="failed", validation=validation()) for i in range(2)]
    if change == "task":
        calls[1]["task_uid"] = "other-task"
    else:
        calls[1]["validation"]["scope"]["artifact_revision"] = "v2"
    assert assessment(recommend(analysis(calls=calls)), "validation_failures") != "triggered"


def test_test_command_mentions_are_not_failed_validation_runs():
    calls = [tool_call(f"mention-{i}", seq=10 + i * 2, status="failed",
                      command_head="echo pytest failed", command_complete=True) for i in range(2)]
    assert assessment(recommend(analysis(calls=calls)), "validation_failures") != "triggered"


def test_explicit_unmatched_acceptance_set_triggers_evidence_capture_recommendation():
    result = recommend(analysis([event("criteria", 0, acceptance=acceptance())]))
    assert assessment(result, "acceptance_evidence_gap") == "triggered"


@pytest.mark.parametrize("tool_status", ["partial", "unavailable"])
def test_incomplete_tool_dataset_cannot_prove_acceptance_evidence_gap(tool_status):
    data = analysis([event("criteria", 0, acceptance=acceptance())], tool_status=tool_status)
    assert assessment(recommend(data), "acceptance_evidence_gap") == "insufficient_evidence"


def test_no_criteria_is_unknown_acceptance_not_unperformed_tests():
    assert assessment(recommend(analysis()), "acceptance_evidence_gap") == "insufficient_evidence"


def test_partial_validation_success_does_not_fill_other_acceptance_criteria():
    data = analysis([event("criteria", 0, acceptance=acceptance())],
                    [tool_call("unit", validation=validation())])
    assert data["bottleneck_features"]["outcome"]["task_success"] is None
    # One unmatched criterion is below this rule's two-criterion threshold.
    assert assessment(recommend(data), "acceptance_evidence_gap") != "triggered"


def test_high_input_tokens_without_observed_context_pressure_do_not_trigger():
    models = [model_request(f"m-{i}", input_tokens=100_000) for i in range(5)]
    assert assessment(recommend(analysis(models=models)), "context_pressure") != "triggered"


def test_input_pressure_requires_complete_request_tokens_and_secondary_evidence():
    models = [model_request(f"m-{i}") for i in range(5)]
    assert assessment(recommend(analysis(calls=retry_calls(), models=models)), "context_pressure") == "triggered"
    models[0]["input_tokens"] = None
    assert assessment(recommend(analysis(calls=retry_calls(), models=models)), "context_pressure") != "triggered"


def test_cache_read_tokens_do_not_count_toward_uncached_input_budget():
    models = [model_request(f"m-{i}", input_tokens=10, cache_read_tokens=100_000) for i in range(5)]
    assert assessment(recommend(analysis(calls=retry_calls(), models=models)), "context_pressure") != "triggered"


def test_cumulative_snapshot_never_masquerades_as_five_model_requests():
    snapshot = event("usage", 0, "model.usage", measurement="cumulative", snapshot_key="s-total",
                     usage_scope="session_snapshot", coverage="self", input_tokens=200_000,
                     cache_read_tokens=0, cache_write_tokens=0, output_tokens=100)
    data = analysis([snapshot], calls=retry_calls(), models=None)
    assert assessment(recommend(data), "context_pressure") != "triggered"


def test_missing_models_and_calls_are_insufficient_evidence_not_zero_measurements():
    result = recommend(analysis(calls=None, models=None))
    for rule in ("tool_failures", "identical_retries", "context_pressure", "validation_failures"):
        assert assessment(result, rule) == "insufficient_evidence"


def test_input_and_policy_are_not_mutated_and_results_are_reproducible():
    data = analysis(correction_events(), calls=retry_calls(), models=[model_request(f"m-{i}") for i in range(5)])
    before = copy.deepcopy(data)
    first = recommend(data, target_agent="codex")
    assert data == before
    assert first == recommend(data, target_agent="codex")
    assert data == before


def test_unverified_external_catalog_cannot_supply_actionable_recommendations():
    unverified = [{
        "id": "unverified-debugger", "resource_id": "unverified-debugger", "name": "Unknown resource",
        "kind": "skill", "capabilities": ["identical_retries", "systematic_debugging"],
        "rule_ids": ["identical_retries"], "compatible_agents": ["generic", "codex", "claude_code"],
        "url": "https://github.com/example/unverified", "source_path": "SKILL.md",
        "verification": "unverified", "verified_sha": None,
        "source": {"url": "https://github.com/example/unverified", "verification": "unverified"},
    }]
    result = recommend_bottlenecks(analysis(calls=retry_calls()), catalog=unverified)
    assert assessment(result, "identical_retries") == "triggered"
    assert result["recommendations"] == []


@pytest.mark.parametrize("friction,capability", [("execution", "debugging"), ("verification", "verification")])
def test_confirmed_friction_routes_correction_to_matching_capability(friction, capability):
    es = correction_events()
    for e in es:
        a = e["attrs"].get("interaction")
        if a and "correction" in a["intents"]:
            a["friction_types"] = [friction]
    signals = [s for s in recommend(analysis(es))["signals"] if s["rule_id"] == "correction_density"]
    assert len(signals) == 1
    assert set(signals[0]["capabilities"]) == {capability}


@pytest.mark.parametrize("members", ["files", "test_ids"])
def test_validation_scope_member_order_does_not_split_the_same_failure_group(members):
    first = {**VALIDATION_SCOPE, "coverage": "subset", members: ["a", "b"]}
    second = {**VALIDATION_SCOPE, "coverage": "subset", members: ["b", "a"]}
    calls = [tool_call("check-a", seq=10, status="failed", validation=validation(scope=first)),
             tool_call("check-b", seq=12, status="failed", validation=validation(scope=second))]
    assert assessment(recommend(analysis(calls=calls)), "validation_failures") == "triggered"


def root_sessions():
    return [{"session_uid": sid, "root_uid": sid, "kind": "main", "project_id": "p", "started_at": 0}
            for sid in ("root-a", "root-b")]


def test_two_root_sessions_cannot_pool_small_intent_samples_into_a_recommendation():
    es = []
    for s in root_sessions():
        for e in correction_events(known=5, corrected=3):
            e["session_uid"] = s["session_uid"]
            # Native event identifiers are unique; correction targets retain their link.
            e["event_uid"] = s["session_uid"] + "-" + e["event_uid"]
            a = e["attrs"].get("interaction")
            if a and a.get("target_event_uid"):
                a["target_event_uid"] = s["session_uid"] + "-" + a["target_event_uid"]
            es.append(e)
    data = analysis(es, sessions=root_sessions())
    assert data["bottleneck_features"]["interaction"]["effective_samples"]["intent_messages"] == 10
    result = recommend(data)
    checks = [a for a in result["assessments"] if a["rule_id"] == "correction_density"]
    assert len(checks) == 2
    assert all(a["status"] == "insufficient_evidence" for a in checks)
    assert not any(s["rule_id"] == "correction_density" for s in result["signals"])


def test_two_root_sessions_cannot_pool_model_requests_into_context_pressure():
    calls, models = [], []
    for s in root_sessions():
        for c in retry_calls():
            c["session_uid"] = s["session_uid"]
            c["call_event_uid"] = s["session_uid"] + "-" + c["call_event_uid"]
            c["result_event_uid"] = s["session_uid"] + "-" + c["result_event_uid"]
            calls.append(c)
        models.extend(model_request(f"model-{i}", session_uid=s["session_uid"], input_tokens=10_000)
                      for i in range(3))
    data = analysis(calls=calls, models=models, sessions=root_sessions())
    assert data["bottleneck_features"]["cost_time"]["usage"]["request_count"] == 6
    result = recommend(data)
    checks = [a for a in result["assessments"] if a["rule_id"] == "context_pressure"]
    assert len(checks) == 2
    assert all(a["status"] == "insufficient_evidence" for a in checks)
    assert not any(s["rule_id"] == "context_pressure" for s in result["signals"])


def test_unavailable_events_and_null_workflow_sequences_do_not_crash():
    bundle = AnalysisInputBundle.from_dict({
        "input_contract": "analysis-input-v1", "sessions": root_sessions()[:1],
        "events": None, "tool_calls": None, "model_calls": None,
        "coverage": {name: {"status": "unavailable"} for name in ("events", "tool_calls", "model_calls")},
    })
    data = analyze_bundle(bundle, with_text=False)
    for root in data["sessions"]:
        # Some consumers preserve an unavailable workflow container with null fields.
        root["bottleneck_features"]["respond"]["workflow"] = {"sequences": None}
    result = recommend(data)
    assert result["signals"] == [] and result["recommendations"] == []
    assert all(a["status"] == "insufficient_evidence" for a in result["assessments"])
