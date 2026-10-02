"""Deterministic maximal marginal relevance over intervention descriptors."""

import math
from collections import Counter
from copy import deepcopy

from ..contracts import RankingPolicy


def _tags(row: dict) -> set[str]:
    item = row["item"]
    return ({f"capability:{tag}" for tag in item.capability.tags}
            | {f"effect:{tag}" for tag, value in item.expected_effect.targets.items() if value > 0.}
            | {f"family:{item.family}"})


def _similarity(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.


def _rule(row: dict) -> str:
    return str(row.get("signal", {}).get("rule_id") or "")


def _tie_key(row: dict) -> tuple:
    return (-row["score"], _rule(row), row["item"].identity.id,
            str(row.get("signal", {}).get("signal_id") or ""))


def select_diverse(ranked: list[dict], limit: int, policy: RankingPolicy) -> list[dict]:
    """Return copies with MMR explanations, preserving original scores and inputs.

    Resource identity is globally unique in a slate. Up to two recommendations
    per diagnosed rule preserve room for other bottlenecks. The cap applies to
    actual rules, not an artificial shared rule for rows lacking diagnosis.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return []
    remaining = [row for row in ranked if isinstance(row.get("score"), (float, int))
                 and not isinstance(row.get("score"), bool) and math.isfinite(row["score"]) and row["score"] > 0.]
    remaining.sort(key=_tie_key)
    selected: list[dict] = []
    selected_tags: list[set[str]] = []
    seen: set[str] = set()
    counts: Counter = Counter()
    while remaining and len(selected) < limit:
        eligible = [row for row in remaining if row["item"].identity.id not in seen
                    and (not _rule(row) or counts[_rule(row)] < 2)]
        if not eligible:
            break
        scores = [(policy.mmr_lambda * row["score"] - (1. - policy.mmr_lambda)
                   * max((_similarity(_tags(row), tags) for tags in selected_tags), default=0.), row)
                  for row in eligible]
        mmr, best = min(scores, key=lambda entry: (-entry[0], *_tie_key(entry[1])))
        result = deepcopy(best)
        result["mmr_score"] = mmr
        result["diversity_penalty"] = policy.mmr_lambda * best["score"] - mmr
        selected.append(result)
        selected_tags.append(_tags(best))
        seen.add(best["item"].identity.id)
        counts[_rule(best)] += 1
        # Equal dicts are still independent candidates; identity removal occurs
        # in the next eligible pass and does not modify the caller's collection.
        remaining = [row for row in remaining if row is not best]
    return selected
