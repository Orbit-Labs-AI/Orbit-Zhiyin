"""Resident-context overhead proxy: input side of each main session's first model request.

Consumed by ``analytics.metrics`` (``resident_tokens_median``). The former installed-but-unused
fact had no production entry (``analyze_signals`` was test-only); ``recommend.problems`` owns
the ``installed_unused`` problem.
"""

from collections import defaultdict
from typing import Any

from ..context import AnalysisContext
from ..cost_time.tokens import TOKEN_BUCKETS, normalize_token_buckets

Record = dict[str, Any]

INPUT_SIDE = TOKEN_BUCKETS[:3]  # uncached input + cache_read + cache_write; output excluded


def input_side_tokens(row: Record) -> int | None:
    """Full prompt size of one request: uncached input + cache read + cache write.

    Canonical ``input_tokens`` is *uncached* (``orbit_data.contract.normalize_usage``);
    for Claude-style agents almost the whole resident context lands in the cache buckets,
    so the uncached bucket alone is near zero. ``input_tokens_semantics`` is honoured via
    ``normalize_token_buckets``; any unknown bucket makes the request unknown (None).
    """
    buckets = normalize_token_buckets(row)
    parts = [buckets[k] for k in INPUT_SIDE]
    return sum(parts) if all(v is not None for v in parts) else None


def first_request_tokens(context: AnalysisContext) -> dict[str, int | None] | None:
    """Input-side tokens of the first model request per main session (resident overhead proxy)."""
    if context.model_calls is None:
        return None
    by_session = defaultdict(list)
    for m in context.model_calls:
        by_session[m["session_uid"]].append(m)
    out = {}
    for sid in sorted(context.main_ids):
        rows = sorted(by_session.get(sid, []), key=lambda m: (m.get("ts") is None, m.get("ts") or 0,
                                                               m.get("call_uid") or ""))
        out[sid] = input_side_tokens(rows[0]) if rows else None
    return out
