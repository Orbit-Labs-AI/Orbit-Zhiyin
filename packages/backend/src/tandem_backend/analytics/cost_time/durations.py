"""Native execution durations, observed spans and separately reported estimates."""

from collections import defaultdict

from ...profiling.analysis import union_duration
from ..common import nonnegative_number, quantile, timestamp
from ..respond import execution_intervals


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
