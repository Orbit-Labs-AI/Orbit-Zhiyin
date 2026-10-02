"""Resource authoring contracts must not lose operational requirements."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tandem_backend.recommend.contracts import FAMILIES, RankingPolicy, RecommendationItem
from tandem_backend.recommend.families import prepare_item
from tandem_backend.recommend.schema import catalog_schema


def item(family, **values):
    return RecommendationItem(identity={"id": "synthetic", "name": "Synthetic"}, family=family, family_features=values)


@pytest.mark.parametrize("family,values,field,expected", [
    ("skills", {"required_tools": ["pytest"]}, "tools", ["pytest"]),
    ("workflows", {"tools": ["git"]}, "tools", ["git"]),
    ("plugins", {"dependencies": ["example"]}, "resources", ["example"]),
])
def test_family_dependencies_cannot_bypass_common_filters(family, values, field, expected):
    original = item(family, **values)
    prepared, _ = prepare_item(original)
    assert getattr(prepared.requirements, field) == expected
    assert getattr(original.requirements, field) == []


@pytest.mark.parametrize("family", ["plugins", "mcp"])
def test_family_permissions_are_promoted_to_shared_requirements(family):
    prepared, _ = prepare_item(item(family, permissions=["write_repository"]))
    assert prepared.risk_permission.required_permissions == ["write_repository"]


def test_hook_and_model_configuration_missing_identity_stays_pending():
    _, missing = prepare_item(item("hooks"))
    assert missing == ["family_features.event", "family_features.condition", "family_features.action"]
    _, missing = prepare_item(item("model_configs", model="synthetic-model"))
    assert missing == ["family_features.reasoning_effort", "family_features.agent_harness"]


@pytest.mark.parametrize("family,values", [
    ("hooks", {"runtime_overhead_ms": True}), ("skills", {"required_tools": "pytest"}),
    ("mcp", {"permissions": [1]}), ("model_configs", {"context_window": -1}),
    ("workflows", {"imaginary_flag": True}),
])
def test_family_fields_are_strict(family, values):
    with pytest.raises(ValidationError):
        prepare_item(item(family, **values))


def test_model_benchmark_must_retain_exact_configuration_and_scale():
    observation = {"benchmark": "fictional", "benchmark_version": "v1", "score": 60., "scale": "0..100",
                   "date": "2026-01-01", "source": "synthetic", "model": "model-a", "reasoning_effort": "low", "harness": "fixture"}
    prepared, _ = prepare_item(item("model_configs", benchmark_observations=[observation]))
    assert prepared.family_features["benchmark_observations"] == [observation]
    observation.pop("harness")
    with pytest.raises(ValidationError):
        prepare_item(item("model_configs", benchmark_observations=[observation]))


@pytest.mark.parametrize("family", FAMILIES)
def test_committed_schemas_are_generated_from_current_contracts(family):
    path = Path(__file__).parents[2] / "src" / "tandem_backend" / "data" / "recommend" / (family + ".schema.json")
    # tests/recommend → project root
    assert json.loads(path.read_text(encoding="utf-8")) == catalog_schema(family)


@pytest.mark.parametrize("values", [{"task_weight": True}, {"effect_weight": float("nan")}, {"per_route": True}])
def test_policy_rejects_bool_and_nonfinite_weights(values):
    with pytest.raises(ValidationError):
        RankingPolicy(**values)
