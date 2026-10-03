"""Offline catalogue integrity and public input validation."""

import pytest

from tandem_backend.analytics.recommendations import RecommendationPolicy, recommend_bottlenecks
from tandem_backend.analytics.recommendations.catalog import (
    builtin_resources,
    load_catalog,
    rejection_reason,
)


def test_bundled_catalogue_is_vetted_and_covers_all_resource_kinds():
    catalogue = load_catalog()
    assert [rejection_reason(r) for r in catalogue] == [None] * 12
    assert len({r["id"] for r in catalogue}) == 12
    assert {r["kind"] for r in catalogue} == {"skill", "agent", "hook", "prompt"}
    assert all(r["effect_status"] == "unmeasured" for r in catalogue)


@pytest.mark.parametrize("key,value", [
    ("verified_sha", "main"), ("content_sha256", ""), ("source_path", "../secret"),
    ("verification", "repository_only"), ("license", "NOASSERTION"),
    ("source_status", "revoked"), ("url", "https://example.com/arbitrary"),
])
def test_unverified_external_catalogue_is_excluded(key, value):
    resource = next(r for r in load_catalog() if r["origin"] == "github")
    resource[key] = value
    assert rejection_reason(resource) is not None


def test_modified_builtin_is_not_mistaken_for_reviewed_template():
    resource = builtin_resources()[0]
    resource["preview"] = "arbitrary replacement"
    assert rejection_reason(resource) == "unrecognized_project_template"


def test_unknown_capabilities_excluded():
    resource = builtin_resources()[0]
    resource["capabilities"] = ["popular"]
    assert rejection_reason(resource) == "invalid_resource_contract"


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
