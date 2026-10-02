"""A configurable trial-priority score, not a promised performance gain."""

import math

from ..contracts import RankingPolicy


def _unit(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.
    return min(1., max(0., float(value)))


def score_candidate(features: dict, policy: RankingPolicy) -> tuple[float, dict]:
    """Normalize positive weights, subtract costs, then apply evidence/context factors."""
    weights = {"task_match": policy.task_weight, "trigger_match": policy.trigger_weight,
               "effect_match": policy.effect_weight, "context_match": policy.context_weight,
               "evidence_quality": policy.evidence_weight, "fusion_match": policy.fusion_weight}
    positive = {name: weight * _unit(features.get(name)) for name, weight in weights.items()}
    penalties = {"friction": policy.friction_weight * _unit(features.get("friction")),
                 "risk": policy.risk_weight * _unit(features.get("risk"))}
    weight_sum = sum(weights.values())
    grounded = (features.get("grounded") is True and
                (_unit(features.get("trigger_match")) > 0. or _unit(features.get("effect_match")) > 0.))
    confidence = _unit(features.get("confidence"))
    compatibility = _unit(features.get("compatibility_factor"))
    base = max(0., (sum(positive.values()) - sum(penalties.values())) / weight_sum) if weight_sum else 0.
    score = _unit(base * confidence * compatibility) if grounded else 0.
    return score, {"positive_contributions": positive, "penalties": penalties,
                   "positive_weight_sum": weight_sum, "base_score": base,
                   "evidence_confidence": confidence, "compatibility_factor": compatibility,
                   "grounded": grounded, "score": score,
                   "meaning": "启发式试用优先级；不是效果百分比、成功概率或已测量收益。"}
