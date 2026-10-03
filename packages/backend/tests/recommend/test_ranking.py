"""Synthetic resources/states only; ranking never consults personal histories."""

import math
from copy import deepcopy

import pytest

from tandem_backend.recommend.contracts import (
    Candidate,
    RankingPolicy,
    RecommendationContext,
    RecommendationItem,
    RecommendationState,
)
from tandem_backend.recommend.features import candidate_features
from tandem_backend.recommend.ranking import filter_item, score_candidate, select_diverse


def resource(uid="test-resource", **changes):
    value = {
        "identity": {"id": uid, "name": "Synthetic diagnostic skill", "version": "1"},
        "family": "skills",
        "target_task": {"text": "Python debugging", "tags": ["python"]},
        "trigger": {"rule_ids": ["identical_retries"]},
        "capability": {"tags": ["debugging"]},
        "expected_effect": {"targets": {"identical_retries": 1.}},
        "compatibility": {"agents": {"codex": "manual", "generic": "manual"}},
        "friction": {"setup_cost": .1, "runtime_cost": .1},
        "evidence_quality": {"status": "reviewed", "score": .8, "reviewed_by": "synthetic-curator"},
        "source": {"origin": "github", "status": "verified", "url": "https://github.com/example/repo",
                   "verified_sha": "a" * 40, "content_sha256": "b" * 64,
                   "source_path": "skills/debug/SKILL.md", "license": "MIT"},
        "action": {"setup_steps": ["Read the skill and try one controlled task."],
                   "preview": "Reproduce before changing code.", "trial": "Compare repeated tool failures."},
    }
    value.update(changes)
    return RecommendationItem.model_validate(value)


def signal(rule="identical_retries", **changes):
    value = {"signal_id": "signal-" + rule, "rule_id": rule, "severity": .8, "confidence": .9,
             "capabilities": ["debugging"],
             "evidence": [{"kind": "tool_call", "session_uid": "synthetic-session", "id": "call-1"}]}
    value.update(changes)
    return value


def state(**changes):
    value = {"root_session_uid": "synthetic-session", "context_state": {"agent": "codex"},
             "task_text": "Python debugging", "signals": [signal()],
             "bottleneck_vector": {"identical_retries": .72}}
    value.update(changes)
    return RecommendationState.model_validate(value)


def features(item=None, current=None, **kwargs):
    item = item or resource()
    current = current or state()
    candidate = Candidate(item_id=item.identity.id, route_scores={"rules": 1., "sparse": 2.},
                          route_ranks={"rules": 1, "sparse": 2}, fusion_score=1 / 61 + 1 / 62)
    return candidate_features(current, item, candidate, filter_item(item, current.context_state), **kwargs)


def test_reviewed_actionable_resource_passes_without_inventing_prerequisites():
    decision = filter_item(resource(), RecommendationContext(agent="codex"))
    assert decision.eligible and decision.compatibility == "manual"
    assert decision.pending_requirements == [] and decision.reasons == []


@pytest.mark.parametrize("requirement,inventory", [("tools", "tools"), ("software", "software"),
                                                   ("resources", "installed_resources")])
def test_unknown_inventory_is_pending_and_explicit_empty_inventory_rejects(requirement, inventory):
    item = resource(requirements={requirement: ["synthetic-dependency"]})
    unknown = filter_item(item, RecommendationContext(agent="codex"))
    assert unknown.eligible and unknown.pending_requirements == [f"{requirement}:synthetic-dependency"]
    missing = filter_item(item, RecommendationContext(agent="codex", **{inventory: []}))
    assert not missing.eligible
    assert f"missing_{requirement}:synthetic-dependency" in missing.reasons
    supplied = filter_item(item, RecommendationContext(agent="codex", **{inventory: ["Synthetic-Dependency"]}))
    assert supplied.eligible and not supplied.pending_requirements


