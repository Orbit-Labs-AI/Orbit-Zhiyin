import copy

import pytest

from tandem_backend.analytics.outcome import analyze_outcome, extract_validation_runs

SCOPE = {"project_id": "p", "artifact_uid": "app", "artifact_revision": "v1", "coverage": "full"}


def validation(kind="test", **values):
    return {"kind": kind, "executed": True, "source": "synthetic-check-adapter", "available_at": 100,
            "scope": dict(SCOPE), "criterion_uids": [kind], **values}


def acceptance(**values):
    return {"state": "confirmed", "source": "synthetic-instruction-labels", "available_at": 50,
            "criteria_set_uid": "set-v1", "complete": True, "scope": dict(SCOPE),
            "criteria": [{"criterion_uid": "test", "kind": "test"}, {"criterion_uid": "build", "kind": "build"}], **values}


def test_passing_test_does_not_imply_unrun_build_or_whole_task(make_call, make_event):
    r = analyze_outcome([make_call(validation=validation())], [make_event(acceptance=acceptance())], {"s"})
    assert [v["acceptance_result"] for v in r["acceptance_results"]] == ["passed", "unknown"]
    assert r["effective_n"] == 1 and r["unknown_n"] == 1
    assert r["task_success"] is None


def test_all_explicit_criteria_pass_only_for_complete_set(make_call, make_event):
    calls = [make_call("test", validation=validation()), make_call("build", validation=validation("build"))]
    before = copy.deepcopy(calls)
    assert analyze_outcome(calls, [make_event(acceptance=acceptance())], {"s"})["task_success"] is True
    assert analyze_outcome(calls, [make_event(acceptance=acceptance(complete=False))], {"s"})["task_success"] is None
    assert analyze_outcome(calls, [], {"s"})["task_success"] is None
    assert calls == before


def test_wrapper_success_is_not_inner_test_success_without_scoped_report(make_call):
    c = make_call(status_scope="orchestration_only", is_wrapper=True, validation=validation())
    run = extract_validation_runs([c])["validation_runs"][0]
    assert run["validation_result"] == "unknown"
    assert run["missing_reason"] == "outer_or_unknown_status_scope"
    c["validation_result"] = {"status": "passed", "source": "test-report", "report_uid": "report-1",
                               "call_uid": "c", "scope": dict(SCOPE), "available_at": 200}
    assert extract_validation_runs([c])["validation_runs"][0]["validation_result"] == "passed"
    c["validation_result"]["call_uid"] = "unrelated"
    assert extract_validation_runs([c])["validation_runs"][0]["validation_result"] == "unknown"


def test_old_revision_and_subset_do_not_satisfy_new_full_acceptance(make_call, make_event):
    for scope in [{**SCOPE, "artifact_revision": "v0"}, {**SCOPE, "coverage": "subset", "files": ["one.py"]}]:
        r = analyze_outcome([make_call(validation=validation(scope=scope))],
                            [make_event(acceptance=acceptance())], {"s"})
        assert r["acceptance_results"][0]["acceptance_result"] == "unknown"
        assert r["acceptance_results"][0]["missing_reason"] == "scope_or_artifact_revision_mismatch"


def test_matching_ids_without_object_revision_still_unknown(make_call, make_event):
    r = analyze_outcome([make_call(validation=validation(scope={"project_id": "p"}))],
                        [make_event(acceptance=acceptance(scope={"project_id": "p"}))], {"s"})
    assert r["task_success"] is None


@pytest.mark.parametrize("command", ["echo pytest passed", "pytest --collect-only", "pytest --version",
                                     "pytest --fixtures", "cargo test --no-run", "pytest && echo ok",
                                     "go test -list=.", "go test --list=.", "go test -list .",
                                     "go test -args -test.list=."])
def test_mentions_dry_runs_and_compound_commands_never_become_passed_tests(make_call, command):
    r = extract_validation_runs([make_call(command_head=command, command_complete=True)])
    assert r["validation_runs"] == []


def test_only_complete_direct_command_can_be_identified_without_labels(make_call):
    c = make_call(command_head="python -m pytest tests/unit")
    assert extract_validation_runs([c])["validation_runs"] == []
    c["command_complete"] = True
    r = extract_validation_runs([c])["validation_runs"][0]
    assert r["kind"] == "test" and r["validation_result"] == "passed"
    assert r["validation_scope"] is None
    assert r["criterion_uids"] == []


def test_later_result_and_later_annotation_are_not_visible_at_snapshot(make_call, make_event):
    c = make_call(validation=validation(), ended_at=300)
    r = analyze_outcome([c], [make_event(acceptance=acceptance())], {"s"}, until_ts=300)
    assert r["validation_runs"][0]["validation_result"] == "unknown"
    assert r["validation_runs"][0]["validation_evidence"]["result_event_uid"] is None
    r = analyze_outcome([c], [make_event(acceptance=acceptance(available_at=400))], {"s"}, until_ts=300)
    assert r["acceptance_results"] == []
    assert r["unusable_criteria_events"] == ["u"]


def test_latest_result_not_latest_call_determines_current_check_state(make_call, make_event):
    calls = [make_call("started-first", seq=1, ended_at=500, status="failed", validation=validation()),
             make_call("started-second", seq=2, ended_at=200, status="success", validation=validation())]
    r = analyze_outcome(calls, [make_event(acceptance=acceptance())], {"s"})
    assert r["acceptance_results"][0]["acceptance_result"] == "failed"
    assert r["task_success"] is False
    for c in calls:
        c["ended_at"] = None
    assert analyze_outcome(calls, [make_event(acceptance=acceptance())], {"s"})["acceptance_results"][0]["acceptance_result"] == "unknown"


def test_child_validation_requires_explicit_root_relation(make_call, make_event):
    child = make_call(session_uid="child", validation=validation())
    es = [make_event(acceptance=acceptance())]
    assert analyze_outcome([child], es, {"s"})["acceptance_results"][0]["acceptance_result"] == "unknown"
    child["root_session_uid"] = "s"
    assert analyze_outcome([child], es, {"s"})["acceptance_results"][0]["acceptance_result"] == "passed"


def test_rejected_validation_request_is_not_executed_check(make_call):
    r = extract_validation_runs([make_call(status="rejected", validation=validation())])
    assert r["validation_runs"] == []
    assert len(r["validation_candidates"]) == 1


def test_acceptance_becomes_visible_only_after_both_criteria_and_result(make_call, make_event):
    c = make_call(validation=validation(), ended_at=200)
    es = [make_event(acceptance=acceptance(available_at=500))]
    r = analyze_outcome([c], es, {"s"})
    assert r["acceptance_results"][0]["available_at"] == 500
    assert analyze_outcome([c], es, {"s"}, until_ts=400)["acceptance_results"] == []


@pytest.mark.parametrize("other_session, expected", [("child", "unknown"), ("s", "passed")])
def test_unclocked_result_sequences_only_order_one_session(make_call, make_event, other_session, expected):
    calls = [make_call("root-failed", ended_at=None, result_seq=2, status="failed", validation=validation()),
             make_call("other-passed", session_uid=other_session, root_session_uid="s",
                       ended_at=None, result_seq=50, status="success", validation=validation())]
    criterion = acceptance(criteria=[{"criterion_uid": "test", "kind": "test"}])
    result = analyze_outcome(calls, [make_event(acceptance=criterion)], {"s"})
    assert result["acceptance_results"][0]["acceptance_result"] == expected
    assert result["task_success"] is (True if expected == "passed" else None)
