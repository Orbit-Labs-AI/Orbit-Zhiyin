"""Report examples execute the production recommendation pipeline."""

import importlib
from pathlib import Path


def test_generated_counterfactuals_and_arithmetic_are_fixed_oracles(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    validation = importlib.import_module("evals.recommendation.validation")
    _, analysis, items, cases = validation.generate_cases()
    assert len(items) == 4 and all(i["source"]["verified_sha"] for i in items)
    assert len(cases) >= 25
    assert all(case["passed"] for case in cases), [(c["id"], c["checks"]) for c in cases if not c["passed"]]
    assert len({case["result"]["analysis_digest"] for case in cases[:6]}) == 1
    assert all(case["result"]["signals"] == cases[0]["result"]["signals"] for case in cases[:6])
    positive = next(c for c in cases if c["id"] == "benefit-positive")
    card = positive["result"]["recommendations"][0]
    assert card["benefit_estimate"]["estimates"][0]["tokens"]["net_savings"] == {"low": 2500., "high": 8700.}
    assert card["priority_score"] == cases[0]["result"]["recommendations"][0]["priority_score"]
    assert analysis["sessions"][0]["session_uid"] == "demo"
