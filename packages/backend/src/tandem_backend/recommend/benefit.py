"""Conditional savings from observed incident counts and explicit assumptions.

No causal improvement or probability is inferred from relevance, ranking scores,
catalogue prose or confidence. Overlapping signals are separate alternatives.
"""

import math

_COUNT_PATHS = {
    "correction_density": "interaction.confirmed_correction_count",
    "identical_retries": "respond.retry_links.confirmed_same_arguments",
    "tool_failures": "respond.tools.by_tool.known_failure_count",
}


def _range(low, high):
    return {"low": round(low, 6), "high": round(high, 6)}


def _savings(count, scenario, unit_cost, setup, extra):
    if unit_cost is None:
        return {"status": "unknown", "missing": ["cost_per_occurrence"],
                "baseline": None, "gross_savings": None, "overhead": None, "net_savings": None,
                "break_even_windows": None}
    windows, rate = scenario.repeated_windows, scenario.reduction
    baseline_low, baseline_high = count * windows * unit_cost.low, count * windows * unit_cost.high
    gross_low, gross_high = baseline_low * rate.low, baseline_high * rate.high
    baseline, gross = _range(baseline_low, baseline_high), _range(gross_low, gross_high)
    missing = [name for name, value in (("setup_cost", setup), ("extra_cost_per_window", extra)) if value is None]
    if missing:
        return {"status": "partial", "missing": missing, "baseline": baseline,
                "gross_savings": gross, "overhead": None, "net_savings": None, "break_even_windows": None}
    overhead_low, overhead_high = setup.low + windows * extra.low, setup.high + windows * extra.high
    overhead = _range(overhead_low, overhead_high)
    net = _range(gross_low - overhead_high, gross_high - overhead_low)
    per_window_low = count * unit_cost.low * rate.low - extra.high
    per_window_high = count * unit_cost.high * rate.high - extra.low

    def break_even(setup_cost, saving):
        # Zero/negative running benefit never establishes positive payback.
        return max(1, math.ceil(setup_cost / saving)) if saving > 0 else None

    return {"status": "estimated", "missing": [], "baseline": baseline, "gross_savings": gross,
            "overhead": overhead, "net_savings": net,
            "break_even_windows": {"optimistic": break_even(setup.low, per_window_high),
                                   "conservative": break_even(setup.high, per_window_low)}}


def estimate_benefit(item, signals, scenarios, *, analysis_digest, conditions=()):
    own = [s for s in scenarios if s.resource_id == item.identity.id]
    supported = {s["signal_id"]: s for s in signals
                 if item.expected_effect.targets.get(s["rule_id"], 0) > 0}
    estimates, excluded = [], []
    for scenario in own:
        if analysis_digest is None or scenario.analysis_digest != analysis_digest:
            excluded.append({"signal_id": scenario.signal_id, "reason": "analysis_snapshot_mismatch"})
            continue
        signal = supported.get(scenario.signal_id)
        if signal is None:
            excluded.append({"signal_id": scenario.signal_id, "reason": "signal_not_supported_in_this_scope"})
            continue
        path = _COUNT_PATHS.get(signal["rule_id"])
        values = [m.get("value") for m in signal["metrics"] if path is not None and m.get("path") == path]
        count = values[0] if len(values) == 1 else None
        if (isinstance(count, bool) or not isinstance(count, (int, float))
                or not math.isfinite(count) or count < 0 or int(count) != count):
            excluded.append({"signal_id": scenario.signal_id, "reason": "supported_incident_count_unavailable"})
            continue
        time = _savings(count, scenario, scenario.minutes_per_occurrence,
                        scenario.setup_minutes, scenario.extra_minutes_per_window)
        tokens = _savings(count, scenario, scenario.tokens_per_occurrence,
                          scenario.setup_tokens, scenario.extra_tokens_per_window)
        estimates.append({"signal_id": scenario.signal_id, "rule_id": signal["rule_id"],
                          "scope": signal["scope"], "observed_occurrences": count, "count_path": path,
                          "evidence": signal["evidence"], "assumptions": scenario.model_dump(mode="json"),
                          "time_minutes": time, "tokens": tokens})
    status = ("estimated" if any(e[unit]["status"] == "estimated" for e in estimates for unit in ("time_minutes", "tokens"))
              else "partial" if estimates else "insufficient_inputs")
    return {"status": status, "basis": "conditional_scenario", "effect_status": "unmeasured",
            "conditions": list(conditions), "estimates": estimates, "excluded": excluded,
            "missing": [] if estimates else ["matching_observed_signal_and_explicit_scenario"],
            "formula": "net = observed_occurrences × repeated_windows × cost_per_occurrence × reduction − setup_cost − repeated_windows × extra_cost_per_window",
            "aggregation": "alternatives_not_additive",
            "limitations": ["改善比例、单次成本和新增开销由调用者明确提供，尚无因果效果校准。",
                            "上下限是情景边界，不是置信区间；窗口重复是预测假设，不是新增观察。",
                            "验收通过率和验证覆盖不得下降；不能通过少测或跳过错误制造收益。"]}


class _Range:
    __slots__ = ("low", "high")

    def __init__(self, low: float, high: float):
        self.low, self.high = low, high


class _Scenario:
    __slots__ = ("repeated_windows", "reduction")

    def __init__(self, windows: float, reduction: _Range):
        self.repeated_windows, self.reduction = windows, reduction


def beta_interval(alpha: float, beta: float, z: float = 1.645) -> tuple[float, float]:
    """Central ~90 % interval of Beta(alpha, beta) by the normal approximation, clipped to [0, 1]."""
    n = alpha + beta
    mean = alpha / n
    sd = math.sqrt(alpha * beta / (n * n * (n + 1)))
    return max(0., mean - z * sd), min(1., mean + z * sd)


def card_savings(occurrences_per_window: float, windows: float, unit_minutes: float,
                 reduction: tuple[float, float]) -> dict:
    """Engine-card savings on the same scenario-bound口径 as ``estimate_benefit``.

    ``occurrences_per_window`` is observed; ``unit_minutes`` must carry a source (the caller
    checks); ``reduction`` is a (low, high) improvement fraction. Setup/extra costs are not
    known per card, so the result is the gross range (``status='partial'``), never a net figure.
    """
    scenario = _Scenario(windows, _Range(*reduction))
    return _savings(occurrences_per_window, scenario, _Range(unit_minutes, unit_minutes), None, None)
