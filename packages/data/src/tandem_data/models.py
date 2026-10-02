"""Built-in model aliases and a versioned list-price table.

Aliases map a native model string (``claude-sonnet-4-5-20250929``, ``anthropic/claude-opus-4.6``,
``us.anthropic.claude-haiku-4-5-v1:0``) to a canonical id. They are seeded into ``model_alias``
with ``INSERT OR IGNORE`` so user-maintained rows always win.

Prices are public first-party list prices in USD per million tokens. A cost is only computed
for a resolved model with a price row and complete token buckets; everything else stays NULL
(``cost_source`` NULL) so cost cards show "unknown", never zero. The cost of a subscription
session is the API-equivalent list price, not what the user paid.
"""

from __future__ import annotations

import re

PRICE_TABLE_VERSION = "anthropic-list-2026-09"

# canonical id -> (input, output, cache_read, cache_write_5m) USD per MTok.
_CLAUDE = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-3-7-sonnet": (3.0, 15.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-3-5-haiku": (0.8, 4.0),
}
PRICES = {
    model: (inp, out, round(inp * 0.1, 6), round(inp * 1.25, 6))
    for model, (inp, out) in _CLAUDE.items()
}
_CACHE_READ_OVERRIDES = {
    "claude-fable-5-1": 0.25,
    "claude-opus-5-5": 0.20,
    "claude-sonnet-5-5": 0.20,
}
for _model, _read in _CACHE_READ_OVERRIDES.items():
    PRICES[_model] = (*PRICES[_model][:2], _read, PRICES[_model][3])

_PREFIX = re.compile(r"^(?:[a-z0-9-]+\.)?(?:anthropic[./:])|^(?:openai|google|models)/")
_DATE = re.compile(r"(?:-|@)(?:20\d{6}|\d{4}-\d{2}-\d{2})$")
_BEDROCK = re.compile(r"-v\d+(?::\d+)?$")
_CONTEXT = re.compile(r"\[[^\]]*\]$")
_FAMILIES = (
    "claude",
    "gpt",
    "o1",
    "o3",
    "o4",
    "gemini",
    "glm",
    "kimi",
    "qwen",
    "deepseek",
    "grok",
    "llama",
    "mistral",
)


def canonical_model(raw: str | None) -> tuple[str, str | None] | None:
    """(canonical id, family) for a native model string, or None when it is not a model name."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if not value or value.startswith("<") or len(value) > 120:
        return None
    value = _CONTEXT.sub("", value)
    value = _PREFIX.sub("", value)
    value = value.rsplit("/", 1)[-1]
    value = _BEDROCK.sub("", value)
    value = _DATE.sub("", value)
    if value.startswith("claude"):
        # claude-opus-4.6 / claude-opus-4-6-thinking -> claude-opus-4-6
        value = value.replace(".", "-").removesuffix("-thinking")
    family = next((name for name in _FAMILIES if value.startswith(name)), None)
    if family is None or not re.fullmatch(r"[a-z0-9][a-z0-9.:_-]*", value):
        return None
    if family == "claude":
        family = next(
            (tier for tier in ("fable", "opus", "sonnet", "haiku", "mythos") if tier in value),
            "claude",
        )
    return value, family


def cost_usd(model_id: str | None, tokens: dict) -> float | None:
    """List-price USD for one call with complete buckets; None when unpriced or incomplete."""
    price = PRICES.get(model_id or "")
    if price is None:
        return None
    buckets = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    values = [tokens.get(name) for name in buckets]
    # Missing buckets are never inferred as zero.
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        return None
    return round(sum(v * p for v, p in zip(values, price, strict=True)) / 1_000_000, 8)
