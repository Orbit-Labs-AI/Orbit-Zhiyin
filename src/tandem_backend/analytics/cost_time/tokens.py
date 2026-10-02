"""Canonical token buckets and reliable per-request identities."""




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
    values = list(normalize_token_buckets(row).values())
    if all(v is not None for v in values):
        return sum(values)
    return None


def prepare_requests(model_calls):
    unique, conflicts, duplicate_n, invalid_n = {}, set(), 0, 0
    for c in model_calls or []:
        key = (c.get("session_uid"), c.get("call_uid"))
        if not (c.get("usage_scope") == "call" and c.get("measurement") == "delta"
                and key[0] and key[1] and c.get("boundary_reliable") is True):
            invalid_n += 1
            continue
        if key in unique:
            if c != unique[key]:
                conflicts.add(key)
            else:
                duplicate_n += 1
        else:
            unique[key] = c
    valid = [c for key, c in unique.items() if key not in conflicts]
    return {"requests": valid, "invalid_request_rows": invalid_n,
            "duplicate_request_rows": duplicate_n,
            "conflicting_request_ids": [{"session_uid": sid, "call_uid": uid} for sid, uid in sorted(conflicts)]}
