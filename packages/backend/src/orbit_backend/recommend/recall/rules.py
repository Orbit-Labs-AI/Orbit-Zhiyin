"""High-precision recall from already-established diagnostic signals."""

from ..contracts import RecommendationItem, RecommendationState
from ._common import names, ranked


def recall(state: RecommendationState, items: list[RecommendationItem],
           limit: int = 50) -> list[tuple[str, float]]:
    """Match declared rule IDs or intervention capabilities, never context alone.

    This layer trusts the state's upstream diagnosis rather than evaluating raw
    analytics thresholds for a second time. A rule match scores 1; capability
    overlap scores at most .8, relative to the item's declared capabilities.
    """
    scores: dict[str, float] = {}
    for item in items:
        item_caps = names(item.capability.tags)
        item_rules = set(item.trigger.rule_ids)
        best = 0.
        for signal in state.signals:
            signal_rule = signal.get("rule_id")
            raw_caps = signal.get("capabilities", [])
            signal_caps = names([value for value in raw_caps if isinstance(value, str)]) \
                if isinstance(raw_caps, list) else set()
            exact = isinstance(signal_rule, str) and signal_rule in item_rules
            overlap = len(signal_caps & item_caps) / len(item_caps) if item_caps else 0.
            best = max(best, 1. if exact else .8 * overlap)
        scores[item.identity.id] = max(scores.get(item.identity.id, 0.), best)
    return ranked(scores, limit)
