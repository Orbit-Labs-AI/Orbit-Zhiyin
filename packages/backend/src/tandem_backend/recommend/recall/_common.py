"""Small helpers shared by offline recall routes."""

import math


def ranked(scores: dict[str, float], limit: int) -> list[tuple[str, float]]:
    """Return only finite, positive scores in a reproducible order."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")
    if any(not math.isfinite(value) for value in scores.values()):
        raise ValueError("recall scores must be finite")
    return sorted(((key, value) for key, value in scores.items() if value > 0),
                  key=lambda row: (-row[1], row[0]))[:limit]


def names(values: list[str] | None) -> set[str]:
    return {value.strip().casefold() for value in values or [] if value.strip()}
