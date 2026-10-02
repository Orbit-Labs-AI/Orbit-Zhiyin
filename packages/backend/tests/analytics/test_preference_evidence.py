"""Preference consumes Instruction facts without changing task execution policy."""

import copy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.instruction import extract_instruction_constraints
from tandem_backend.analytics.preference import (
    build_preference_evidence,
    explicit_to_preference_evidence,
    extract_explicit_preferences,
    instruction_to_preference_evidence,
    resolve_effective_preferences,
    summarize_preference_evidence,
)
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.api import create_app


def observations(events):
    return extract_instruction_constraints(events, main_ids={"s"})


def test_only_four_control_dimensions_enter_historical_evidence(fixtures):
    s, e, _ = fixtures
    events = [e("直接执行。请运行 pytest。请用 Markdown 表格。只修改 a.py。不要推送。"
                "验收标准：全部测试通过。使用 bash", task_id="task")]
    rows = observations(events)
    evidence = instruction_to_preference_evidence(rows, [s()])
    assert {(r["dimension"], r["value"]) for r in evidence} == {
        ("autonomy", "autonomous"), ("execution_style", "execute_first"),
        ("verification", "requested"), ("format", "markdown"), ("format", "table"),
    }
    assert {r["source_id"] for r in evidence} <= {c["constraint_uid"] for c in rows[0]["constraints"]}
    assert all(r["source_type"] == "task_instruction" and r["confidence"] == 0.6 for r in evidence)
    assert all(r["task_id"] == "task" and r["project_id"] == "p" for r in evidence)


def test_adapter_uses_structured_values_even_without_parseable_text(fixtures):
    s, e, _ = fixtures
    rows = observations([e("请用 JSON", task_id="task")])
    rows[0]["constraints"][0]["text"] = "unparseable audit text"
    assert instruction_to_preference_evidence(rows, [s()])[0]["value"] == "json"
    del rows[0]["constraints"][0]["format_values"]
    item = instruction_to_preference_evidence(rows, [s()])[0]
    assert item["value"] is None and item["status"] == "pending"
    assert "format_value_unavailable" in item["missing_reasons"]


def test_explicit_extractor_does_not_parse_task_requirements(fixtures, monkeypatch):
    s, e, _ = fixtures
    parser = Mock(side_effect=AssertionError("ordinary task text reached preference vocabulary"))
    monkeypatch.setattr("tandem_backend.analytics.preference.features.preference_values", parser)
    result = extract_explicit_preferences([e("这次直接执行，请用表格，并运行 pytest")], [s()])
    assert result["records"] == result["candidates"] == result["task_instructions"] == []
    parser.assert_not_called()


def test_explicit_authority_keeps_scope_and_history_separate_from_instruction(fixtures):
    s, e, _ = fixtures
    events = [e("以后这个项目用中文", "a", 1, ts=10),
              e("这个项目改用英文", "b", 2, ts=20),
              e("撤销这个项目的英文偏好", "c", 3, ts=30),
              e("直接执行", "d", 4, ts=40, task_id="task")]
    explicit = extract_explicit_preferences(events, [s()])
    rows = observations(events)
    before = copy.deepcopy((explicit, rows))
    evidence = build_preference_evidence(explicit, rows, [s()])
    assert (explicit, rows) == before
    strong = [r for r in evidence if r["source_type"] == "explicit_preference"]
    assert len(strong) == 3 and all(r["confidence"] == 1.0 for r in strong)
    assert {r["operation"] for r in strong} == {"assert", "revise", "revoke"}
    assert all(r["scope"]["kind"] == "project" for r in strong)
    assert any(r["history"] for r in strong)
    assert resolve_effective_preferences(explicit["records"], {"project_id": "p"}, 40)["applicable"] == []
    assert resolve_effective_preferences(explicit["records"], {"project_id": "p"}, 25)["applicable"][0]["value"] == "en"


def test_task_support_is_deduplicated_and_missing_request_is_not_opposite(fixtures):
    s, e, _ = fixtures
    rows = observations([e("无需确认", f"e{i}", i, task_id="one") for i in range(4)]
                        + [e("hello", "no-request", 5, task_id="two")])
    evidence = instruction_to_preference_evidence(rows, [s()])
    summary = summarize_preference_evidence(evidence * 2, rows, [s()])
    assert summary["evidence_count"] == 4 and summary["observed_tasks"] == 2
    values = summary["dimensions"][0]["historical_values"]
    assert [(v["value"], v["support_tasks"], v["support_sessions"], v["task_rate"]) for v in values] == [
        ("autonomous", 1, 1, 0.5)]


