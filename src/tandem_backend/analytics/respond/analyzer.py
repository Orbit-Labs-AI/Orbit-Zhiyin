"""Recorded agent execution, protocol outcomes and execution relations."""

import math
from collections import Counter, defaultdict
from copy import deepcopy

from ...analysis import union_duration
from ..common import human, quantile, ratio, task_uid, timestamp


def result_status(call):
    """Only protocol evidence; a wrapper's success never erases inner uncertainty."""
    if call.get("pairing_status") == "conflict":
        return "unknown"
    status = call.get("status")
    if call.get("failed_command_results"):
        return "failed"
    if call.get("unknown_return_values") and status in ("success", "completed"):
        return "unknown"
    if status == "completed":
        return "success"
    return status if status in ("success", "failed", "rejected", "interrupted", "running") else "unknown"


def tool_summary(calls, dataset_status="available"):
    if calls is None:
        return {"status": "unavailable", "totals": None, "by_tool": None,
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
            "unknown_n": sum(result_status(c) == "unknown" for c in calls),
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


RESULT_FIELDS = ("status", "status_scope", "exit_code", "error_class", "failure_reason",
                 "duration_ms", "duration_source", "duration_quality", "ended_at",
                 "known_command_results", "failed_command_results", "unknown_return_values",
                 "validation_result", "validation_report")


def pair_tool_calls(events):
    """Pair L2 records by source/session/native call ID, never by proximity.

    Multiple distinct calls or returns for an ID remain conflicts; exact mirrored
    event IDs are deduplicated. A return preceding its call cannot close it.
    """
    grouped, seen, duplicates = defaultdict(lambda: {"calls": [], "results": []}), {}, []
    event_conflicts = set()
    for e in sorted(events, key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        if e["kind"] not in ("tool.call", "tool.result"):
            continue
        if e.get("attrs", {}).get("replayed_from") or e.get("attrs", {}).get("duplicate_of"):
            continue
        identity = (e.get("source_id"), e["session_uid"], e["event_uid"])
        if identity in seen:
            if e != seen[identity]:
                event_conflicts.add(identity)
            duplicates.append(e["event_uid"])
            continue
        seen[identity] = e
        native = e.get("call_id") or e.get("attrs", {}).get("call_id")
        key = (e.get("source_id"), e["session_uid"], native or ("missing", e["event_uid"]))
        grouped[key]["calls" if e["kind"] == "tool.call" else "results"].append(e)
    calls, orphans, conflicts = [], [], []
    for key, group in grouped.items():
        starts, ends = group["calls"], group["results"]
        conflict = (len(starts) > 1 or len(ends) > 1
                    or any((e.get("source_id"), e["session_uid"], e["event_uid"]) in event_conflicts
                           for e in starts + ends))
        if conflict:
            conflicts.append({"session_uid": key[1], "source_id": key[0],
                              "event_uids": [e["event_uid"] for e in starts + ends]})
        paired = bool(len(starts) == len(ends) == 1 and not conflict and ends[0]["seq"] > starts[0]["seq"])
        if not paired:
            orphans.extend(e["event_uid"] for e in ends)
        for e in starts:
            a = e.get("attrs", {})
            row = {"call_uid": e["event_uid"], "session_uid": e["session_uid"], "source_id": key[0],
                   "turn_uid": e.get("turn_uid"), "task_uid": task_uid(e), "seq": e["seq"],
                   "call_event_uid": e["event_uid"], "result_event_uid": None,
                   "name_raw": a.get("name_raw") or a.get("name"), "kind": a.get("category", "unknown"),
                   "status": None, "status_scope": None, "started_at": e.get("ts"), "ended_at": None,
                   "interval_reliable": False, "pairing_status": "conflict" if conflict else "unpaired",
                   **{k: deepcopy(a[k]) for k in ("argument_digest", "argument_digest_kind", "command_head",
                       "validation", "retry_of_call_uid", "project_id") if k in a}}
            if paired:
                r = ends[0]
                ra = r.get("attrs", {})
                row.update({k: deepcopy(ra.get(k)) for k in RESULT_FIELDS})
                row.update(result_event_uid=r["event_uid"], result_available_at=r.get("ts"), pairing_status="paired")
                if row["status"] is None and isinstance(ra.get("exit_code"), int) and not isinstance(ra["exit_code"], bool):
                    row["status"] = "success" if ra["exit_code"] == 0 else "failed"
                # Native bounds must be explicit; log timestamps are not execution endpoints.
                if a.get("interval_reliable") is True and ra.get("interval_reliable") is True:
                    row.update(started_at=a.get("started_at"), ended_at=ra.get("ended_at"),
                               interval_reliable=True, duration_source="native_bounds", duration_quality="reported")
            calls.append(row)
    return {"calls": sorted(calls, key=lambda c: (c["session_uid"], c["seq"], c["call_uid"])),
            "orphan_result_event_uids": orphans, "duplicate_event_uids": duplicates, "pairing_conflicts": conflicts}


def normalize_tool_calls(calls):
    """One logical L3 call per identity; conflicting mirrors cannot claim success."""
    rows, duplicates, conflicts = {}, 0, []
    for original in calls or []:
        key = (original["session_uid"], original["call_uid"])
        c = deepcopy(original)
        if key in rows:
            duplicates += 1
            if c != rows[key]:
                conflicts.append({"session_uid": key[0], "call_uid": key[1], "reason": "conflicting_call_rows"})
                rows[key].update({k: None for k in RESULT_FIELDS})
                rows[key].update(pairing_status="conflict", result_event_uid=None, interval_reliable=False)
        else:
            rows[key] = c
    return {"calls": sorted(rows.values(), key=lambda c: (c["session_uid"], c.get("seq", 0), c["call_uid"])),
            "duplicate_call_rows": duplicates, "call_conflicts": conflicts}


def analyze_execution_sequence(calls):
    """Stricter retry links alongside the compatible v1 workflow counters."""
    groups, retries, failures = defaultdict(list), [], []
    for c in calls or []:
        groups[c["session_uid"]].append(c)
        status = result_status(c)
        if status in ("failed", "rejected", "interrupted"):
            code = c.get("error_class") or c.get("failure_reason")
            if not code and status in ("rejected", "interrupted"):
                code = status
            failures.append({"call_uid": c["call_uid"], "session_uid": c["session_uid"],
                             "failure_reason": code, "exit_code": c.get("exit_code"),
                             "status_scope": c.get("status_scope"), "source": "explicit_protocol",
                             "evidence_event_uid": c.get("result_event_uid")})
    for group in groups.values():
        ordered = sorted(group, key=lambda c: (c.get("seq", 0), c["call_uid"]))
        prior, previous = {}, None
        for c in ordered:
            explicit = c.get("retry_of_call_uid")
            p = prior.get(explicit) if explicit else previous
            if p and result_status(p) == "failed" and (c.get("name_raw"), c.get("kind")) == (p.get("name_raw"), p.get("kind")):
                task_same = bool(c.get("task_uid") and c.get("task_uid") == p.get("task_uid"))
                task_conflict = c.get("task_uid") and p.get("task_uid") and not task_same
                scope_same = bool(c.get("status_scope") not in (None, "unknown")
                                  and c.get("status_scope") == p.get("status_scope"))
                digest_known = bool(c.get("argument_digest") and p.get("argument_digest")
                                    and c.get("argument_digest_kind") not in (None, "unknown")
                                    and c.get("argument_digest_kind") == p.get("argument_digest_kind"))
                same_args = c.get("argument_digest") == p.get("argument_digest") if digest_known else None
                if not task_conflict and (explicit or same_args is not False):
                    confirmed = task_same and scope_same and (bool(explicit) or same_args is True)
                    retries.append({"session_uid": c["session_uid"], "from_call_uid": p["call_uid"],
                                    "to_call_uid": c["call_uid"], "state": "confirmed" if confirmed else "candidate",
                                    "basis": "explicit_link" if explicit else "failed_same_tool_repeat",
                                    "same_arguments": same_args, "status_scope": c.get("status_scope"),
                                    "task_uid": c.get("task_uid"),
                                    "missing": ([] if task_same else ["task_identity"])
                                        + ([] if scope_same else ["status_scope"])
                                        + ([] if explicit or digest_known else ["argument_digest_identity"])})
            prior[c["call_uid"]], previous = c, c
    return {"retry_links": retries if calls is not None else None,
            "failure_reasons": failures if calls is not None else None,
            "failure_reason_unknown_n": sum(r["failure_reason"] is None for r in failures) if calls is not None else None}


def execution_intervals(calls):
    intervals, missing = [], []
    for c in calls or []:
        a, b = c.get("started_at"), c.get("ended_at")
        reliable = c.get("interval_reliable", c.get("duration_source") == "native_bounds")
        identity = {"session_uid": c["session_uid"], "call_uid": c["call_uid"]}
        if reliable and timestamp(a) and timestamp(b) and b >= a and c.get("pairing_status") != "conflict":
            intervals.append({**identity, "started_at": a, "ended_at": b,
                              "duration_ms": b - a, "source": "native_bounds", "quality": "reliable"})
        else:
            missing.append(identity)
    # Sweep half-open native intervals; adjacent endpoints are not parallel.
    endpoints = defaultdict(list)
    for i in intervals:
        key = (i["session_uid"], i["call_uid"])
        if i["started_at"] < i["ended_at"]:
            endpoints[i["started_at"]].append((1, key))
            endpoints[i["ended_at"]].append((-1, key))
    active, previous, overlaps = set(), None, []
    for t, changes in sorted(endpoints.items()):
        if previous is not None and t > previous and len(active) > 1:
            overlaps.append({"started_at": previous, "ended_at": t, "concurrency": len(active),
                             "calls": [{"session_uid": sid, "call_uid": uid} for sid, uid in sorted(active)]})
        for direction, key in sorted(changes):
            active.add(key) if direction == 1 else active.discard(key)
        previous = t
    return {"execution_intervals": intervals if calls is not None else None,
            "parallel_intervals": overlaps if calls is not None else None,
            "interval_unknown_calls": missing if calls is not None else None}


def build_execution_relations(events, sessions):
    relations, unresolved, forks = {}, [], []
    for s in sessions:
        if s.get("forked_from"):
            forks.append({"session_uid": s["session_uid"], "forked_from": s["forked_from"]})
        if s.get("kind") in ("subagent", "workflow_agent") and s.get("parent_uid"):
            relations[(s["parent_uid"], s["session_uid"])] = {
                "parent_session_uid": s["parent_uid"], "child_session_uid": s["session_uid"],
                "source": "explicit_parent_uid", "spawn_event_uids": [], "join_event_uids": []}
    for e in events or []:
        if e["kind"] not in ("subagent.spawn", "subagent.result"):
            continue
        a = e.get("attrs", {})
        child, parent = a.get("child_session_uid"), a.get("parent_session_uid", e["session_uid"])
        if not child or child == parent:
            unresolved.append(e["event_uid"])
            continue
        relation = relations.setdefault((parent, child), {"parent_session_uid": parent, "child_session_uid": child,
             "source": "explicit_event", "spawn_event_uids": [], "join_event_uids": []})
        relation["spawn_event_uids" if e["kind"] == "subagent.spawn" else "join_event_uids"].append(e["event_uid"])
    return {"subagent_relations": list(relations.values()), "unresolved_subagent_events": unresolved,
            "fork_relations": forks,
            "rollback_restart_events": [{"event_uid": e["event_uid"], "session_uid": e["session_uid"],
                "kind": e["kind"], "action": e.get("attrs", {}).get("action")} for e in events or []
                if e["kind"] == "context.restart" or (e["kind"] == "branch"
                    and e.get("attrs", {}).get("action") in ("rollback", "rewind"))]}


def analyze_respond(events, calls, sessions, main_ids, dataset_status="available", supported_kinds=None):
    paired = pair_tool_calls(events or [])
    normalized = normalize_tool_calls(calls)
    effective = normalized["calls"] if calls is not None else paired["calls"] if paired["calls"] else None
    status = dataset_status if calls is not None else "partial" if effective else "unavailable"
    sequence = [] if effective is not None else None
    for c in effective or []:
        sequence.append({**c, "tool_result_status": result_status(c), "raw_status": c.get("status")})
    turn_ids = {(e["session_uid"], e["turn_uid"]) for e in events or [] if e.get("turn_uid")}
    return {"status": status, "grain": "tool_call", "tool_sequence": sequence,
            "call_source": "L3" if calls is not None else "paired_L2",
            "turn_count": len(turn_ids) if turn_ids else 0 if events == [] and dataset_status == "available" else None,
            "turn_boundary_unknown_n": sum(not e.get("turn_uid") for e in events) if events is not None else None,
            "tools": tool_summary(effective, status),
            "workflow": workflow(events, effective, main_ids, supported_kinds) if events is not None else None,
            **analyze_execution_sequence(effective), **execution_intervals(effective),
            **build_execution_relations(events, sessions),
            "pairing": {**{k: v for k, v in paired.items() if k != "calls"},
                        **{k: v for k, v in normalized.items() if k != "calls"}}}
