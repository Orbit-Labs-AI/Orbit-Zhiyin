"""Arithmetic oracles and abstention, not claimed skill efficacy."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_recommend_pipeline import correction_bundle, ready_item

from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.recommend.benefit import estimate_benefit
from tandem_backend.recommend.contracts import (
    BenefitScenario,
    RecommendationContext,
    RecommendationItem,
)
from tandem_backend.recommend.service import recommend


def value(low, high=None):
    return {"low": low, "high": low if high is None else high}


def estimate(**updates):
    analysis = analyze_bundle(correction_bundle(), with_text=False)
    baseline = recommend(analysis, catalog=[ready_item()])
    card = baseline["recommendations"][0]
    scenario = {"resource_id": card["resource_id"], "signal_id": card["signal_id"],
                "analysis_digest": analysis["analysis_digest"],
                "repeated_windows": 4, "reduction": value(.25, .5),
                "minutes_per_occurrence": value(10), "setup_minutes": value(5, 10),
                "extra_minutes_per_window": value(1, 2), "basis": "Synthetic cost and improvement assumptions."}
    scenario.update(updates)
    result = recommend(analysis, catalog=[ready_item()], context={"benefit_scenarios": [scenario]})
    return result["recommendations"][0], card


def test_count_is_observed_but_rate_and_cost_are_explicit_assumptions():
    card, baseline = estimate()
    result = card["benefit_estimate"]
    assert result["status"] == "estimated"
    row = result["estimates"][0]
    assert row["observed_occurrences"] == 3
    assert row["time_minutes"]["baseline"] == value(120)
    assert row["time_minutes"]["gross_savings"] == value(30, 60)
    assert row["time_minutes"]["overhead"] == value(9, 18)
    assert row["time_minutes"]["net_savings"] == value(12, 51)
    assert row["time_minutes"]["break_even_windows"] == {"optimistic": 1, "conservative": 2}
    assert row["tokens"]["net_savings"] is None
    assert card["priority_score"] == baseline["priority_score"]
    assert card["effect_status"] == result["effect_status"] == "unmeasured"
    assert card["evaluation_plan"]["observed_effect"] is None


def test_token_costs_have_their_own_units_and_explicit_zero_overhead():
    card, _ = estimate(tokens_per_occurrence=value(1000, 2000), setup_tokens=value(0), extra_tokens_per_window=value(100))
    tokens = card["benefit_estimate"]["estimates"][0]["tokens"]
    assert tokens["net_savings"] == value(2600, 11600)


@pytest.mark.parametrize("missing", ["setup_minutes", "extra_minutes_per_window"])
def test_unknown_overhead_is_not_free(missing):
    card, _ = estimate(**{missing: None})
    time = card["benefit_estimate"]["estimates"][0]["time_minutes"]
    assert time["status"] == "partial"
    assert time["gross_savings"] == value(30, 60)
    assert time["net_savings"] is None and time["overhead"] is None


def test_missing_baseline_is_not_zero_savings():
    card, _ = estimate(minutes_per_occurrence=None)
    time = card["benefit_estimate"]["estimates"][0]["time_minutes"]
    assert time["net_savings"] is None and time["baseline"] is None


def test_negative_net_and_no_payback_are_preserved():
    card, _ = estimate(setup_minutes=value(100), extra_minutes_per_window=value(20))
    time = card["benefit_estimate"]["estimates"][0]["time_minutes"]
    assert time["net_savings"] == value(-150, -120)
    assert time["break_even_windows"] == {"optimistic": None, "conservative": None}


def test_zero_improvement_cannot_become_positive_benefit():
    card, _ = estimate(reduction=value(0))
    time = card["benefit_estimate"]["estimates"][0]["time_minutes"]
    assert time["gross_savings"] == value(0)
    assert time["net_savings"] == value(-18, -9)


def test_wrong_signal_cannot_borrow_counts_from_another_scope():
    card, _ = estimate(signal_id="different-session-or-stale-signal")
    result = card["benefit_estimate"]
    assert result["status"] == "insufficient_inputs" and result["estimates"] == []
    assert result["excluded"][0]["reason"] == "signal_not_supported_in_this_scope"


def test_no_assumptions_means_no_invented_benefit():
    _, card = estimate()
    assert card["benefit_estimate"]["status"] == "insufficient_inputs"


def test_same_signal_id_in_another_snapshot_cannot_reuse_old_assumptions():
    card, _ = estimate(analysis_digest="stale-analysis")
    result = card["benefit_estimate"]
    assert result["status"] == "insufficient_inputs" and not result["estimates"]
    assert result["excluded"][0]["reason"] == "analysis_snapshot_mismatch"


def test_rounding_does_not_erase_small_positive_payback():
    card, _ = estimate(minutes_per_occurrence=value(.000001), reduction=value(.1),
                       setup_minutes=value(.000001), extra_minutes_per_window=value(0))
    time = card["benefit_estimate"]["estimates"][0]["time_minutes"]
    assert time["break_even_windows"] == {"optimistic": 4, "conservative": 4}


@pytest.mark.parametrize("field,bad", [
    ("reduction", value(-.1)), ("reduction", value(.9, .1)), ("reduction", value(1.1)),
    ("minutes_per_occurrence", value(float("nan"))), ("minutes_per_occurrence", value(float("inf"))),
    ("minutes_per_occurrence", value(True)), ("setup_tokens", value(-1)),
    ("repeated_windows", True), ("repeated_windows", 0), ("repeated_windows", "10"), ("basis", " "),
])
def test_invalid_scenarios_rejected(field, bad):
    scenario = {"resource_id": "x", "signal_id": "s", "analysis_digest": "current", "reduction": value(.2), "basis": "hypothesis"}
    scenario[field] = bad
    with pytest.raises(ValidationError):
        BenefitScenario.model_validate(scenario)


def test_estimates_do_not_mutate_input_and_keep_alternatives_separate():
    analysis = analyze_bundle(correction_bundle(), with_text=False)
    item = RecommendationItem.model_validate(ready_item())
    signal = recommend(analysis, catalog=[item])["signals"][0]
    other = deepcopy(signal)
    other.update(signal_id="other-rule", rule_id="tool_failures")
    other["metrics"] = [{"path": "respond.tools.by_tool.known_failure_count", "value": 2}]
    item.expected_effect.targets["tool_failures"] = 1.
    scenarios = [BenefitScenario(resource_id=item.identity.id, signal_id=s["signal_id"],
                 analysis_digest=analysis["analysis_digest"],
                 reduction=value(.5), minutes_per_occurrence=value(10), setup_minutes=value(0),
                 extra_minutes_per_window=value(0), basis="Synthetic scenario") for s in (signal, other)]
    before = deepcopy((item, signal, other, scenarios))
    result = estimate_benefit(item, [signal, other], scenarios, analysis_digest=analysis["analysis_digest"], conditions=["tools:pytest"])
    assert result["aggregation"] == "alternatives_not_additive"
    assert [r["time_minutes"]["net_savings"] for r in result["estimates"]] == [value(15), value(10)]
    assert "total" not in result and result["conditions"] == ["tools:pytest"]
    assert (item, signal, other, scenarios) == before


def test_duplicate_scenarios_cannot_double_count_savings():
    scenario = {"resource_id": "x", "signal_id": "s", "analysis_digest": "current", "reduction": value(.2), "basis": "hypothesis"}
    with pytest.raises(ValidationError, match="Duplicate"):
        RecommendationContext(benefit_scenarios=[scenario, scenario])


def test_card_savings_uses_scenario_bounds():
    from tandem_backend.recommend.benefit import beta_interval, card_savings

    lo, hi = beta_interval(9, 1)
    # mean .9, sd = √(9·1 / (10²·11)) = .0904534 ; ±1.645·sd = .1487958 ; upper clipped at 1
    assert lo == pytest.approx(.7512042, abs=1e-6) and hi == 1.
    out = card_savings(10, 4, 2., (.25, .5))
    # baseline 10 × 4 × 2 = 80 min; gross = 80 × [.25, .5] = [20, 40]; overhead unknown → partial
    assert out["status"] == "partial" and out["baseline"] == {"low": 80, "high": 80}
    assert out["gross_savings"] == {"low": 20, "high": 40} and out["net_savings"] is None


@pytest.mark.parametrize("agent", ["generic", "claude_code", "codex", "opencode", "pi", "hermes", "dsh", "kimi"])
def test_context_agent_accepts_the_analytics_targets(agent):
    assert RecommendationContext(agent=agent).agent == agent


@pytest.mark.parametrize("agent", ["claude", "Codex", "gemini", "unknown"])
def test_context_agent_rejects_names_outside_the_targets(agent):
    with pytest.raises(ValueError, match="Unknown agent"):
        RecommendationContext(agent=agent)
