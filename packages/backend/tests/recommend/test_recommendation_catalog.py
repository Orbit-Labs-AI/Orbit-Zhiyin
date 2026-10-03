"""Offline catalogue integrity and deterministic resource selection."""

import copy

import pytest

from orbit_backend.analytics.recommendations import RecommendationPolicy, recommend_bottlenecks
from orbit_backend.analytics.recommendations.catalog import (
    builtin_resources,
    load_catalog,
    vetted_catalog,
)
from orbit_backend.analytics.recommendations.ranking import rank_resources


def signal(uid="s", rule="identical_retries", capabilities=None):
    return {"signal_id": uid, "rule_id": rule, "capabilities": capabilities or ["retry_control"],
            "confidence": .8, "severity": .7, "recurrence": .5, "reason": "synthetic repeated failure",
            "metrics": [{"path": "respond.retry_links", "value": 3}],
            "evidence": [{"kind": "call", "session_uid": "s", "id": "synthetic-call"}],
            "scope": {"root_session_uid": "s"}, "hypothesis": "test diagnostic checkpoint",
            "evaluation_metrics": ["respond.retry_links", "outcome.acceptance_results"]}


def test_bundled_catalogue_is_vetted_and_covers_all_resource_kinds():
    accepted, rejected = vetted_catalog(load_catalog())
    assert not rejected
    assert len(accepted) == 12
    assert {r["kind"] for r in accepted} == {"skill", "agent", "hook", "prompt"}
    assert all(r["effect_status"] == "unmeasured" for r in accepted)


@pytest.mark.parametrize("key,value", [
    ("verified_sha", "main"), ("content_sha256", ""), ("source_path", "../secret"),
    ("verification", "repository_only"), ("license", "NOASSERTION"),
    ("source_status", "revoked"), ("url", "https://example.com/arbitrary"),
])
def test_unverified_external_catalogue_is_excluded(key, value):
    resource = next(r for r in load_catalog() if r["origin"] == "github")
    resource[key] = value
    accepted, rejected = vetted_catalog([resource])
    assert not accepted
    assert rejected[0]["resource_id"] == resource["id"]


def test_modified_builtin_is_not_mistaken_for_reviewed_template():
    resource = builtin_resources()[0]
    resource["preview"] = "arbitrary replacement"
    assert not vetted_catalog([resource])[0]


def test_duplicate_ids_and_unknown_capabilities_excluded():
    resource = builtin_resources()[0]
    accepted, rejected = vetted_catalog([resource, resource])
    assert len(accepted) == 1
    assert rejected[0]["reason"] == "duplicate_resource_id"
    resource["capabilities"] = ["popular"]
    assert not vetted_catalog([resource])[0]


def test_priority_formula_is_visible_and_resources_have_actionable_trials():
    prompt = next(r for r in builtin_resources() if "retry_control" in r["capabilities"])
    card = rank_resources([signal()], [prompt], "codex", 6, None)[0]
    assert card["priority_score"] == round(100 * .8 * (.6 * .7 + .25 * .5 + .15), 2)
    assert card["effect_status"] == "unmeasured"
    assert card["evaluation_plan"]["observed_effect"] is None
    assert card["setup_steps"] and card["preview"] and card["trial"] and card["evidence"]


def test_matching_is_stable_deduplicated_and_limits_one_problem():
    signals = [signal(), signal("s2"), signal("s3", "acceptance_evidence_gap", ["verification"])]
    resources = load_catalog()
    original = copy.deepcopy((signals, resources))
    cards = rank_resources(signals, resources, "generic", 20, None)
    assert cards == rank_resources(list(reversed(signals)), list(reversed(resources)), "generic", 20, None)
    assert len({c["resource_id"] for c in cards}) == len(cards)
    assert sum(c["rule_id"] == "identical_retries" for c in cards) <= 2
    assert len(cards) >= 2
    cards[0]["setup_steps"].append("mutate result")
    assert (signals, resources) == original


def test_kind_filter_and_hook_adaptation_are_explicit():
    cards = rank_resources([signal()], load_catalog(), "codex", 6, "hook")
    assert cards and all(c["kind"] == "hook" for c in cards)
    assert all(c["compatibility"] == "adaptation_required" for c in cards)
    assert all(c["recommendation_status"] == "adaptation_required" for c in cards)
    assert all("/blob/" in c["source"]["source_url"] for c in cards)
    assert all(c["score_breakdown"]["compatibility_factor"] < 1 for c in cards)


def test_unsupported_agent_cannot_receive_resource():
    resource = next(r for r in load_catalog() if r["kind"] == "hook")
    resource["compatibility"]["codex"] = "unsupported"
    assert rank_resources([signal()], [resource], "codex", 6, None) == []


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 21}, {"limit": True}, {"target_agent": "unknown"}, {"kind": "plugin"}])
def test_public_input_filters_reject_invalid_values(kwargs):
    with pytest.raises(ValueError):
        recommend_bottlenecks({}, **kwargs)


@pytest.mark.parametrize("kwargs", [{"intent_min_samples": 0}, {"input_min_share": 1.1}, {"retry_min_count": True}])
def test_policy_must_have_positive_samples_and_valid_ratios(kwargs):
    with pytest.raises(ValueError):
        RecommendationPolicy(**kwargs)


def test_unknown_schema_is_not_silently_interpreted():
    with pytest.raises(ValueError, match="schema"):
        recommend_bottlenecks({"bottleneck_features": {"schema_version": "future-schema"}})
