"""Per-million-token list prices used when an engine does not report cost itself."""

from __future__ import annotations

# (input, output) USD per MTok, keyed by model family; ids are matched by family name.
PRICES = {
    "haiku": (1.0, 5.0),    # claude-haiku-4-5
    "sonnet": (2.0, 10.0),  # claude-sonnet-5-5
    "opus": (4.0, 20.0),    # claude-opus-5-5
}


def family(model: str | None) -> str | None:
    lowered = (model or "").lower()
    return next((name for name in PRICES if name in lowered), None)


def estimate(tokens_in: int, tokens_out: int, model: str | None) -> float | None:
    """USD for one call, or ``None`` when the model is unknown."""
    name = family(model)
    if name is None:
        return None
    price_in, price_out = PRICES[name]
    return round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 6)
