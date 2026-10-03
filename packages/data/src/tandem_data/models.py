"""Built-in model aliases and a versioned list-price table.

Aliases map a native model string (``claude-sonnet-4-5-20250929``, ``anthropic/claude-opus-4.6``,
``us.anthropic.claude-haiku-4-5-v1:0``) to a canonical id. They are seeded into ``model_alias``
with ``INSERT OR IGNORE`` so user-maintained rows always win.

Prices live in ``prices.json`` (USD per million tokens, each row tied to a provider source
URL and retrieval date). A cost is only computed for a resolved model with a price row and
complete token buckets; everything else stays NULL (``cost_source`` NULL) so cost cards show
"unknown", never zero. Anthropic cache writes are priced per TTL bucket: when a call wrote
cache tokens but the 1h/5m split is not reported, the cost is NULL rather than assuming the
cheaper 5m rate. The cost of a subscription session is the API-equivalent list price, not
what the user paid.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files

_TABLE = json.loads(files("tandem_data").joinpath("prices.json").read_text())
PRICE_TABLE_VERSION = _TABLE["version"]
PRICE_SOURCES: dict[str, dict] = _TABLE["sources"]
# canonical id -> row (input, output, cache_read, cache_write_5m, cache_write_1h, ...).
PRICES: dict[str, dict] = _TABLE["models"]

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


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def cost_usd(
    model_id: str | None, tokens: dict, *, cache_write_1h: int | None = None
) -> float | None:
    """List-price USD for one call with complete buckets; None when unpriced or incomplete.

    ``tokens`` holds the four normalized buckets; ``cache_write_1h`` is the part of
    ``cache_write_tokens`` written with a 1-hour TTL (Anthropic ``cache_creation``), or None
    when the harness did not report the split.
    """
    price = PRICES.get(model_id or "")
    if price is None:
        return None
    inp, out, read = (tokens.get(n) for n in ("input_tokens", "output_tokens", "cache_read_tokens"))
    write = tokens.get("cache_write_tokens")
    # Missing buckets are never inferred as zero.
    if not all(_count(value) for value in (inp, out, read)):
        return None
    total = inp * price["input"] + out * price["output"] + read * price["cache_read"]
    if price.get("cache_write_billed", True):
        if not _count(write):
            return None
        if write:
            if not _count(cache_write_1h) or cache_write_1h > write:
                return None
            total += (write - cache_write_1h) * price["cache_write_5m"]
            total += cache_write_1h * price["cache_write_1h"]
    elif write is not None and not _count(write):
        return None
    limit = price.get("max_prompt_tokens")
    if limit is not None and inp + read + (write or 0) > limit:
        return None
    return round(total / 1_000_000, 8)
