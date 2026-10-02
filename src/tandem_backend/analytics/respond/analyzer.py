"""Recorded agent execution, protocol outcomes and execution relations."""

import math
from collections import Counter, defaultdict

from ...analysis import union_duration
from ..common import human, quantile, ratio


def tool_summary(calls, dataset_status="available"):
    if calls is None:
        return {"status": "unavailable", "totals": None, "by_tool": None,
                "effective_n": 0, "unknown_n": None}
    def aggregate(items):
        statuses = Counter()
        durations, intervals = [], []
        sources, qualities = Counter(), Counter()
        for c in items:
            status = c.get("status")
            # Do not let outer success erase a known failing/unknown inner result.
            if c.get("failed_command_results", 0):
                status = "failed"
            elif c.get("unknown_return_values", 0) and status in ("success", "completed"):
                status = None
            if status == "completed":
                status = "success"
            statuses[status if status in ("success", "failed", "rejected", "interrupted", "running") else "unknown"] += 1
            duration = c.get("duration_ms")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0:
                durations.append(duration)
                sources[c.get("duration_source") or "unknown"] += 1
                qualities[c.get("duration_quality") or "unknown"] += 1
            a, b = c.get("started_at"), c.get("ended_at")
            reliable = c.get("interval_reliable", c.get("duration_source") == "native_bounds")
            if reliable and a is not None and b is not None and b >= a:
                intervals.append((a, b))
        out = {"call_count": len(items), "paired_result_count": sum(bool(c.get("result_event_uid")) for c in items),
               "unpaired_count": sum(not c.get("result_event_uid") for c in items),
               "known_success_count": statuses["success"], "known_failure_count": statuses["failed"],
               **{k + "_count": statuses[k] for k in ("rejected", "interrupted", "running")},
               "unknown_status_count": statuses["unknown"],
               "eligible_status_count": statuses["success"] + statuses["failed"],
               "success_rate": ratio(statuses["success"], statuses["success"] + statuses["failed"]),
               "failure_rate": ratio(statuses["failed"], statuses["success"] + statuses["failed"]),
               "median_duration_ms": quantile(durations, .5), "p25_duration_ms": quantile(durations, .25),
               "p75_duration_ms": quantile(durations, .75), "p90_duration_ms": quantile(durations, .9),
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
            "unknown_n": sum(c.get("status") is None for c in calls),
            "by_tool": [{"name_raw": name, "kind": kind, **aggregate(v)}
                        for (name, kind), v in sorted(groups.items(), key=lambda p: (-len(p[1]), str(p[0])))]}


STATES = {"message.assistant": "ASSISTANT_MESSAGE", "tool.call": "TOOL_CALL",
          "tool.result": "TOOL_RESULT", "error": "ERROR", "permission.request": "PERMISSION",
          "branch": "BRANCH", "context.compaction": "COMPACTION", "subagent.spawn": "SUBAGENT_SPAWN",
          "subagent.result": "SUBAGENT_RESULT", "turn.interrupted": "INTERRUPTION"}


def workflow(events, calls, main_ids, supported_kinds=None):
    sequences, transitions = defaultdict(list), Counter()
    for e in sorted(events, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        state = "HUMAN_MESSAGE" if human(e, main_ids) else STATES.get(e["kind"])
        if state:
            sequences[e["session_uid"]].append((state, e["event_uid"]))
    runs, repeated = 0, 0
    for seq in sequences.values():
        edges = [(a[0], b[0]) for a, b in zip(seq, seq[1:], strict=False)]
        transitions.update(edges)
        seen, prev, run = set(), None, 0
        for edge in edges:
            repeated += edge in seen
            seen.add(edge)
            run = run + 1 if edge == prev else 1
            runs, prev = max(runs, run), edge
    totals = Counter()
    for (a, _), n in transitions.items():
        totals[a] += n
    count = sum(transitions.values())
    counts = {}
    for name, kind in (("error_count", "error"), ("branch_count", "branch"),
                       ("compaction_count", "context.compaction"), ("permission_request_count", "permission.request"),
                       ("subagent_spawn_count", "subagent.spawn"), ("interruption_count", "turn.interrupted")):
        counts[name] = sum(e["kind"] == kind for e in events) if supported_kinds is None or kind in supported_kinds else None
    counts["rollback_rewind_count"] = (sum(e["kind"] == "branch" and e.get("attrs", {}).get("action") in ("rollback", "rewind") for e in events)
                                       if supported_kinds is None or "branch" in supported_kinds else None)
    consecutive, same, max_failures, digest_eligible = 0, 0, 0, 0
    by_session = defaultdict(list)
    for c in calls or []:
        by_session[c["session_uid"]].append(c)
    for group in by_session.values():
        previous, run = None, 0
        for c in sorted(group, key=lambda c: (c.get("seq", 0), c["call_uid"])):
            failed = c.get("status") == "failed" or bool(c.get("failed_command_results"))
            run = run + 1 if failed else 0
            max_failures = max(max_failures, run)
            if run > 1:
                consecutive += 1
                eligible = (bool(c.get("argument_digest")) and bool(previous.get("argument_digest"))
                            and bool(c.get("status_scope")) and c.get("status_scope") != "unknown"
                            and c.get("status_scope") == previous.get("status_scope"))
                digest_eligible += eligible
                same += bool(eligible and c["argument_digest"] == previous["argument_digest"]
                             and (c.get("name_raw"), c.get("kind")) == (previous.get("name_raw"), previous.get("kind")))
            previous = c
    return {**counts, "transition_count": count, "repeated_transition_count": repeated,
            "repeated_transition_rate": ratio(repeated, count), "max_repeated_transition_run": runs,
            "transitions": [{"from": a, "to": b, "count": n, "probability": n / totals[a]}
                            for (a, b), n in sorted(transitions.items())],
            "consecutive_failed_calls": consecutive if calls is not None else None,
            "max_consecutive_failure_run": max_failures if calls is not None else None,
            "confirmed_same_argument_failed_retries": same if digest_eligible else None,
            "retry_eligible_pairs": digest_eligible, "sequences": dict(sequences)}
