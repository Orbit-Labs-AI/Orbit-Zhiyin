"""Common candidate features, separate from recall and final ranking."""

import math
import re

from .contracts import Candidate, RecommendationItem, RecommendationState
from .preferences import match_preferences
from .ranking.filters import FilterDecision

COMPATIBILITY_FACTORS = {"native": 1., "manual": 1., "adaptation_required": .55, "unknown": .35,
                         "unsupported": 0.}


def _unit(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return 0.
    return max(0., min(1., float(value)))


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_+#]+(?:[.-][a-z0-9_+#]+)*|[\u4e00-\u9fff]", value.casefold()))


def _task_match(state: RecommendationState, item: RecommendationItem) -> float:
    # Sparse recall may also match problem/context text, so its score is not a
    # task-match measurement. It contributes through RRF, not this feature.
    target = _tokens(" ".join([item.target_task.text, *item.target_task.tags]))
    current = _tokens(state.task_text)
    text_match = len(target & current) / len(target) if target else 0.
    return text_match


def _has_evidence(signal: dict) -> bool:
    rows = signal.get("evidence")
    return isinstance(rows, list) and any(
        isinstance(row, dict) and row.get("id") and row.get("session_uid") and row.get("kind") for row in rows)


def _context_match(state: RecommendationState, item: RecommendationItem, decision: FilterDecision) -> float:
    context = state.context_state
    components = [COMPATIBILITY_FACTORS.get(decision.compatibility, 0.)]
    # Rejected incompatibilities have already been handled by the hard filter.
    if item.compatibility.os:
        components.append(float(context.os is not None and "os" not in decision.pending_requirements))
    for expected, observed in ((item.compatibility.languages, context.languages),
                               (item.compatibility.frameworks, context.frameworks)):
        if expected:
            components.append(float(bool(observed) and bool(
                {name.casefold() for name in expected} & {name.casefold() for name in observed})))
    for kind, required in (("tools", item.requirements.tools), ("software", item.requirements.software),
                           ("resources", item.requirements.resources)):
        if required:
            components.append(float(not any(value.startswith(f"{kind}:")
                                            for value in decision.pending_requirements)))
    return sum(components) / len(components)


def candidate_features(state: RecommendationState, item: RecommendationItem, candidate: Candidate,
                       decision: FilterDecision, *, fusion_upper_bound: float | None = None) -> dict:
    """Create bounded features without changing analytics, items or candidates.

    RRF normalization needs the *enabled routes'* total upper bound, not the
    number of routes this candidate happened to match. A missing bound abstains
    from adding a fusion feature. Only evidence-backed signals ground a match.
    """
    valid_signals = [signal for signal in state.signals if isinstance(signal, dict) and _has_evidence(signal)]
    item_tags = set(item.capability.tags) | set(item.trigger.tags)
    item_rules = set(item.trigger.rule_ids)
    trigger_signals = [signal for signal in valid_signals if signal.get("rule_id") in item_rules
                       or bool(set(signal.get("capabilities") or []) & item_tags)]
    supported_rules = {signal.get("rule_id") for signal in valid_signals}
    vector = {rule: value for rule, value in state.bottleneck_vector.items() if rule in supported_rules}
    total = sum(vector.values())
    dot = sum(value * item.expected_effect.targets.get(rule, 0.) for rule, value in vector.items())
    effect_match = dot / total if total else 0.
    effect_signals = [signal for signal in valid_signals
                      if vector.get(signal.get("rule_id"), 0.) > 0.
                      and item.expected_effect.targets.get(signal.get("rule_id"), 0.) > 0.]
    matching = sorted(trigger_signals + effect_signals,
                      key=lambda signal: (-_unit(signal.get("confidence")) * _unit(signal.get("severity")),
                                          -_unit(signal.get("confidence")), str(signal.get("signal_id", ""))))
    primary = matching[0] if matching else {}
    upper = fusion_upper_bound
    fusion = (candidate.fusion_score / upper
              if isinstance(upper, (int, float)) and not isinstance(upper, bool)
              and math.isfinite(upper) and upper > 0. else 0.)
    preference = match_preferences(state, item)
    return {
        "task_match": _unit(_task_match(state, item)),
        "trigger_match": float(bool(trigger_signals)),
        "effect_match": _unit(effect_match),
        "preference_match": preference["score"],
        "preference_active": preference["active"],
        "preference_matches": preference["matches"],
        "context_match": _unit(_context_match(state, item, decision)) if decision.eligible else 0.,
        "evidence_quality": _unit(item.evidence_quality.score),
        "friction": _unit(.7 * item.friction.setup_cost + .3 * item.friction.runtime_cost),
        "risk": _unit(item.risk_permission.level),
        "fusion_match": _unit(fusion),
        "confidence": _unit(primary.get("confidence")),
        "compatibility_factor": COMPATIBILITY_FACTORS.get(decision.compatibility, 0.) if decision.eligible else 0.,
        "grounded": bool(matching),
        "primary_signal_id": primary.get("signal_id"),
        "grounded_signal_ids": sorted({str(signal["signal_id"]) for signal in matching if signal.get("signal_id")}),
        "pending_requirements": list(decision.pending_requirements),
    }
