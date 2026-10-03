"""Canonical token buckets and reliable per-request identities."""

from collections import Counter

TOKEN_BUCKETS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def token_number(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def normalize_token_buckets(row):
    """v1 canonical input is uncached; adapters may explicitly declare inclusion."""
    buckets = {k: row.get(k) if token_number(row.get(k)) else None for k in TOKEN_BUCKETS}
    semantics = row.get("input_tokens_semantics", "uncached")
    if semantics == "includes_cache":
        parts = [buckets[k] for k in TOKEN_BUCKETS[:3]]
        buckets["input_tokens"] = parts[0] - parts[1] - parts[2] if all(v is not None for v in parts) else None
        if buckets["input_tokens"] is not None and buckets["input_tokens"] < 0:
            buckets["input_tokens"] = None
    elif semantics != "uncached":
        buckets["input_tokens"] = None
    return buckets


def token_total(row):
    """Sum of normalize_token_buckets(row), or None if any bucket is unknown (no dict built)."""
    i, r, w, o = (row.get(k) for k in TOKEN_BUCKETS)
    if not (token_number(r) and token_number(w) and token_number(o)):
        return None
    semantics = row.get("input_tokens_semantics", "uncached")
    if not token_number(i) or semantics not in ("uncached", "includes_cache"):
        return None
    if semantics == "includes_cache":
        i = i - r - w
        if i < 0:
            return None
    return i + r + w + o


def prepare_requests(model_calls):
    unique, conflicts, duplicate_n, invalid_n = {}, set(), 0, 0
    reasons, qualities = Counter(), Counter()
    for c in model_calls or []:
        key = (c.get("session_uid"), c.get("call_uid"))
        # Typed L3 rows carry identity/boundary quality, not duplicate call/delta
        # fields. Legacy adapters retain their explicit measurement contract.
        typed = "request_identity_quality" in c or "boundary_quality" in c
        reason = (
            "missing_request_identity" if not all(key) else
            "non_call_delta" if (c.get("usage_scope", "call" if typed else None) != "call"
                                 or c.get("measurement", "delta" if typed else None) != "delta") else
            "unknown_request_identity" if typed and c.get("request_identity_quality") not in ("reported", "derived") else
            "unreliable_request_boundary" if typed and c.get("boundary_quality") not in ("reported", "observed") else
            "unreliable_request_boundary" if not typed and c.get("boundary_reliable") is not True else None
        )
        if reason:
            invalid_n += 1
            reasons[reason] += 1
            continue
        if key in unique:
            if c != unique[key]:
                conflicts.add(key)
            else:
                duplicate_n += 1
        else:
            unique[key] = c
    valid = [c for key, c in unique.items() if key not in conflicts]
    qualities.update(c.get("boundary_quality", "legacy_reliable") for c in valid)
    return {"requests": valid, "invalid_request_rows": invalid_n,
            "invalid_request_reasons": dict(sorted(reasons.items())),
            "request_boundary_qualities": dict(sorted(qualities.items())),
            "duplicate_request_rows": duplicate_n,
            "conflicting_request_ids": [{"session_uid": sid, "call_uid": uid} for sid, uid in sorted(conflicts)]}
