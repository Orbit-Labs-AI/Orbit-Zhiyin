"""Tool-level counts, protocol success rates and duration coverage."""

import math
from collections import Counter, defaultdict

from ...profiling.analysis import union_duration
from ..common import MIN_STATUS_COVERAGE, covered_ratio, quantile, status_coverage, timestamp
from .rules import result_status


def tool_summary(calls, dataset_status="available"):
    if calls is None:
        return {"status": "excluded" if dataset_status == "excluded" else "unavailable", "totals": None, "by_tool": None,
                "effective_n": 0, "unknown_n": None}
    def aggregate(items):
        statuses = Counter()
        durations, intervals = [], []
        sources, qualities = Counter(), Counter()
        for c in items:
            statuses[result_status(c)] += 1
            duration = c.get("duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0:
                durations.append(duration)
                sources[c.get("duration_source") or "unknown"] += 1
                qualities[c.get("duration_quality") or "unknown"] += 1
            a, b = c.get("started_at"), c.get("ended_at")
            reliable = c.get("interval_reliable", c.get("duration_source") == "native_bounds")
            if reliable and timestamp(a) and timestamp(b) and b >= a:
                intervals.append((a, b))
        # One O(n log n) sort; quantile() re-sorting an ordered list is linear.
        ordered = sorted(durations)
        known = statuses["success"] + statuses["failed"]
        out = {"call_count": len(items), "paired_result_count": sum(bool(c.get("result_event_uid")) for c in items),
               "unpaired_count": sum(not c.get("result_event_uid") for c in items),
               "known_success_count": statuses["success"], "known_failure_count": statuses["failed"],
               **{k + "_count": statuses[k] for k in ("rejected", "interrupted", "running")},
               "unknown_status_count": statuses["unknown"],
               "eligible_status_count": known,
               "status_coverage": status_coverage(known, statuses["unknown"]),
               "success_rate": covered_ratio(statuses["success"], known, statuses["unknown"]),
               "failure_rate": covered_ratio(statuses["failed"], known, statuses["unknown"]),
               "rate_reason": None if covered_ratio(1, known, statuses["unknown"]) is not None else
                              "no_known_status" if not known else "status_coverage_below_min",
               "min_status_coverage": MIN_STATUS_COVERAGE,
               "median_duration_ms": quantile(ordered, .5), "p25_duration_ms": quantile(ordered, .25),
               "p75_duration_ms": quantile(ordered, .75), "p90_duration_ms": quantile(ordered, .9),
               "duration_sum_ms": sum(durations) if durations else None,
               "reliable_interval_union_ms": union_duration(intervals) if intervals else None,
               "duration_source": dict(sources), "duration_quality": dict(qualities),
               "duration_effective_n": len(durations), "duration_unknown_n": len(items) - len(durations),
               "reliable_interval_n": len(intervals), "interval_unavailable_n": len(items) - len(intervals)}
        if not items and dataset_status != "available":
            for k in out:
                if k.endswith("_count"):
                    out[k] = None
        return out
    groups = defaultdict(list)
    for c in calls:
        groups[(c.get("name_raw"), c.get("kind"))].append(c)
    return {"status": dataset_status, "totals": aggregate(calls), "effective_n": len(calls),
            "unknown_n": sum(result_status(c) == "unknown" for c in calls),
            "by_tool": [{"name_raw": name, "kind": kind, **aggregate(v)}
                        for (name, kind), v in sorted(groups.items(), key=lambda p: (-len(p[1]), str(p[0])))]}
