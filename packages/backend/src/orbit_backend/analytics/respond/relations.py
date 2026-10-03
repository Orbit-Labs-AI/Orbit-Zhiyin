"""Explicit subagent relations and reliable concurrent execution intervals."""

from collections import defaultdict

from ...models import stable_id
from ..common import nonnegative_number, timestamp


def execution_intervals(calls):
    intervals, missing = [], []
    for c in calls or []:
        a, b = c.get("started_at"), c.get("ended_at")
        reliable = c.get("interval_reliable", nonnegative_number(c.get("wall_elapsed_ms"))
                         or c.get("duration_source") == "native_bounds")
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
    children, unresolved, forks = {}, [], []
    def child_record(child):
        return children.setdefault(child, {"parents": defaultdict(set), "activities": [],
                                           "starts": [], "ends": []})
    for s in sessions:
        if s.get("forked_from"):
            forks.append({"session_uid": s["session_uid"], "forked_from": s["forked_from"]})
        if s.get("kind") in ("subagent", "workflow_agent"):
            record = child_record(s["session_uid"])
            if s.get("parent_uid") and s["parent_uid"] != s["session_uid"]:
                record["parents"][s["parent_uid"]].add("explicit_parent_uid")
    for e in events or []:
        if not e["kind"].startswith("subagent."):
            continue
        a = e.get("attrs", {})
        child = a.get("child_session_uid")
        if not child or child == e["session_uid"]:
            unresolved.append(e["event_uid"])
            continue
        record = child_record(child)
        record["activities"].append(e)
        parent = a.get("parent_session_uid")
        # Old mapper versions put the observer in parent_session_uid on all activity.
        # Only creation or a native parent field proves ownership independently.
        if e["kind"] == "subagent.spawn":
            parent = parent or e["session_uid"]
            source = "spawn_creator"
        elif a.get("parent_relation_source") == "native_parent":
            source = "native_parent"
        else:
            parent, source = None, None
        if parent and parent != child:
            record["parents"][parent].add(source)
        if e["kind"] in ("subagent.spawn", "subagent.result"):
            record["starts" if e["kind"] == "subagent.spawn" else "ends"].append(e)
    session_lookup = {s["session_uid"]: s for s in sessions}
    relations, runs, conflicts = [], [], []
    for child, record in sorted(children.items()):
        parents = sorted(record["parents"])
        parent = parents[0] if len(parents) == 1 else None
        evidence = sorted({e["event_uid"] for e in record["activities"]})
        sources = sorted(record["parents"][parent]) if parent else []
        source = "explicit_parent_uid" if "explicit_parent_uid" in sources else sources[0] if sources else "observed_child_identity"
        if len(parents) > 1:
            source = "conflicting_parent_evidence"
            conflicts.append({"child_session_uid": child, "parent_session_uids": parents,
                              "evidence_uids": evidence})
        if parent:
            relations.append({"parent_session_uid": parent, "child_session_uid": child, "source": source,
                              "spawn_event_uids": sorted({e["event_uid"] for e in record["starts"]}),
                              "join_event_uids": sorted({e["event_uid"] for e in record["ends"]}),
                              "activity_event_uids": evidence,
                              "observing_session_uids": sorted({e["session_uid"] for e in record["activities"]})})
        # Sequence positions belong to individual sessions, so cannot order observers.
        ends = [e for e in record["ends"] if timestamp(e.get("ts"))]
        completed_at = max((e["ts"] for e in ends), default=None)
        latest = [e for e in ends if e["ts"] == completed_at] if ends else record["ends"]
        statuses = {e.get("attrs", {}).get("status", "unknown") for e in latest}
        status = next(iter(statuses)) if len(statuses) == 1 else "unknown"
        child_session = session_lookup.get(child, {})
        runs.append({"subagent_run_uid": stable_id(child, "subagent_run"),
                     "parent_session_uid": parent, "child_session_uid": child,
                     "spawn_call_uid": child_session.get("spawn_call_uid"),
                     "started_at": min((e["ts"] for e in record["starts"] if timestamp(e.get("ts"))), default=None),
                     "completed_at": completed_at, "status": status,
                     "evidence_uids": evidence, "parent_relation_sources": sources,
                     "observing_session_uids": sorted({e["session_uid"] for e in record["activities"]}),
                     "source": source, "time_basis": "observed_lifecycle_events"})
    return {"subagent_relations": relations, "unresolved_subagent_events": sorted(set(unresolved)),
            "subagent_parent_conflicts": conflicts,
            "subagent_parent_unknown_n": sum(r["parent_session_uid"] is None for r in runs),
            "subagent_runs": runs,
            "subagent_instance_count": len({r["child_session_uid"] for r in runs}),
            "subagent_activity_event_count": sum(e["kind"].startswith("subagent.") for e in events or []),
            "fork_relations": forks,
            "rollback_restart_events": [{"event_uid": e["event_uid"], "session_uid": e["session_uid"],
                "kind": e["kind"], "action": e.get("attrs", {}).get("action")} for e in events or []
                if e["kind"] == "context.restart" or (e["kind"] == "branch"
                    and e.get("attrs", {}).get("action") in ("rollback", "rewind"))]}
