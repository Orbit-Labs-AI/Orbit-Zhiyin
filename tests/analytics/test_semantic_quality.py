"""A fixed labeled corpus, separate from implementation rules and real history."""
import json
from pathlib import Path

import pytest

from tandem_backend.analytics.common import semantic_messages
from tandem_backend.analytics.preference import (
    extract_explicit_preferences,
    resolve_effective_preferences,
)
from tandem_backend.analytics.task import extract_task_features

CORPUS = json.loads((Path(__file__).parents[1] / "fixtures/semantic-quality-v1.json").read_text())


@pytest.mark.parametrize("case", CORPUS["preference"], ids=lambda c: c["id"])
def test_preference_labeled_case(case, fixtures):
    s, e, _ = fixtures
    result = extract_explicit_preferences([e(case["text"])], [s()], {"e": "t"})
    assert sorted(p["value"] for p in result["records"]) == sorted(case["values"])
    assert len(result["task_instructions"]) == case["instructions"]
    assert len(result["candidates"]) == case["candidates"]
    for p in result["records"]:
        assert p["preference_scope"]["kind"] == case["scope"]
        assert p["polarity"] == case.get("polarity", "prefer")


@pytest.mark.parametrize("case", CORPUS["task"], ids=lambda c: c["id"])
def test_task_labeled_case(case, fixtures):
    s, e, _ = fixtures
    result = extract_task_features(semantic_messages([e(case["text"])], [s()]))
    assert (result["domain"] or []) == case["domain"]
    assert (result["task_type"] or []) == case["task_type"]
    assert sorted(a["name"] for a in result["expected_artifacts"] or []) == sorted(case["artifact_names"])


def test_compatible_negative_constraint_is_not_a_conflict(fixtures):
    s, e, _ = fixtures
    records = extract_explicit_preferences([e("以后这个项目用中文，不要用英文")], [s()])["records"]
    result = resolve_effective_preferences(records, {"project_id": "p"})
    assert len(result["applicable"]) == 2 and not result["conflicts"]
