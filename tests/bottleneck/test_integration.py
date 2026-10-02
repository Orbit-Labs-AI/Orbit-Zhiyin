import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.api import create_app
from tandem_backend.cli import main
from tandem_backend.models import Event, ParsedSession, Session
from tandem_backend.store import Store


def fixture():
    return json.loads((Path(__file__).parents[1] / "fixtures" / "bottleneck-features-v1.json").read_text())


def analyze(data, scope=None):
    return analyze_bundle(AnalysisInputBundle.from_dict(data), scope, with_text=False)


def test_four_families_have_consistent_scope_in_overall_session_and_project():
    data = fixture()
    before = copy.deepcopy(data)
    r = analyze(data)
    for f in (r["bottleneck_features"], r["sessions"][0]["bottleneck_features"], r["projects"][0]["bottleneck_features"]):
        assert f["included_session_uids"] == ["child", "root"]
        assert f["interaction"]["confirmed_correction_count"] == 1
        assert f["interaction"]["confirmed_correction_rate"] == .5
        assert f["respond"]["tools"]["totals"]["call_count"] == 2
        assert f["cost_time"]["usage"]["total_tokens"] == 350
        assert f["cost_time"]["durations"]["execution_duration_sum_ms"] == 20000
        assert f["cost_time"]["durations"]["reliable_interval_union_ms"] == 15000
        assert f["outcome"]["task_success"] is True
    assert data == before
    assert r == analyze(data)
    json.dumps(r, allow_nan=False)


def test_excluding_children_changes_all_families_and_cannot_keep_their_passed_checks():
    r = analyze(fixture(), Scope(include_children=False))
    f = r["bottleneck_features"]
    assert f["included_session_uids"] == ["root"]
    assert f["respond"]["tools"]["totals"]["call_count"] == 1
    assert f["cost_time"]["usage"]["total_tokens"] == 200
    assert f["outcome"]["task_success"] is None
    assert f["outcome"]["acceptance_results"][1]["acceptance_result"] == "unknown"


def test_future_return_and_report_cannot_leak_into_any_family():
    data = fixture()
    base = data["sessions"][0]["started_at"]
    future_report = {"status": "failed", "source": "synthetic", "available_at": base + 20000,
                     "call_uid": "test", "report_uid": "future-private-marker", "scope": data["events"][0]["attrs"]["acceptance"]["scope"]}
    data["tool_calls"][0]["validation_result"] = future_report
    r = analyze(data, Scope(until_ts=base + 12000))
    assert "future-private-marker" not in json.dumps(r)
    f = r["bottleneck_features"]
    results = {v["kind"]: v["validation_result"] for v in f["outcome"]["validation_runs"]}
    assert results == {"test": "passed", "build": "unknown"}
    assert f["outcome"]["task_success"] is None
    assert f["cost_time"]["durations"]["reliable_interval_union_ms"] == 10000
    child = next(c for c in f["respond"]["tool_sequence"] if c["session_uid"] == "child")
    assert child["result_event_uid"] is None and child["raw_status"] is None


def test_duplicate_calls_are_deduplicated_for_legacy_and_new_outputs():
    data = fixture()
    data["tool_calls"].append(copy.deepcopy(data["tool_calls"][0]))
    r = analyze(data)
    assert r["tools"]["totals"]["call_count"] == 2
    assert r["sessions"][0]["features"]["tool_call_count"] == 2
    assert r["bottleneck_features"]["respond"]["tools"]["totals"]["call_count"] == 2
    assert r["selection"]["tool_call_normalization"]["duplicate_call_rows"] == 1


def test_unavailable_events_and_calls_do_not_become_zero_observations():
    data = fixture()
    data["events"] = data["tool_calls"] = data["model_calls"] = None
    for k in ("events", "tool_calls", "model_calls"):
        data["coverage"][k]["status"] = "unavailable"
    f = analyze(data)["bottleneck_features"]
    assert f["interaction"]["confirmed_correction_count"] is None
    assert f["respond"]["tool_sequence"] is None
    assert f["cost_time"]["usage"]["total_tokens"] is None
    assert f["outcome"]["validation_runs"] is None
    assert f["outcome"]["task_success"] is None