def test_explicit_adapter_keeps_known_task_scope_and_future_observation_time(fixtures):
    s, e, _ = fixtures
    explicit = extract_explicit_preferences([e("这次我喜欢表格", "a", 1, ts=10),
                                             e("明天以后所有项目用中文", "b", 2, ts=20)],
                                            [s()], {"a": "known-task"})
    evidence = explicit_to_preference_evidence(explicit, [s()])
    task = next(r for r in evidence if r["scope"]["kind"] == "task")
    assert task["task_id"] == "known-task" and task["task_identity_quality"] == "task_family"
    future = next(r for r in evidence if r["scope"]["kind"] == "global")
    assert future["observed_at"] == 20 and future["status"] == "pending"
    assert "scheduled_effective_time_not_parsed" in future["missing_reasons"]


def test_verification_absence_and_prohibition_never_become_negative_preference(fixtures):
    s, e, _ = fixtures
    rows = observations([e("请运行测试", "a", 1, task_id="one"),
                         e("不要测试", "b", 2, task_id="two"),
                         e("hello", "c", 3, task_id="three")])
    evidence = instruction_to_preference_evidence(rows, [s()])
    summary = summarize_preference_evidence(evidence, rows, [s()])
    value = summary["dimensions"][0]["historical_values"][0]
    assert value["value"] == "requested" and value["task_rate"] == pytest.approx(1 / 3)
    assert len(evidence) == 1


def test_pending_conditions_missing_tasks_and_truncation_are_not_historical_votes(fixtures):
    s, e, _ = fixtures
    rows = observations([e("先给方案", "unscoped", 1),
                         e("如果测试通过，请用 JSON", "conditional", 2, task_id="t"),
                         {**e("直接执行", "cut", 3, task_id="t"), "text_truncated": True},
                         e("请用 JSON 或 Markdown", "alternative", 4, task_id="t")])
    evidence = instruction_to_preference_evidence(rows, [s()])
    assert len(evidence) == 6 and all(r["status"] == "pending" for r in evidence)
    assert all(not r["historical_values"] for r in summarize_preference_evidence(evidence, rows, [s()])["dimensions"])
    assert {reason for r in evidence for reason in r["missing_reasons"]} >= {
        "task_unknown", "condition_not_evaluated", "text_truncated", "alternative_values_not_resolved"}


def test_task_family_assignment_is_used_without_mutating_instruction(fixtures):
    s, e, _ = fixtures
    rows = observations([e("先给方案", task_id="legacy")])
    old = copy.deepcopy(rows)
    item = instruction_to_preference_evidence(rows, [s()], {"e": "canonical-task"})[0]
    assert item["task_id"] == "canonical-task" and item["task_identity_quality"] == "task_family"
    assert rows == old


def test_equal_local_task_names_in_different_sessions_do_not_merge(fixtures):
    s, e, _ = fixtures
    rows = extract_instruction_constraints([e("先给方案", "a", sid="a", task_id="t"),
                                           e("先给方案", "b", sid="b", task_id="t")], main_ids={"a", "b"})
    sessions = [s("a"), s("b")]
    evidence = instruction_to_preference_evidence(rows, sessions)
    assert summarize_preference_evidence(evidence, rows, sessions)["observed_tasks"] == 2
    mapping = {"a": "confirmed-shared", "b": "confirmed-shared"}
    evidence = instruction_to_preference_evidence(rows, sessions, mapping)
    summary = summarize_preference_evidence(evidence, rows, sessions, mapping)
    assert summary["observed_tasks"] == 1
    assert summary["dimensions"][0]["historical_values"][0]["support_sessions"] == 2


def test_opposing_requests_in_one_task_remain_a_conflict_not_two_votes(fixtures):
    s, e, _ = fixtures
    rows = observations([e("先询问我", "a", 1, task_id="t"), e("无需确认", "b", 2, task_id="t")])
    evidence = instruction_to_preference_evidence(rows, [s()])
    dimension = summarize_preference_evidence(evidence, rows, [s()])["dimensions"][0]
    assert dimension["historical_values"] == [] and len(dimension["conflicting_tasks"]) == 1


