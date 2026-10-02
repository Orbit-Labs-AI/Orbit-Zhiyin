"""Bottleneck-to-intervention relevance, not an estimated improvement rate."""

from ..contracts import RecommendationItem, RecommendationState
from ._common import ranked


def recall(state: RecommendationState, items: list[RecommendationItem],
           limit: int = 50) -> list[tuple[str, float]]:
    """Score the exact-key dot product of two nonnegative target vectors.

    Components are bounded by the contract. Their sum may exceed one; callers
    must not display it as a probability, percentage gain, or causal estimate.
    """
    scores: dict[str, float] = {}
    for item in items:
        score = sum(weight * item.expected_effect.targets.get(key, 0.)
                    for key, weight in sorted(state.bottleneck_vector.items()))
        scores[item.identity.id] = max(scores.get(item.identity.id, 0.), score)
    return ranked(scores, limit)