def test_api_and_cli_share_family_output_using_only_temporary_synthetic_store(tmp_path, capsys):
    store = Store(tmp_path / "synthetic.sqlite")
    s = Session("s", "p", "fictional", "/fictional", "fixture", analytics_metadata={"kind": "main", "root_uid": "s"})
    e = Event("u", "s", 0, "user_message", "2026-01-01T00:00:00Z", text="新增功能", details={"origin": "human"})
    store.save(ParsedSession(s, [e]), "fixture", json.dumps({"parser": 26, "before": None, "exclude": []}))
    with TestClient(create_app(store.path)) as client:
        response = client.get("/v1/analytics/bottleneck")
        assert response.status_code == 200
        api = response.json()
        assert api["bottleneck_features"]["interaction"]["effective_samples"]["human_messages"] == 1
        assert client.get("/v1/analytics/bottleneck?display_timezone=invalid").status_code == 422
    output = tmp_path / "synthetic-analytics.json"
    main(["--db", str(store.path), "analytics", "--no-text", "--output", str(output)])
    cli = json.loads(output.read_text())
    assert cli["bottleneck_features"] == api["bottleneck_features"]
    assert cli["analysis_digest"] == api["analysis_digest"]
    assert "主会话" in capsys.readouterr().out


def test_future_l2_annotations_are_removed_before_fallback_pairing():
    data = fixture()
    base = data["sessions"][0]["started_at"]
    data["tool_calls"] = None
    data["coverage"]["tool_calls"]["status"] = "unavailable"
    call = next(e for e in data["events"] if e["event_uid"] == "test-call")
    call["attrs"]["validation"].update(available_at=base + 20000, check_name="future-secret-marker")
    r = analyze(data, Scope(until_ts=base + 12000))
    assert "future-secret-marker" not in json.dumps(r)


def test_unknown_session_kind_does_not_imply_zero_interactions():
    data = fixture()
    data["sessions"][0]["kind"] = "unknown"
    f = analyze(data)["bottleneck_features"]["interaction"]
    assert f["confirmed_correction_count"] is None
    assert f["unknown_counts"]["session_kind_messages"] == 2


def test_declared_wrapper_cannot_become_direct_validation_when_flag_omitted():
    data = fixture()
    data["tool_calls"][0]["name_raw"] = "functions.exec"
    f = analyze(data)["bottleneck_features"]["outcome"]
    assert next(v for v in f["validation_runs"] if v["kind"] == "test")["validation_result"] == "unknown"
    assert f["task_success"] is None


def test_instruction_observation_does_not_invent_objective_acceptance():
    data = fixture()
    for event in data["events"]:
        event.get("attrs", {}).pop("acceptance", None)
    data["events"][0]["text"] = "验收标准：全部测试和构建通过"
    result = analyze(data)
    instruction = result["instruction"]["summary"]["features"]["acceptance_criteria"]
    assert instruction["effective_n"] == 1
    outcome = result["bottleneck_features"]["outcome"]
    assert outcome["validation_result_counts"] == {"passed": 2}
    assert outcome["acceptance_results"] == []
    assert outcome["task_success"] is None


