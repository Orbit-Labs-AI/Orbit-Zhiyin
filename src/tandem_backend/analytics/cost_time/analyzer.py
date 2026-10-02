"""Resource measurements; observed time is never human work time."""

import math
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from zoneinfo import ZoneInfo

from ...analysis import union_duration
from ..common import human, nonnegative_number, quantile, timestamp
from ..respond import execution_intervals


def activity(sessions, events, calls, model_calls, main_ids, scope):
    zone = ZoneInfo(scope.display_timezone)
    def buckets(records):
        day, hour, weekday, unknown = Counter(), Counter(), Counter(), 0
        for ts in records:
            if not timestamp(ts):
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
            starts.append(s.get("started_at"))
    hs = buckets([e.get("ts") for e in human_rows])
    return {"time_basis": "reported log timestamps; not continuous work", "sessions": buckets(starts),
            "human_messages": hs, "tool_calls": None if calls is None else buckets([c.get("started_at") for c in calls]),
            "model_requests": None if model_calls is None else buckets([c.get("ts") for c in prepare_requests(model_calls)["requests"]]),
            "active_days": hs["active_days"], "hour_distribution": hs["by_hour"],
            "weekday_distribution": hs["weekday_distribution"]}


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
    costs = [c["cost_usd"] for c in valid if isinstance(c.get("cost_usd"), (int, float))
             and not isinstance(c["cost_usd"], bool) and math.isfinite(c["cost_usd"]) and c["cost_usd"] >= 0
             and c.get("cost_source") and (c["cost_source"] not in ("price_table", "estimate") or c.get("price_table_version"))]
    latency = [c["latency_ms"] for c in valid if nonnegative_number(c.get("latency_ms"))]
    ttft = [c["ttft_ms"] for c in valid if nonnegative_number(c.get("ttft_ms"))]
    buckets = [normalize_token_buckets(c) for c in valid if c.get("coverage") == "self"]
    return {"status": "available" if full_calls else "partial" if valid or snapshots or legacy else "unavailable",
            "request_count": len(valid) if valid or (model_calls == [] and records_complete) else None,
            **{k: v for k, v in prepared.items() if k != "requests"},
            "total_tokens": total, "total_basis": basis,
            "known_call_tokens": sum(token_total(c) for c in known_calls) if known_calls or known_empty else None,
            "token_complete_call_n": len(known_calls), "token_unknown_call_n": len(valid) - len(known_calls),
            "token_buckets": {k: sum(c[k] for c in buckets) if (buckets or known_empty) and all(c[k] is not None for c in buckets) else None for k in TOKEN_BUCKETS},
            "token_semantics": {"input_tokens": "uncached", "cache": "disjoint_read_and_write",
                                "reasoning_tokens": "already_in_output_not_added"},
            "token_bucket_basis": "call_delta_known_rows",
            "cost_usd": sum(costs) if valid and full_requests and len(costs) == len(valid) else None,
            "cost_effective_n": len(costs), "cost_unknown_n": len(valid) - len(costs),
            "cost_sources": sorted({c["cost_source"] for c in valid if c.get("cost_source")}),
            "price_table_versions": sorted({c["price_table_version"] for c in valid if c.get("price_table_version")}),
            "median_latency_ms": median(latency) if latency else None, "latency_effective_n": len(latency),
            "median_ttft_ms": median(ttft) if ttft else None, "ttft_effective_n": len(ttft),
            "models": dict(Counter(c.get("model_id") or "unknown" for c in valid)) if model_calls is not None else None,
            "cumulative_snapshots": snapshot_totals or None, "legacy_latest_reports": list(legacy.values()) or None,
            "cumulative_regressed_keys": sorted({key[1] for key in regressed_keys}),
            "request_evidence": [{"session_uid": c["session_uid"], "call_uid": c["call_uid"]} for c in valid],
            "cumulative_note": "快照不按日期分摊、不推算请求、不与逐次值相加；旧报告不提供规范总量"}


def summarize_durations(calls, events, intervals=None):
    """Keep reported/native execution, log-gap estimates and spans separate."""
    if intervals is None:
        intervals = execution_intervals(calls)["execution_intervals"]
    by_call = {(i["session_uid"], i["call_uid"]): i for i in intervals or []}
    rows, known, estimates = [], [], []
    for c in calls or []:
        native = by_call.get((c["session_uid"], c["call_uid"]))
        duration, estimate, source = None, None, None
        if native:
            duration, source = native["duration_ms"], "native_bounds"
        elif nonnegative_number(c.get("duration_ms")):
            if c.get("duration_source") in ("reported", "native_report") and c.get("duration_quality") != "estimated":
                duration, source = c["duration_ms"], c["duration_source"]
            elif c.get("duration_source") == "event_difference" or c.get("duration_quality") == "estimated":
                estimate, source = c["duration_ms"], "event_difference"
        if duration is not None:
            known.append(duration)
        if estimate is not None:
            estimates.append(estimate)
        rows.append({"session_uid": c["session_uid"], "call_uid": c["call_uid"],
                     "execution_duration_ms": duration, "estimated_log_gap_ms": estimate,
                     "started_at": native["started_at"] if native else None,
                     "ended_at": native["ended_at"] if native else None,
                     "source": source, "quality": "reliable" if duration is not None else "estimated" if estimate is not None else "unknown",
                     "evidence_event_uids": [v for v in (c.get("call_event_uid"), c.get("result_event_uid")) if v]})
    spans = []
    for sid in sorted({e["session_uid"] for e in events or []}):
        es = [e for e in events if e["session_uid"] == sid]
        timed = [e for e in es if timestamp(e.get("ts"))]
        times = [e["ts"] for e in timed]
        spans.append({"session_uid": sid, "first_observed_ts": min(times, default=None),
                      "last_observed_ts": max(times, default=None),
                      "observed_session_span_ms": max(times) - min(times) if times else None,
                      "effective_n": len(times), "unknown_n": len(es) - len(times),
                      "time_source": "event.ts", "time_quality": "observed_log_time",
                      "evidence_event_uids": [e["event_uid"] for e in timed]})
    return {"execution_durations": rows if calls is not None else None,
            "execution_duration_sum_ms": sum(known) if known else None,
            "median_execution_duration_ms": quantile(known, .5),
            "p90_execution_duration_ms": quantile(known, .9),
            "estimated_log_gap_sum_ms": sum(estimates) if estimates else None,
            "reliable_interval_union_ms": union_duration([(i["started_at"], i["ended_at"]) for i in intervals]) if intervals else None,
            "effective_n": len(known), "estimated_n": len(estimates),
            "unknown_n": len(calls) - len(known) if calls is not None else None,
            "interval_effective_n": len(intervals) if intervals is not None else 0,
            "session_spans": spans if events is not None else None,
            "meaning": "known execution subset; session spans and log gaps are not human work time"}


def analyze_cost_time(sessions, events, calls, model_calls, main_ids, scope, records_complete=True, intervals=None):
    return {"grain": "request/call/session", "display_timezone": scope.display_timezone,
            "usage": usage(model_calls, events or [], sessions, scope, records_complete),
            "durations": summarize_durations(calls, events, intervals),
            "activity_rhythm": activity(sessions, events or [], calls, model_calls, main_ids, scope) if events is not None else None,
            "deferred": ["actual_cost_analysis", "estimated_cost_analysis", "time_to_first_acceptance", "human_work_duration"]}