def test_permission_allowlist_denial_and_unknown_are_distinct():
    item = resource(risk_permission={"required_permissions": ["network:write"]})
    pending = filter_item(item, RecommendationContext(agent="codex"))
    assert pending.eligible and pending.pending_requirements == ["permission:network:write"]
    assert not filter_item(item, RecommendationContext(agent="codex", permissions=[])).eligible
    assert filter_item(item, RecommendationContext(agent="codex", permissions=["network:write"])).eligible
    denied = filter_item(item, RecommendationContext(agent="codex", permissions=["network:write"],
                                                    denied_permissions=["network:write"]))
    assert not denied.eligible and "permission_denied:network:write" in denied.reasons
    denied_unknown = filter_item(item, RecommendationContext(agent="codex", denied_permissions=["network:write"]))
    assert not denied_unknown.eligible and not denied_unknown.pending_requirements


def test_agent_unknown_does_not_inherit_generic_native_and_unsupported_is_rejected():
    item = resource(compatibility={"agents": {"generic": "native", "claude_code": "unsupported"}})
    unknown = filter_item(item, RecommendationContext(agent="codex"))
    assert unknown.eligible and unknown.compatibility == "unknown"
    assert unknown.pending_requirements == ["agent:codex"]
    assert not filter_item(item, RecommendationContext(agent="claude_code")).eligible


def test_os_unknown_incompatible_and_alias():
    item = resource(compatibility={"agents": {"codex": "manual"}, "os": ["linux"]})
    unknown = filter_item(item, RecommendationContext(agent="codex"))
    assert unknown.eligible and unknown.pending_requirements == ["os"]
    assert not filter_item(item, RecommendationContext(agent="codex", os="windows")).eligible
    assert filter_item(item, RecommendationContext(agent="codex", os="wsl")).eligible


@pytest.mark.parametrize("kind,name", [("languages", "python"), ("frameworks", "pytest")])
def test_language_framework_complete_context_vs_unknown(kind, name):
    item = resource(compatibility={"agents": {"codex": "manual"}, kind: [name]})
    pending = filter_item(item, RecommendationContext(agent="codex"))
    assert pending.eligible and kind in pending.pending_requirements
    assert not filter_item(item, RecommendationContext(agent="codex", **{kind: []})).eligible
    assert not filter_item(item, RecommendationContext(agent="codex", **{kind: ["unrelated"]})).eligible
    assert filter_item(item, RecommendationContext(agent="codex", **{kind: [name.upper()]})).eligible


@pytest.mark.parametrize("installed", [["test-resource"], ["test-resource@1"]])
def test_installed_identity_is_excluded(installed):
    decision = filter_item(resource(), RecommendationContext(agent="codex", installed_resources=installed))
    assert not decision.eligible and "already_installed:test-resource" in decision.reasons


@pytest.mark.parametrize("status", ["draft", "stale", "deprecated", "unavailable", "revoked"])
def test_non_verified_source_is_excluded(status):
    source = resource().source.model_dump()
    source["status"] = status
    assert not filter_item(resource(source=source), RecommendationContext(agent="codex")).eligible


@pytest.mark.parametrize("field,value", [
    ("content_sha256", None), ("content_sha256", "a" * 63), ("content_sha256", "g" * 64),
    ("verified_sha", None), ("verified_sha", "main"), ("blob_sha", "broken"),
    ("url", "http://github.com/example/repo"), ("url", "https://github.com/example/repo/tree/main"),
    ("url", "https://github.com.evil.test/example/repo"), ("url", "https://[invalid"),
    ("source_path", "../SKILL.md"), ("source_path", "/SKILL.md"), ("source_path", "folder\\SKILL.md"),
    ("source_path", "folder//SKILL.md"), ("source_path", ""),
    ("license", None), ("license", "unknown"), ("license", "NOASSERTION"),
])
def test_source_hash_revision_repository_path_and_license_are_required(field, value):
    source = resource().source.model_dump()
    source[field] = value
    assert not filter_item(resource(source=source), RecommendationContext(agent="codex")).eligible


