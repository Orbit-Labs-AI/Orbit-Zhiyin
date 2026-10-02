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
    relations, unresolved, forks = {}, [], []
    for s in sessions:
        if s.get("forked_from"):
            forks.append({"session_uid": s["session_uid"], "forked_from": s["forked_from"]})
        if s.get("kind") in ("subagent", "workflow_agent") and s.get("parent_uid"):
            relations[(s["parent_uid"], s["session_uid"])] = {
                "parent_session_uid": s["parent_uid"], "child_session_uid": s["session_uid"],
                "source": "explicit_parent_uid", "spawn_event_uids": [], "join_event_uids": []}
    for e in events or []:
        if not e["kind"].startswith("subagent."):
            continue
        a = e.get("attrs", {})
        child, parent = a.get("child_session_uid"), a.get("parent_session_uid", e["session_uid"])
        if not child or child == parent:
            unresolved.append(e["event_uid"])
            continue
        relation = relations.setdefault((parent, child), {"parent_session_uid": parent, "child_session_uid": child,
             "source": "explicit_event", "spawn_event_uids": [], "join_event_uids": []})
        relation.setdefault("activity_event_uids", []).append(e["event_uid"])
        if e["kind"] in ("subagent.spawn", "subagent.result"):
            relation["spawn_event_uids" if e["kind"] == "subagent.spawn" else "join_event_uids"].append(e["event_uid"])
    lookup = {e["event_uid"]: e for e in events or []}
    session_lookup = {s["session_uid"]: s for s in sessions}
    runs = []
    for (parent, child), relation in sorted(relations.items()):
        starts = [lookup[u] for u in relation["spawn_event_uids"]]
        ends = [lookup[u] for u in relation["join_event_uids"]]
        latest = max(ends, key=lambda e: e["seq"], default={})
        child_session = session_lookup.get(child, {})
        runs.append({"subagent_run_uid": stable_id(parent, child, "subagent_run"),
                     "parent_session_uid": parent, "child_session_uid": child,
                     "spawn_call_uid": child_session.get("spawn_call_uid"),
                     "started_at": min((e["ts"] for e in starts if timestamp(e.get("ts"))), default=None),
                     "completed_at": latest.get("ts"),
                     "status": latest.get("attrs", {}).get("status", "unknown"),
                     "evidence_uids": sorted(set(relation.get("activity_event_uids", []))),
                     "source": relation["source"], "time_basis": "observed_lifecycle_events"})
    return {"subagent_relations": list(relations.values()), "unresolved_subagent_events": unresolved,
            "subagent_runs": runs,
            "subagent_instance_count": len({r["child_session_uid"] for r in runs}),
            "subagent_activity_event_count": sum(e["kind"].startswith("subagent.") for e in events or []),
            "fork_relations": forks,
            "rollback_restart_events": [{"event_uid": e["event_uid"], "session_uid": e["session_uid"],
                "kind": e["kind"], "action": e.get("attrs", {}).get("action")} for e in events or []
                if e["kind"] == "context.restart" or (e["kind"] == "branch"
                    and e.get("attrs", {}).get("action") in ("rollback", "rewind"))]}
