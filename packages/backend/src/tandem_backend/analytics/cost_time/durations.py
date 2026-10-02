"""Wall spans, native execution, approval waits and log estimates remain separate."""

from collections import defaultdict

from ...profiling.analysis import union_duration
from ..common import nonnegative_number, quantile, timestamp
from ..respond import execution_intervals


def _distribution(rows, field):
    known = [r for r in rows if nonnegative_number(r.get(field))]
    values = [r[field] for r in known]
    total = sum(values) if values else None
    top = sorted(known, key=lambda r: (-r[field], r["session_uid"], r["call_uid"]))[:16]
    outliers = [r for r in known if r[field] > 3_600_000]
    return {"sum_ms": total, "effective_n": len(values), "unknown_n": len(rows) - len(values),
            "p50_ms": quantile(values, .5), "p90_ms": quantile(values, .9), "p99_ms": quantile(values, .99),
            "top_k": 16, "top_k_contribution": sum(r[field] for r in top) / total if total else None,
            "over_one_hour_n": len(outliers),
            "over_one_hour_contribution": sum(r[field] for r in outliers) / total if total else None,
            "top_calls": [{"session_uid": r["session_uid"], "call_uid": r["call_uid"],
                           "duration_ms": r[field], "evidence_event_uids": r["evidence_event_uids"]} for r in top]}


def summarize_durations(calls, events, intervals=None):
    if intervals is None:
        intervals = execution_intervals(calls)["execution_intervals"]
    by_call = {(i["session_uid"], i["call_uid"]): i for i in intervals or []}
    rows = []
    for c in calls or []:
        interval = by_call.get((c["session_uid"], c["call_uid"]))
        native = c.get("native_execution_ms")
        reported = c.get("duration_ms") if c.get("duration_source") in ("reported", "native_report") and c.get("duration_quality") != "estimated" else None
        # Canonical rows include native_execution_ms, even when it is NULL.
        # Legacy adapters can still supply an explicitly reported duration.
        if "native_execution_ms" not in c:
            native = reported
        native = native if nonnegative_number(native) else None
        wall = interval["duration_ms"] if interval else c.get("wall_elapsed_ms")
        wall = wall if nonnegative_number(wall) else None
        estimate = c.get("duration_ms") if c.get("duration_source") == "event_difference" or c.get("duration_quality") == "estimated" else None
        estimate = estimate if nonnegative_number(estimate) else None
        wait = c.get("approval_wait_ms")
        wait = wait if nonnegative_number(wait) else None
        rows.append({"session_uid": c["session_uid"], "call_uid": c["call_uid"],
                     "wall_elapsed_ms": wall, "native_execution_ms": native,
                     "approval_wait_ms": wait, "reported_tool_duration_ms": reported,
                     "execution_duration_ms": native, "estimated_log_gap_ms": estimate,
                     "started_at": interval["started_at"] if interval else None,
                     "ended_at": interval["ended_at"] if interval else None,
                     "source": "native_execution_report" if native is not None else
                               "native_bounds" if wall is not None else "event_difference" if estimate is not None else None,
                     "quality": "reliable" if native is not None else "wall_only" if wall is not None else
                                "estimated" if estimate is not None else "unknown",
                     "native_exceeds_wall": native > wall if native is not None and wall is not None else None,
                     "evidence_event_uids": [v for v in (c.get("call_event_uid"), c.get("result_event_uid")) if v]})
    spans = []
    by_session = defaultdict(list)
    for e in events or []:
        by_session[e["session_uid"]].append(e)
    for sid in sorted(by_session):
        es = by_session[sid]
        timed = [e for e in es if timestamp(e.get("ts"))]
        times = [e["ts"] for e in timed]
        spans.append({"session_uid": sid, "first_observed_ts": min(times, default=None),
                      "last_observed_ts": max(times, default=None),
                      "observed_session_span_ms": max(times) - min(times) if times else None,
                      "effective_n": len(times), "unknown_n": len(es) - len(times),
                      "time_source": "event.ts", "time_quality": "observed_log_time",
                      "evidence_event_uids": [e["event_uid"] for e in timed]})
    wall, native, waits = (_distribution(rows, name) for name in
                           ("wall_elapsed_ms", "native_execution_ms", "approval_wait_ms"))
    estimates = [r["estimated_log_gap_ms"] for r in rows if r["estimated_log_gap_ms"] is not None]
    interval_union = union_duration([(i["started_at"], i["ended_at"]) for i in intervals]) if intervals else None
    return {"execution_durations": rows if calls is not None else None,
            "wall_elapsed": wall, "native_execution": native, "approval_wait": waits,
            "wall_elapsed_sum_ms": wall["sum_ms"], "native_execution_sum_ms": native["sum_ms"],
            "approval_wait_sum_ms": waits["sum_ms"], "wall_interval_union_ms": interval_union,
            "execution_duration_sum_ms": native["sum_ms"],
            "median_execution_duration_ms": native["p50_ms"], "p90_execution_duration_ms": native["p90_ms"],
            "p99_execution_duration_ms": native["p99_ms"],
            "estimated_log_gap_sum_ms": sum(estimates) if estimates else None,
            "reliable_interval_union_ms": interval_union,
            "effective_n": native["effective_n"], "estimated_n": len(estimates),
            "unknown_n": len(calls) - native["effective_n"] if calls is not None else None,
            "wall_effective_n": wall["effective_n"],
            "interval_effective_n": len(intervals) if intervals is not None else 0,
            "native_wall_mismatch_n": sum(r["native_exceeds_wall"] is True for r in rows),
            "session_spans": spans if events is not None else None,
            "meaning": "wall span, reported native execution and approval waits are separate; none measure human work time",
            "compatibility": {"execution_duration_sum_ms": "native_execution_sum_ms",
                              "reliable_interval_union_ms": "wall_interval_union_ms"}}
