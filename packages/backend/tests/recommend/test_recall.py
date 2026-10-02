"""Synthetic retrieval tests; no histories, network, or model downloads."""

import math

import pytest

from tandem_backend.recommend.contracts import RecommendationItem, RecommendationState
from tandem_backend.recommend.recall import context, dense, effect, rules, sparse
from tandem_backend.recommend.recall.fusion import fuse


def item(uid, **values):
    return RecommendationItem.model_validate({
        "identity": {"id": uid, "name": uid}, "family": "skills", **values,
    })


def state(**values):
    return RecommendationState(root_session_uid="synthetic-root", **values)


def test_rules_do_not_turn_context_or_keywords_into_a_bottleneck():
    candidate = item("pytest-hook", capability={"tags": ["verification"]},
                     trigger={"rule_ids": ["validation_failures"]})
    actual = state(problem_text="validation_failures verification", context_state={"tools": ["pytest"]})
    assert rules.recall(actual, [candidate]) == []
    assert actual.signals == []


def test_rules_prioritize_exact_diagnosis_then_intervention_capability():
    actual = state(signals=[{"rule_id": "validation_failures", "capabilities": ["verification"]}])
    candidates = [item("unrelated", capability={"tags": ["scope_alignment"]}),
                  item("broad", capability={"tags": ["verification", "debugging"]}),
                  item("specific", capability={"tags": ["verification"]}),
                  item("exact", trigger={"rule_ids": ["validation_failures"]})]
    assert rules.recall(actual, candidates) == [("exact", 1.), ("specific", .8), ("broad", .4)]


def test_rules_ignore_malformed_optional_signal_fields():
    actual = state(signals=[{"rule_id": [], "capabilities": "verification"},
                            {"capabilities": [None, 3, "verification"]}])
    assert rules.recall(actual, [item("valid", capability={"tags": ["verification"]})]) == [("valid", .8)]


def test_rules_duplicate_resources_do_not_multiply_results():
    candidate = item("one", trigger={"rule_ids": ["retry"]})
    assert rules.recall(state(signals=[{"rule_id": "retry"}]), [candidate, candidate]) == [("one", 1.)]


def test_sparse_matches_exact_technical_terms_case_insensitively():
    candidates = [item("python", target_task={"text": "Python code"}),
                  item("tests", capability={"text": "PyTest validation"}),
                  item("similar", capability={"text": "pytested validation"})]
    assert [uid for uid, _ in sparse.recall(state(task_text="pytest"), candidates)] == ["tests"]


def test_sparse_uses_all_three_curated_text_blocks_and_tags():
    candidates = [item("target", target_task={"tags": ["playwright"]}),
                  item("trigger", trigger={"text": "playwright"}),
                  item("capability", capability={"text": "playwright"}),
                  item("raw", source={"source_path": "playwright.md"},
                       family_features={"readme": "playwright"})]
    assert {uid for uid, _ in sparse.recall(state(desired_effect_text="playwright"), candidates)} == {
        "target", "trigger", "capability",
    }


def test_sparse_retrieves_chinese_phrase_inside_a_sentence():
    candidates = [item("tests", capability={"text": "自动执行测试并记录结果"}),
                  item("cost", capability={"text": "降低成本并记录结果"})]
    assert [uid for uid, _ in sparse.recall(state(problem_text="测试"), candidates)] == ["tests"]


def test_tokenizer_preserves_technical_names_and_avoids_single_character_noise():
    tokens = sparse.tokenize("C++ C# pytest-xdist React.js GitHub 自动测试")
    assert {"c++", "c#", "pytest-xdist", "pytest", "xdist", "react.js", "react", "github"} <= set(tokens)
    assert {"自动", "动测", "测试"} <= set(tokens)
    assert "测" not in tokens


def test_sparse_repeated_query_terms_and_duplicate_ids_do_not_amplify_rank():
    candidate = item("one", capability={"text": "pytest"})
    once = sparse.recall(state(task_text="pytest"), [candidate])
    duplicate = sparse.recall(state(task_text="pytest pytest", problem_text="pytest"), [candidate, candidate])
    assert duplicate == once


def test_bm25_uses_document_length_normalization():
    concise = item("short", capability={"text": "pytest"})
    verbose = item("long", capability={"text": "pytest " + "unrelated " * 100})
    results = sparse.recall(state(task_text="pytest"), [verbose, concise])
    assert results[0][0] == "short"
    assert results[0][1] > results[1][1] > 0


@pytest.mark.parametrize(("k1", "b"), [(0, .75), (math.inf, .75), (True, .75),
                                      (1.2, -1), (1.2, math.nan), (1.2, True)])
