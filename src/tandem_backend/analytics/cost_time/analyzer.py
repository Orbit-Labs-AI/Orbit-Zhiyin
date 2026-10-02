"""Resource measurements; observed time is never human work time."""

import math
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from zoneinfo import ZoneInfo

from ..common import human


def activity(sessions, events, calls, model_calls, main_ids, scope):
    zone = ZoneInfo(scope.display_timezone)
    def buckets(records):
        day, hour, weekday, unknown = Counter(), Counter(), Counter(), 0
        for ts in records:
            if ts is None:
                unknown += 1
                continue
            if not scope.contains(ts):
                continue
            try:
                dt = datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone(zone)
            except (ValueError, OverflowError, OSError):
                unknown += 1
                continue
            day[dt.date().isoformat()] += 1
            hour[str(dt.hour)] += 1
            weekday[str(dt.isoweekday())] += 1
        return {"by_day": dict(sorted(day.items())), "by_hour": dict(sorted(hour.items(), key=lambda x: int(x[0]))),
                "weekday_distribution": dict(sorted(weekday.items())), "active_days": len(day),
                "effective_n": sum(day.values()), "time_unknown_n": unknown}
    human_rows = [e for e in events if human(e, main_ids)]
    starts = []
    for s in sessions:
        if s["session_uid"] in main_ids:
            times = [e["ts"] for e in events if e["session_uid"] == s["session_uid"] and e.get("ts") is not None]
            starts.append(s.get("started_at") if s.get("started_at") is not None else min(times, default=None))
    hs = buckets([e.get("ts") for e in human_rows])
    return {"time_basis": "reported log timestamps; not continuous work", "sessions": buckets(starts),
            "human_messages": hs, "tool_calls": None if calls is None else buckets([c.get("started_at") for c in calls]),
            "model_requests": None if model_calls is None else buckets([c.get("ts") for c in model_calls]),
            "active_days": hs["active_days"], "hour_distribution": hs["by_hour"],
            "weekday_distribution": hs["weekday_distribution"]}


TOKEN_BUCKETS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def token_total(row):
    values = [row.get(k) for k in TOKEN_BUCKETS]
    if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values):
        return sum(values)
    return None


def usage(model_calls, events, sessions, scope, records_complete=True):
    valid = [c for c in model_calls or [] if c.get("usage_scope") == "call"
             and c.get("measurement") == "delta" and c.get("call_uid") and c.get("boundary_reliable") is True]
    # Stable canonical call IDs prevent mirrored records from becoming new requests.
    valid = list({c["call_uid"]: c for c in valid}.values())
    snapshots, legacy, regressed_keys = {}, {}, set()
    for e in sorted(events, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        if e["kind"] != "model.usage":
            continue
        a = e.get("attrs", {})
        if a.get("measurement") == "cumulative":
            key = a.get("snapshot_key")
            if key and a.get("usage_scope") in ("session_snapshot", "session_model_snapshot"):
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
    for a in snapshots.values():
        value = token_total(a)
        if a["snapshot_key"] not in regressed_keys and value is not None and a.get("coverage") in ("self", "root_tree"):
            snapshot_totals.append({"snapshot_key": a["snapshot_key"], "session_uid": a["session_uid"],
                                    "coverage": a["coverage"], "total_tokens": value,
                                    "event_uid": a["event_uid"]})
    known_calls = [c for c in valid if c.get("coverage") == "self" and token_total(c) is not None]
    full_calls = bool(valid) and records_complete and len(known_calls) == len(valid) == len(model_calls or [])
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
    costs = [c["cost_usd"] for c in valid if isinstance(c.get("cost_usd"), (int, float))
             and not isinstance(c["cost_usd"], bool) and math.isfinite(c["cost_usd"]) and c["cost_usd"] >= 0
             and c.get("cost_source") and (c["cost_source"] not in ("price_table", "estimate") or c.get("price_table_version"))]
    latency = [c["latency_ms"] for c in valid if c.get("latency_ms") is not None and c["latency_ms"] >= 0]
    ttft = [c["ttft_ms"] for c in valid if c.get("ttft_ms") is not None and c["ttft_ms"] >= 0]
    return {"status": "available" if full_calls else "partial" if valid or snapshots or legacy else "unavailable",
            "request_count": len(valid) if valid or (model_calls == [] and records_complete) else None,
            "invalid_request_rows": len(model_calls or []) - len(valid),
            "total_tokens": total, "total_basis": basis,
            "known_call_tokens": sum(token_total(c) for c in known_calls) if known_calls else None,
            "token_complete_call_n": len(known_calls), "token_unknown_call_n": len(valid) - len(known_calls),
            "token_buckets": {k: sum(c[k] for c in valid) if valid and all(c.get(k) is not None for c in valid) else None for k in TOKEN_BUCKETS},
            "token_bucket_basis": "call_delta_known_rows",
            "cost_usd": sum(costs) if valid and records_complete and len(costs) == len(valid) == len(model_calls or []) else None,
            "cost_effective_n": len(costs), "cost_unknown_n": len(valid) - len(costs),
            "cost_sources": sorted({c["cost_source"] for c in valid if c.get("cost_source")}),
            "price_table_versions": sorted({c["price_table_version"] for c in valid if c.get("price_table_version")}),
            "median_latency_ms": median(latency) if latency else None, "latency_effective_n": len(latency),
            "median_ttft_ms": median(ttft) if ttft else None, "ttft_effective_n": len(ttft),
            "models": dict(Counter(c.get("model_id") or "unknown" for c in valid)) if model_calls is not None else None,
            "cumulative_snapshots": snapshot_totals or None, "legacy_latest_reports": list(legacy.values()) or None,
            "cumulative_regressed_keys": sorted(regressed_keys),
            "cumulative_note": "快照不按日期分摊、不推算请求、不与逐次值相加；旧报告不提供规范总量"}
