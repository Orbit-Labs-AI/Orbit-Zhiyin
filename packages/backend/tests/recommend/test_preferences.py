"""Counterfactual ranking and scope/history boundaries using fictional inputs."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_recommend_pipeline import correction_bundle, ready_item

from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.recommend.contracts import RecommendationContext
from tandem_backend.recommend.service import recommend


def analysis_with(*statements, roots=None):
    bundle = correction_bundle(roots)
    messages = [event for event in bundle.events if event["kind"] == "message.user"]
    for event, statement in zip(messages, statements, strict=False):
        event["text"] = statement
    return analyze_bundle(bundle, with_text=False)


def choice_catalog(dimension="detail", values=("brief", "detailed")):
    return [ready_item(value, preference_support={dimension: [value]}) for value in values]


def top(result):
    return result["recommendations"][0]["resource_id"]


@pytest.mark.parametrize("scope,dimension,values", [
    ("global", "detail", ("brief", "detailed")),
    ("project", "tool", ("pytest", "playwright")),
    ("task", "capability", ("debugging", "verification")),
])
def test_only_changing_each_preference_axis_switches_top_skill(scope, dimension, values):
    analysis = analysis_with()
    target = {"global": None, "project": "fictional-project", "task": analysis["tasks"]["records"][0]["task_id"]}[scope]
    results = [recommend(analysis, catalog=choice_catalog(dimension, values), context={"preferences": [
        {"scope": scope, "target_id": target, "dimension": dimension, "value": value}]}) for value in values]
    assert [top(r) for r in results] == list(values)
    assert results[0]["signals"] == results[1]["signals"]
    for r in results:
        card = r["recommendations"][0]
        assert card["candidate_features"]["preference_match"] == 1
        assert "preferences" in card["recall"]["ranks"]
        assert card["preference_explanation"]["matches"][0]["outcome"] == "matched"


def test_extracted_history_is_used_without_request_override():
    brief = analysis_with("以后所有项目我喜欢简短回答")
    detailed = analysis_with("以后所有项目我喜欢详细回答")
    assert top(recommend(brief, catalog=choice_catalog())) == "brief"
    assert top(recommend(detailed, catalog=choice_catalog())) == "detailed"
    state = recommend(brief, catalog=choice_catalog())["states"][0]["preference_state"]
    assert state["used_for_ranking"] and state["effective"][0]["evidence"][0]["event_uid"]


def test_project_over_global_and_current_task_instruction_over_project():
    project = analysis_with("以后所有项目我喜欢详细回答", "以后这个项目我喜欢简短回答")
    task = analysis_with("以后所有项目我喜欢详细回答", "以后这个项目我喜欢简短回答", "这次详细回答")
    assert top(recommend(project, catalog=choice_catalog())) == "brief"
    assert top(recommend(task, catalog=choice_catalog())) == "detailed"
    state = recommend(task, catalog=choice_catalog())["states"][0]["preference_state"]
    assert state["effective"][0]["origin"] == "task_instruction"


def test_revision_and_revocation_are_respected():
    revised = analysis_with("以后这个项目我喜欢简短回答", "这个项目改为详细回答")
    revoked = analysis_with("以后这个项目我喜欢简短回答", "撤销这个项目简短回答的偏好")
    assert top(recommend(revised, catalog=choice_catalog())) == "detailed"
    assert recommend(revoked, catalog=choice_catalog())["states"][0]["preference_state"]["effective"] == []


def test_conflict_does_not_fall_back_or_silently_select_one_value():
    analysis = analysis_with("以后所有项目我喜欢简短回答", "以后这个项目我喜欢简短回答", "以后这个项目我喜欢详细回答")
    result = recommend(analysis, catalog=choice_catalog())
    state = result["states"][0]["preference_state"]
    assert state["effective"] == [] and state["conflicts"][0]["dimension"] == "detail"
    corrected = recommend(analysis, catalog=choice_catalog(), context={"preferences": [
        {"scope": "project", "target_id": "fictional-project", "dimension": "detail", "value": "detailed"}]})
    assert top(corrected) == "detailed"
    assert corrected["states"][0]["preference_state"]["conflicts"] == []


def test_task_scope_does_not_leak_between_roots():
    analysis = analysis_with(roots=[("fictional-a", 8, 3), ("fictional-b", 8, 3)])
    task = next(t for t in analysis["tasks"]["records"] if "fictional-a" in t["related_session_ids"])
    result = recommend(analysis, catalog=choice_catalog(), context={"preferences": [
        {"scope": "task", "target_id": task["task_id"], "dimension": "detail", "value": "detailed"}]})
    states = {r["root_session_uid"]: r["preference_state"] for r in result["states"]}
    assert states["fictional-a"]["used_for_ranking"]
    assert not states["fictional-b"]["used_for_ranking"]


def test_unknown_project_and_ambiguous_task_preferences_remain_unresolved():
    analysis = analysis_with("帮我实现接口", "新任务：帮我测试数据库")
    assert len(analysis["tasks"]["records"]) > 1
    result = recommend(analysis, catalog=choice_catalog(), context={"preferences": [
        {"scope": "task", "target_id": analysis["tasks"]["records"][0]["task_id"], "dimension": "detail", "value": "brief"},
        {"scope": "project", "target_id": "elsewhere", "dimension": "detail", "value": "brief"}]})
    state = result["states"][0]["preference_state"]
    assert not state["effective"] and len(state["unresolved"]) == 2


def test_repetition_and_catalogue_order_do_not_change_scores():
    analysis = analysis_with()
    pref = {"dimension": "detail", "value": "detailed"}
    once = recommend(analysis, catalog=choice_catalog(), context={"preferences": [pref]})
    repeated = recommend(analysis, catalog=list(reversed(choice_catalog())), context={"preferences": [pref, pref]})
    assert once["recommendations"] == repeated["recommendations"]


def test_preferred_candidate_survives_small_per_route_limit():
    items = [ready_item(f"a-{i}", preference_support={"detail": ["brief"]}) for i in range(100)]
    items.append(ready_item("z-preferred", preference_support={"detail": ["detailed"]}))
    result = recommend(analysis_with(), catalog=items, context={"preferences": [
        {"dimension": "detail", "value": "detailed"}]}, ranking_policy={"per_route": 1})
    assert top(result) == "z-preferred"


def test_future_unknown_and_quoted_preferences_are_not_applied():
    for statement in ("明天所有项目我喜欢详细回答", "我喜欢详细回答", "文档说以后所有项目我喜欢详细回答"):
        result = recommend(analysis_with(statement), catalog=choice_catalog())
        assert not result["states"][0]["preference_state"]["effective"]


def test_preferences_never_override_missing_evidence_or_hard_filter():
    context = {"agent": "codex", "preferences": [{"dimension": "detail", "value": "detailed"}]}
    no_evidence = analysis_with(roots=[("quiet", 8, 0)])
    assert recommend(no_evidence, catalog=choice_catalog(), context=context)["recommendations"] == []
    items = choice_catalog()
    items[1]["compatibility"] = {"agents": {"codex": "unsupported"}}
    result = recommend(analysis_with(), catalog=items, context=context)
    assert top(result) == "brief"
    assert result["excluded_resources"][0]["resource_id"] == "detailed"


def test_avoid_and_missing_metadata_have_explicit_explanations_without_input_mutation():
    analysis, items = analysis_with(), choice_catalog()
    items.append(ready_item("unknown"))
    before = deepcopy((analysis, items))
    result = recommend(analysis, catalog=items, context={"preferences": [
        {"dimension": "detail", "value": "detailed", "polarity": "avoid"}]})
    assert top(result) == "brief"
    unknown = next(c for c in result["recommendations"] if c["resource_id"] == "unknown")
    assert unknown["preference_explanation"]["matches"][0]["outcome"] == "unknown"
    assert (analysis, items) == before


@pytest.mark.parametrize("pref", [
    {"scope": "project", "dimension": "tool", "value": "pytest"},
    {"target_id": "unexpected", "dimension": "tool", "value": "pytest"},
    {"dimension": "detail", "value": " "}, {"dimension": "persona", "value": "expert"},
])
def test_invalid_preference_requests_are_rejected(pref):
    with pytest.raises(ValidationError):
        RecommendationContext(preferences=[pref])
