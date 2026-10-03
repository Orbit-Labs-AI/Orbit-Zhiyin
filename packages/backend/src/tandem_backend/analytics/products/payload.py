"""Bounded public payloads: evidence arrays keep a capped prefix plus their exact length.

A large home produced a 955 MB products response (and snapshot) dominated by per-call
evidence: statistics samples, journey lane events, duration rows and uid lists. Aggregates
(counts, summaries, comparisons) are computed before this cap, so they stay exact; the cap
only bounds the illustrative evidence that accompanies them.
"""

from typing import Any

from .tools import EVIDENCE_LIMIT

CAPPED_KEYS = frozenset({
    "samples", "events", "execution_durations", "session_spans",
    "evidence_event_uids", "evidence_ids", "event_uids", "call_uids", "session_uids",
})


def compact(value: Any, limit: int = EVIDENCE_LIMIT, keys: frozenset[str] = CAPPED_KEYS) -> Any:
    """Return a copy whose ``keys`` arrays hold ≤ ``limit`` items and ``<key>_total``."""
    if isinstance(value, list):
        return [compact(item, limit, keys) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in keys and isinstance(item, list) and len(item) > limit:
            result[key] = [compact(entry, limit, keys) for entry in item[:limit]]
            result[f"{key}_total"] = len(item)
        else:
            result[key] = compact(item, limit, keys)
    return result