def test_same_fact_from_both_paths_keeps_links_without_a_second_historical_vote(fixtures):
    s, e, _ = fixtures
    explicit = extract_explicit_preferences([e("以后这个项目用 JSON")], [s()])
    rows = observations([e("请用 JSON", task_id="t")])
    evidence = build_preference_evidence(explicit, rows, [s()])
    strong = next(r for r in evidence if r["source_type"] == "explicit_preference")
    weak = next(r for r in evidence if r["source_type"] == "task_instruction")
    assert weak["corroborates_evidence_id"] == strong["evidence_id"]
    assert weak["confidence"] < strong["confidence"]
    assert not summarize_preference_evidence(evidence, rows, [s()])["dimensions"][0]["historical_values"]


def test_origin_replay_and_main_boundaries_are_preserved(fixtures):
    s, e, _ = fixtures
    events = [e("直接执行", "unknown", origin="unknown"), e("直接执行", "robot", origin="automation"),
              e("直接执行", "replay", replayed_from="old"), e("直接执行", "child", sid="child")]
    rows = observations(events)
    assert build_preference_evidence(extract_explicit_preferences(events, [s()]), rows, [s()]) == []


def test_unavailable_is_not_an_empty_observed_sample(fixtures):
    s, _, _ = fixtures
    missing = extract_explicit_preferences(None, [s()])
    assert build_preference_evidence(missing, None, [s()]) is None
    assert summarize_preference_evidence(None)["evidence_count"] is None
    assert summarize_preference_evidence([])["evidence_count"] == 0


def test_service_extracts_instruction_once_and_does_not_apply_historical_evidence(fixtures, monkeypatch):
    s, e, b = fixtures
    events = [e("请修复代码", "a", 1, ts=10), e("直接执行", "b", 2, ts=20),
              e("无需确认", "c", 3, ts=30), e("以后所有项目用中文", "d", 4, ts=40)]
    spy = Mock(wraps=extract_instruction_constraints)
    monkeypatch.setattr("tandem_backend.analytics.service.extract_instruction_constraints", spy)
    result = analyze_bundle(b(events), with_text=False)
    spy.assert_called_once()
    prefs = result["preferences"]
    assert len(prefs["records"]) == 1 and len(prefs["evidence"]) == 4
    assert all(r["task_id"] for r in prefs["evidence"])
    assert set(result["sessions"][0]["preference_evidence_ids"]) == {r["evidence_id"] for r in prefs["evidence"]}
    active = resolve_effective_preferences(prefs["records"])["applicable"]
    assert [r["value"] for r in active] == ["zh"]
    before = analyze_bundle(b(events), Scope(until_ts=30), with_text=False)["preferences"]
    assert before["records"] == [] and len(before["evidence"]) == 2
    missing = analyze_bundle(b(None), with_text=False)["preferences"]
    assert missing["evidence"] is None and missing["evidence_summary"]["status"] == "unavailable"


def test_api_exposes_both_sources_with_existing_scope_filters(fixtures, monkeypatch, tmp_path):
    s, e, b = fixtures
    bundle = b([e("请修复代码", "a", 1, ts=10), e("先给方案", "b", 2, ts=20),
                e("以后所有项目用中文", "c", 3, ts=30)])
    monkeypatch.setattr("tandem_backend.analytics.service.analyze_store",
                        lambda store, scope, with_text=True: analyze_bundle(bundle, scope, with_text))
    with TestClient(create_app(tmp_path / "test.sqlite")) as client:
        response = client.get("/v1/analytics/preferences")
        assert response.status_code == 200
        prefs = response.json()["preferences"]
        assert {e["source_type"] for e in prefs["evidence"]} == {"explicit_preference", "task_instruction"}
        assert prefs["effective"]["applicable"][0]["value"] == "zh"
        filtered = client.get("/v1/analytics/preferences?until_ts=30").json()["preferences"]
        assert {e["source_type"] for e in filtered["evidence"]} == {"task_instruction"}
        excluded = client.get("/v1/analytics/preferences?excluded_session_uids=s").json()["preferences"]
        assert excluded["evidence"] == []


@pytest.mark.parametrize("with_text", [False, True])
def test_service_reuses_optional_session_cluster_context(fixtures, monkeypatch, with_text):
    _, e, b = fixtures
    projection = Mock(return_value={"coordinates": [{"entity_id": "s", "cluster_id": 7}]})
    monkeypatch.setattr("tandem_backend.analytics.service.representation", projection)
    result = analyze_bundle(b([e("先给方案")]), with_text=with_text)
    item = result["preferences"]["evidence"][0]
    assert item["cluster_id"] == result["sessions"][0]["cluster_id"] == (7 if with_text else None)
    assert projection.call_count == int(with_text)