@pytest.mark.parametrize("available_offset", [None, 12000, 20000])
@pytest.mark.parametrize("l2_only", [False, True])
def test_validation_reports_respect_cutoff_in_l2_and_l3(available_offset, l2_only):
    data = fixture()
    base = data["sessions"][0]["started_at"]
    report = {"report_uid": "not-yet-visible-report", "source": "synthetic",
              "available_at": base + available_offset if available_offset is not None else None}
    call = data["tool_calls"][0]
    call["validation_report"] = dict(report)
    start = next(e for e in data["events"] if e["event_uid"] == call["call_event_uid"])
    result = next(e for e in data["events"] if e["event_uid"] == call["result_event_uid"])
    start["attrs"]["call_id"] = result["attrs"]["call_id"] = "synthetic-native-call"
    result["attrs"]["validation_report"] = dict(report)
    if l2_only:
        data["tool_calls"] = None
        data["coverage"]["tool_calls"]["status"] = "unavailable"
    before = copy.deepcopy(data)
    assert "not-yet-visible-report" in json.dumps(analyze(data))
    bounded = analyze(data, Scope(until_ts=base + 12000))
    assert "not-yet-visible-report" not in json.dumps(bounded)
    assert data == before


def test_excluded_tool_dataset_cannot_be_rebuilt_from_retained_events():
    data = fixture()
    for call in data["tool_calls"]:
        start = next(e for e in data["events"] if e["event_uid"] == call["call_event_uid"])
        result = next(e for e in data["events"] if e["event_uid"] == call["result_event_uid"])
        start["attrs"].update(call_id=call["call_uid"], name_raw=call["name_raw"],
                              started_at=call["started_at"], interval_reliable=True)
        result["attrs"].update(call_id=call["call_uid"], ended_at=call["ended_at"], interval_reliable=True)
    data["tool_calls"] = None
    data["coverage"]["tool_calls"]["status"] = "unavailable"
    fallback = analyze(data)["bottleneck_features"]
    assert fallback["respond"]["tools"]["totals"]["call_count"] == 2
    assert fallback["outcome"]["task_success"] is True
    data["coverage"]["tool_calls"]["status"] = "excluded"
    result = analyze(data)
    for family in (result["bottleneck_features"], result["sessions"][0]["bottleneck_features"],
                   result["projects"][0]["bottleneck_features"]):
        assert family["respond"]["status"] == "excluded"
        assert family["respond"]["tool_sequence"] is None
        assert family["respond"]["tools"]["status"] == "excluded"
        assert family["respond"]["tools"]["totals"] is None
        assert family["cost_time"]["durations"]["execution_duration_sum_ms"] is None
        assert family["outcome"]["status"] == "excluded"
        assert family["outcome"]["validation_runs"] is None
        assert family["outcome"]["task_success"] is None


def test_bottleneck_coexists_with_semantic_and_subjective_families():
    data = fixture()
    data["events"][0]["text"] = "请修复代码。以后这个项目用中文。验收标准：全部测试通过。"
    base = data["sessions"][0]["started_at"]
    data["events"].extend([
        {"event_uid": "final-delivery", "session_uid": "root", "seq": 7,
         "ts": base + 18000, "kind": "message.assistant", "actor": "assistant",
         "text": "已交付一个版本。", "attrs": {"origin": "agent", "phase": "final", "task_id": "synthetic-task"}},
        {"event_uid": "accepted-feedback", "session_uid": "root", "seq": 8,
         "ts": base + 19000, "kind": "message.user", "actor": "human", "text": "这个可以了",
         "attrs": {"origin": "human", "task_id": "synthetic-task"}},
    ])
    data["tool_calls"][0]["status"] = "failed"
    result = analyze(data)
    assert result["tasks"]["records"]
    assert any(p["value"] == "zh" for p in result["preferences"]["records"])
    assert result["instruction"]["summary"]["features"]["acceptance_criteria"]["effective_n"] == 1
    assert {"preference_statement", "task_goal_history", "user_acceptance", "interaction.confirmed_correction_rate"} <= result["feature_dictionary"].keys()
    for row in (result["overview"], result["sessions"][0], result["projects"][0]):
        assert row["subjective_outcomes"]["counts"]["accepted_feedback_count"] == 1
    for row in (result, result["sessions"][0], result["projects"][0]):
        assert row["bottleneck_features"]["outcome"]["task_success"] is False