def test_local_reviewed_template_does_not_require_a_fictitious_github_revision():
    item = resource(source={"origin": "local", "status": "verified", "content_sha256": "c" * 64})
    assert filter_item(item, RecommendationContext(agent="codex")).eligible


@pytest.mark.parametrize("change", [{"preview": " "}, {"trial": ""}, {"setup_steps": []},
                                    {"setup_steps": ["Valid step", " "]}])
def test_non_actionable_resource_is_excluded(change):
    action = resource().action.model_dump()
    action.update(change)
    assert not filter_item(resource(action=action), RecommendationContext(agent="codex")).eligible


def test_unreviewed_source_claims_cannot_reach_ranking():
    item = resource(evidence_quality={"status": "draft", "score": 1.})
    assert not filter_item(item, RecommendationContext(agent="codex")).eligible


@pytest.mark.parametrize("reviewer", [None, "", " "])
def test_review_requires_attribution(reviewer):
    item = resource(evidence_quality={"status": "reviewed", "score": .8, "reviewed_by": reviewer})
    decision = filter_item(item, RecommendationContext(agent="codex"))
    assert not decision.eligible and "missing_evidence_reviewer" in decision.reasons


def test_features_explain_grounding_and_normalize_fusion_with_enabled_route_bound():
    result = features(fusion_upper_bound=4 / 61)
    assert result["grounded"] and result["grounded_signal_ids"] == ["signal-identical_retries"]
    assert result["primary_signal_id"] == "signal-identical_retries"
    assert result["trigger_match"] == result["effect_match"] == 1.
    assert result["confidence"] == .9 and "semantic_match" not in result
    assert result["fusion_match"] == pytest.approx((1 / 61 + 1 / 62) / (4 / 61))
    assert features()["fusion_match"] == 0.


def test_effect_match_uses_shared_diagnosis_keys_and_relevance_weights():
    current = state(signals=[signal(), signal("tool_failures")],
                    bottleneck_vector={"identical_retries": .8, "tool_failures": .4})
    item = resource(trigger={}, capability={}, expected_effect={"targets": {"identical_retries": .5}})
    result = features(item, current)
    assert result["effect_match"] == pytest.approx(1 / 3)
    assert result["trigger_match"] == 0. and result["grounded"]
    assert score_candidate(result, RankingPolicy())[0] > 0.


@pytest.mark.parametrize("changes", [
    {"signals": []},
    {"signals": [signal(evidence=[])]},
    {"signals": [signal(evidence=[{"id": "unknown"}])]},
    {"signals": [signal("unrelated", capabilities=["unrelated"])]},
])
def test_keywords_and_unsupported_vectors_never_ground_a_recommendation(changes):
    result = features(current=state(**changes))
    assert result["task_match"] > 0.
    assert score_candidate(result, RankingPolicy())[0] == 0.


def test_persona_alone_does_not_change_matching():
    before = features(current=state(signals=[], bottleneck_vector={}))
    after = features(current=state(signals=[], bottleneck_vector={}, preference_state={"persona": "Verifier"}))
    assert before == after and score_candidate(after, RankingPolicy())[0] == 0.


def test_sparse_problem_match_is_not_mislabeled_as_a_task_match():
    result = features(current=state(task_text="unrelated spreadsheet task"))
    assert result["task_match"] == 0.


def test_shared_capability_can_trigger_an_evidence_backed_intervention():
    item = resource(trigger={}, expected_effect={"targets": {"unrelated": 1.}})
    result = features(item)
    assert result["trigger_match"] == 1. and result["effect_match"] == 0.
    assert score_candidate(result, RankingPolicy())[0] > 0.


def test_higher_risk_friction_and_lower_confidence_reduce_priority():
    initial = features(fusion_upper_bound=4 / 61)
    baseline = score_candidate(initial, RankingPolicy())[0]
    assert baseline > 0.
    for change in ({"risk": 1.}, {"friction": 1.}, {"confidence": .2}, {"compatibility_factor": .35}):
        score, _ = score_candidate({**initial, **change}, RankingPolicy())
        assert 0. <= score < baseline


