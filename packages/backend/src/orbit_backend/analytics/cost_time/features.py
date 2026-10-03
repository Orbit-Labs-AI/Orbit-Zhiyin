"""Request usage totals and isolated cumulative snapshots."""

import math
from collections import Counter
from statistics import median

from ..common import nonnegative_number, quantile
from .tokens import (
    TOKEN_BUCKETS,
    normalize_token_buckets,
    prepare_requests,
    token_number,
    token_total,
)


def usage(model_calls, events, sessions, scope, records_complete=True):
    prepared = prepare_requests(model_calls)
    valid = prepared["requests"]
    snapshots, legacy, regressed_keys = {}, {}, set()
    for e in sorted(events, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        if e["kind"] != "model.usage":
            continue
        a = e.get("attrs", {})
        if a.get("measurement") == "cumulative":
            key = (e["session_uid"], a.get("snapshot_key"))
            if key[1] and a.get("usage_scope") in ("session_snapshot", "session_model_snapshot"):
                previous_total = token_total(snapshots.get(key, {}))
                current_total = token_total(a)
                if previous_total is not None and current_total is not None and current_total < previous_total:
                    regressed_keys.add(key)
                snapshots[key] = {**a, "session_uid": e["session_uid"], "event_uid": e["event_uid"]}
            elif a.get("reported") is not None:
                legacy[e["session_uid"]] = {"event_uid": e["event_uid"], "reported": a["reported"],
                                            "coverage": "unknown", "usage_scope": "unknown"}
    # Cross-scope accumulation is intentionally conservative. Fully covered self
    # calls win; a root_tree snapshot can supply a root total when no time/scene/
    # model subdivision was requested. Never add the two representations.
    roots = {s["session_uid"]: s.get("root_uid") or s["session_uid"] for s in sessions}
    snapshot_totals = []
    unbounded = scope.from_ts is None and scope.until_ts is None and scope.scene is None and scope.model_ids is None and scope.effort_raw is None
    bounded_or_excluded = bool(scope.excluded_session_uids) or not scope.include_children
    for key, a in snapshots.items():
        value = token_total(a)
        if key not in regressed_keys and value is not None and a.get("coverage") in ("self", "root_tree"):
            snapshot_totals.append({"snapshot_key": a["snapshot_key"], "session_uid": a["session_uid"],
                                    "coverage": a["coverage"], "total_tokens": value,
                                    "event_uid": a["event_uid"]})
    known_calls = [c for c in valid if c.get("coverage") == "self" and token_total(c) is not None]
    full_requests = (records_complete and not prepared["invalid_request_rows"]
                     and not prepared["conflicting_request_ids"])
    known_empty = model_calls == [] and full_requests and not snapshots and not legacy
    full_calls = (bool(valid) or known_empty) and full_requests and len(known_calls) == len(valid)
    total, basis = (sum(token_total(c) for c in valid), "call_delta") if full_calls else (None, None)
    # One tree snapshot is sufficient only if it exactly covers the selected tree.
    if unbounded and not bounded_or_excluded and len(snapshot_totals) == 1:
        a = snapshot_totals[0]
        selected_roots = set(roots.values())
        covered = (a["coverage"] == "root_tree" and selected_roots == {a["session_uid"]}) or (
            a["coverage"] == "self" and set(roots) == {a["session_uid"]})
        if covered:
            if a["coverage"] == "root_tree" or not full_calls:
                total, basis = a["total_tokens"], "cumulative_snapshot"
    # One unknown row no longer erases the scope total (audit B13): the known rows are summed
    # as a lower bound, and what is missing is counted and named instead.
    unknown_rows = {"invalid_request_rows": prepared["invalid_request_rows"],
                    "conflicting_request_ids": len(prepared["conflicting_request_ids"]),
                    "token_unknown_calls": len(valid) - len(known_calls),
                    "records_incomplete": not records_complete}
    if total is None and known_calls:
        total, basis = sum(token_total(c) for c in known_calls), "call_delta_known_rows"
    complete = basis in ("call_delta", "cumulative_snapshot")
    # model_call.cache_write_1h_tokens (migration 014) is the 1-hour-TTL part of cache_write;
    # NULL means "not reported", so the subtotal covers reporting rows only.
    write_1h = [c["cache_write_1h_tokens"] for c in valid
                if c.get("coverage") == "self" and token_number(c.get("cache_write_1h_tokens"))]
    costs = [c["cost_usd"] for c in valid if isinstance(c.get("cost_usd"), (int, float))
             and not isinstance(c["cost_usd"], bool) and math.isfinite(c["cost_usd"]) and c["cost_usd"] >= 0
             and c.get("cost_source") and (c["cost_source"] not in ("price_table", "estimate") or c.get("price_table_version"))]
    latency = [c["latency_ms"] for c in valid if nonnegative_number(c.get("latency_ms"))]
    ttft = [c["ttft_ms"] for c in valid if nonnegative_number(c.get("ttft_ms"))]
    buckets = [normalize_token_buckets(c) for c in valid if c.get("coverage") == "self"]
    return {"status": "available" if full_calls else "partial" if valid or snapshots or legacy else "unavailable",
            "request_count": len(valid) if valid or (model_calls == [] and records_complete) else None,
            **{k: v for k, v in prepared.items() if k != "requests"},
            "total_tokens": total, "total_basis": basis, "total_complete": complete if total is not None else None,
            "total_unknown": unknown_rows,
            "total_note": None if total is None or complete else
            "已知逐次请求之和（下限）；无效、冲突或缺 token 的行未计入，见 total_unknown",
            "known_call_tokens": sum(token_total(c) for c in known_calls) if known_calls or known_empty else None,
            "token_complete_call_n": len(known_calls), "token_unknown_call_n": len(valid) - len(known_calls),
            "token_buckets": {k: sum(c[k] for c in buckets) if (buckets or known_empty) and all(c[k] is not None for c in buckets) else None for k in TOKEN_BUCKETS},
            "token_semantics": {"input_tokens": "uncached", "cache": "disjoint_read_and_write",
                                "reasoning_tokens": "already_in_output_not_added"},
            "token_bucket_basis": "call_delta_known_rows",
            "cache_write_1h_tokens": sum(write_1h) if write_1h else None,
            "cache_write_1h_reported_n": len(write_1h),
            "service_tiers": dict(Counter(c.get("service_tier") or "unreported" for c in valid))
            if valid else None,
            "cost_usd": sum(costs) if valid and full_requests and len(costs) == len(valid) else None,
            "known_cost_usd": sum(costs) if costs else None,  # subtotal of priced rows
            "cost_effective_n": len(costs), "cost_unknown_n": len(valid) - len(costs),
            "cost_sources": sorted({c["cost_source"] for c in valid if c.get("cost_source")}),
            "price_table_versions": sorted({c["price_table_version"] for c in valid if c.get("price_table_version")}),
            "median_latency_ms": median(latency) if latency else None, "latency_effective_n": len(latency),
            "model_latency_sum_ms": sum(latency) if latency else None,
            "p90_model_latency_ms": quantile(latency, .9), "p99_model_latency_ms": quantile(latency, .99),
            "median_ttft_ms": median(ttft) if ttft else None, "ttft_effective_n": len(ttft),
            "models": dict(Counter(c.get("model_id") or "unknown" for c in valid)) if model_calls is not None else None,
            "cumulative_snapshots": snapshot_totals or None, "legacy_latest_reports": list(legacy.values()) or None,
            "cumulative_regressed_keys": sorted({key[1] for key in regressed_keys}),
            "request_evidence": [{"session_uid": c["session_uid"], "call_uid": c["call_uid"]} for c in valid],
            "cumulative_note": "快照不按日期分摊、不推算请求、不与逐次值相加；旧报告不提供规范总量"}
