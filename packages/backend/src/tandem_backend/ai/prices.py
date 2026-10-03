"""Per-million-token list prices used when an engine does not report cost itself.

Source: Anthropic first-party API price list (claude-api skill model table, cached
2026-09-25). Keys are full model-ID prefixes, matched longest first, so a dated or
suffixed ID (``claude-opus-4-8-20260101``, ``claude-sonnet-5-5[1m]``) resolves to its own
version instead of the family's newest price. Unknown models return ``None``; callers
record ``cost_source='unknown'`` and budget them with ``CONSERVATIVE`` (never as $0).

Cache pricing: writes (5-minute TTL) cost 1.25x base input; reads cost 0.1x base input
unless the model has its own published cache-read price (Opus 5.5 $0.20, Fable 5.1 $0.25).
"""

from __future__ import annotations

CACHE_WRITE_X = 1.25
CACHE_READ_X = 0.1

# prefix -> (input, output, cache_read or None for CACHE_READ_X * input), USD per MTok.
PRICES: dict[str, tuple[float, float, float | None]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, None),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, None),
    "claude-opus-4-8": (5.0, 25.0, None),
    "claude-opus-4-7": (5.0, 25.0, None),
    "claude-opus-4-6": (5.0, 25.0, None),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, None),
    "claude-sonnet-4-6": (3.0, 15.0, None),
    "claude-haiku-4-5": (1.0, 5.0, None),
}
_ORDER = sorted(PRICES, key=len, reverse=True)

# Budget stand-in for calls whose model has no list price (codex, unknown IDs): the most
# expensive rate in the table, so an unpriced call can only over-count against the cap.
CONSERVATIVE = (max(p[0] for p in PRICES.values()), max(p[1] for p in PRICES.values()))


def lookup(model: str | None) -> tuple[float, float, float] | None:
    """(input, output, cache_read) USD/MTok for a model ID, or ``None`` when unknown."""
    lowered = (model or "").lower().strip()
    lowered = lowered.removeprefix("anthropic.")
    key = next((k for k in _ORDER if lowered == k or lowered.startswith(k + "-")
                or lowered.startswith(k + "[") or lowered.startswith(k + "@")), None)
    if key is None:
        return None
    price_in, price_out, read = PRICES[key]
    return price_in, price_out, read if read is not None else round(price_in * CACHE_READ_X, 6)


def cost(usage: dict, model: str | None) -> float | None:
    """USD for one call from an engine usage dict (input/cache_read/cache_write/output)."""
    price = lookup(model)
    if price is None:
        return None
    price_in, price_out, price_read = price
    total = ((usage.get("input") or 0) * price_in
             + (usage.get("cache_write") or 0) * price_in * CACHE_WRITE_X
             + (usage.get("cache_read") or 0) * price_read
             + (usage.get("output") or 0) * price_out)
    return round(total / 1_000_000, 6)


def estimate(tokens_in: int, tokens_out: int, model: str | None) -> float | None:
    """USD for uncached input + output, or ``None`` when the model is unknown."""
    return cost({"input": tokens_in, "output": tokens_out}, model)


def conservative(tokens_in: int, tokens_out: int) -> float:
    """Upper-bound USD for a call whose model has no list price."""
    return round((tokens_in * CONSERVATIVE[0] + tokens_out * CONSERVATIVE[1]) / 1_000_000, 6)
