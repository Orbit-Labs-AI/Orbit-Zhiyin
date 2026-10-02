"""Rank-only reciprocal-rank fusion for differently scaled recall routes."""

import math

from ..contracts import Candidate


def fuse(routes: dict[str, list[tuple[str, float]]], k: int = 60,
         weights: dict[str, float] | None = None) -> list[Candidate]:
    """Sum weight/(k + rank), with 1-based rank after per-route deduplication.

    Routes supply already-ranked rows; raw scores are explanatory metadata,
    never used to compare unlike algorithms. The first occurrence of an ID
    wins inside a route. Zero-score rows are omitted, avoiding unsupported
    candidates when a caller passes a full corpus rather than a top list.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("RRF k must be a positive integer")
    weights = {} if weights is None else weights
    if set(weights) - set(routes):
        raise ValueError("RRF weights contain an unknown route")
    for weight in weights.values():
        if (isinstance(weight, bool) or not isinstance(weight, (int, float))
                or not math.isfinite(weight) or weight < 0):
            raise ValueError("RRF weights must be finite and nonnegative")
    candidates: dict[str, Candidate] = {}
    for route in sorted(routes):
        weight = weights.get(route, 1.)
        seen: set[str] = set()
        rank = 0
        for uid, score in routes[route]:
            if not isinstance(uid, str) or not uid:
                raise ValueError("recall candidate IDs must be nonempty strings")
            if (isinstance(score, bool) or not isinstance(score, (int, float))
                    or not math.isfinite(score) or score < 0):
                raise ValueError("recall scores must be finite and nonnegative")
            if uid in seen or not score:
                continue
            seen.add(uid)
            rank += 1
            if not weight:
                continue
            candidate = candidates.setdefault(uid, Candidate(item_id=uid))
            candidate.route_scores[route] = float(score)
            candidate.route_ranks[route] = rank
            candidate.fusion_score += weight / (k + rank)
    if any(not math.isfinite(candidate.fusion_score) for candidate in candidates.values()):
        raise ValueError("RRF weight magnitude overflowed the fusion score")
    return sorted(candidates.values(), key=lambda candidate: (-candidate.fusion_score, candidate.item_id))