def test_unknown_agent_is_explicit_and_scores_below_known_compatibility():
    known = features()
    unknown = features(resource(compatibility={}))
    assert unknown["pending_requirements"] == ["agent:codex"]
    assert unknown["compatibility_factor"] == .35
    assert score_candidate(unknown, RankingPolicy())[0] < score_candidate(known, RankingPolicy())[0]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), None, True, "0.9"])
def test_non_numeric_or_nonfinite_confidence_abstains(invalid):
    result = features(current=state(signals=[signal(confidence=invalid)]))
    score, breakdown = score_candidate(result, RankingPolicy())
    assert score == 0. and math.isfinite(breakdown["base_score"])


def test_scoring_stays_finite_with_arbitrary_input_and_zero_policy_weights():
    inputs = {**features(), "task_match": float("nan"), "risk": float("inf"), "fusion_match": -1.}
    score, _ = score_candidate(inputs, RankingPolicy())
    assert math.isfinite(score) and 0. <= score <= 1.
    policy = RankingPolicy(task_weight=0., trigger_weight=0., effect_weight=0., context_weight=0.,
                           evidence_weight=0., fusion_weight=0.)
    assert score_candidate(inputs, policy)[0] == 0.


def test_filter_feature_and_score_calls_do_not_mutate_inputs():
    item, current = resource(), state()
    candidate = Candidate(item_id=item.identity.id, route_scores={"sparse": 2.}, fusion_score=.02)
    before = deepcopy((item, current, candidate))
    decision = filter_item(item, current.context_state)
    result = candidate_features(current, item, candidate, decision, fusion_upper_bound=.1)
    result_before = deepcopy(result)
    score_candidate(result, RankingPolicy())
    assert (item, current, candidate) == before and result == result_before


def ranked_row(uid, score, *, family="skills", capability="debugging", rule="identical_retries"):
    item = resource(uid, family=family, capability={"tags": [capability]},
                    expected_effect={"targets": {rule: 1.}})
    return {"item": item, "candidate": Candidate(item_id=uid), "features": {}, "score": score,
            "filter": filter_item(item, RecommendationContext(agent="codex")), "signal": signal(rule)}


def test_mmr_prefers_distinct_intervention_over_near_duplicate_and_preserves_scores():
    rows = [ranked_row("debug-a", .9), ranked_row("debug-b", .89),
            ranked_row("verify", .85, family="hooks", capability="verification", rule="acceptance_evidence_gap")]
    before = deepcopy(rows)
    selected = select_diverse(rows, 2, RankingPolicy())
    assert [row["item"].identity.id for row in selected] == ["debug-a", "verify"]
    assert [row["score"] for row in selected] == [.9, .85]
    assert all("mmr_score" in row and "diversity_penalty" in row for row in selected)
    assert rows == before
    selected[0]["features"]["changed"] = True
    assert rows == before


def test_mmr_enforces_identity_deduplication_and_two_per_rule():
    rows = [ranked_row("one", .9), ranked_row("one", .95), ranked_row("two", .8),
            ranked_row("three", .79), ranked_row("four", .7, rule="tool_failures")]
    selected = select_diverse(rows, 10, RankingPolicy())
    assert len(selected) == 3
    assert [row["item"].identity.id for row in selected].count("one") == 1
    assert next(row["score"] for row in selected if row["item"].identity.id == "one") == .95
    assert sum(row["signal"]["rule_id"] == "identical_retries" for row in selected) == 2


def test_mmr_ties_are_deterministic_and_bad_scores_cannot_win():
    rows = [ranked_row("b", .5), ranked_row("a", .5), ranked_row("nan", float("nan")),
            ranked_row("infinity", float("inf")), ranked_row("zero", 0.)]
    assert [row["item"].identity.id for row in select_diverse(rows, 5, RankingPolicy())] == ["a", "b"]
    assert select_diverse(rows, 0, RankingPolicy()) == []
    assert select_diverse([], 5, RankingPolicy()) == []
