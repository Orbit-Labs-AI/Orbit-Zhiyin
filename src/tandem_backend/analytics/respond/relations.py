"""Explicit subagent relations and reliable concurrent execution intervals."""

from collections import defaultdict

from ..common import timestamp


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