def test_bm25_rejects_invalid_parameters(k1, b):
    with pytest.raises(ValueError):
        sparse.recall(state(), [], k1=k1, b=b)


def test_effect_dot_product_is_relevance_not_probability():
    actual = state(bottleneck_vector={"retries": .5, "validation": 1.})
    candidates = [item("both", expected_effect={"targets": {"retries": .5, "validation": 1.}}),
                  item("unrelated", expected_effect={"targets": {"context": 1.}}),
                  item("retry", expected_effect={"targets": {"retries": 1.}})]
    assert effect.recall(actual, candidates) == [("both", 1.25), ("retry", .5)]
    assert effect.recall(state(), candidates) == []


def test_context_finds_environment_match_without_creating_diagnosis():
    actual = state(context_state={"agent": "codex", "languages": ["Python"], "tools": ["pytest"]})
    matching = item("match", compatibility={"agents": {"codex": "native"}, "languages": ["python"]},
                    requirements={"tools": ["pytest"]})
    unrelated = item("other", compatibility={"agents": {"codex": "unsupported"}, "languages": ["rust"]})
    assert context.recall(actual, [unrelated, matching]) == [("match", 1.)]
    assert actual.signals == []
    assert actual.bottleneck_vector == {}


def test_context_unknown_environment_and_generic_support_are_not_positive_matches():
    candidate = item("broad", compatibility={"agents": {"generic": "manual"},
                                             "languages": ["python"], "os": ["linux"]})
    assert context.recall(state(), [candidate]) == []


def test_context_matches_declared_model_and_repository_only():
    actual = state(context_state={"model": "synthetic-model", "repository": "org/repo"})
    assert context.recall(actual, [item("match", family_features={
        "model": "synthetic-model", "repository": "org/repo",
    })]) == [("match", 1.)]


def test_rrf_deduplicates_before_assigning_one_based_rank():
    result = fuse({"rules": [("a", 100.), ("a", 99.), ("b", 1.)]})
    assert [row.item_id for row in result] == ["a", "b"]
    assert result[0].fusion_score == pytest.approx(1 / 61)
    assert result[1].route_ranks == {"rules": 2}
    assert result[1].fusion_score == pytest.approx(1 / 62)


def test_rrf_uses_rank_not_incompatible_raw_score_scales():
    result = fuse({"sparse": [("a", 10000.), ("b", 100.)],
                   "rules": [("b", 1.), ("a", .5)]})
    assert result[0].fusion_score == pytest.approx(result[1].fusion_score)
    assert [row.item_id for row in result] == ["a", "b"]
    assert result[0].route_scores == {"rules": .5, "sparse": 10000.}


def test_rrf_route_order_does_not_affect_output():
    routes = {"sparse": [("b", 2.), ("a", 1.)], "effect": [("a", .5)], "rules": [("c", 1.)]}
    assert fuse(routes) == fuse(dict(reversed(list(routes.items()))))


def test_rrf_accepts_weights_and_disables_zero_weight_routes():
    result = fuse({"sparse": [("a", 10.)], "rules": [("b", 1.)]}, weights={"sparse": 0., "rules": 2.})
    assert [row.item_id for row in result] == ["b"]
    assert result[0].fusion_score == pytest.approx(2 / 61)


@pytest.mark.parametrize("bad_score", [math.nan, math.inf, -math.inf, -1., True])
def test_rrf_rejects_nonfinite_and_invalid_scores_even_in_duplicate_rows(bad_score):
    with pytest.raises(ValueError):
        fuse({"rules": [("a", 1.), ("a", bad_score)]})


@pytest.mark.parametrize("weights", [{"rules": math.nan}, {"rules": -1.}, {"rules": True}, {"missing": 1.}])
def test_rrf_rejects_invalid_weights(weights):
    with pytest.raises(ValueError):
        fuse({"rules": [("a", 1.)]}, weights=weights)


def test_rrf_empty_and_zero_scored_inputs_have_no_candidates():
    assert fuse({}) == []
    assert fuse({"rules": [("a", 0.)]}) == []


@pytest.mark.parametrize("route", [rules.recall, sparse.recall, effect.recall, context.recall])
def test_all_offline_routes_accept_empty_catalog_and_validate_limit(route):
    assert route(state(), []) == []
    with pytest.raises(ValueError):
        route(state(), [], limit=-1)


def test_dense_is_explicitly_disabled_with_three_distinct_query_fields():
    assert dense.status()["enabled"] is False
    assert dense.status()["status"] == "disabled"
    assert dense.queries(state(task_text="task", problem_text="problem", desired_effect_text="effect")) == {
        "task": "task", "trigger": "problem", "capability": "effect",
    }
