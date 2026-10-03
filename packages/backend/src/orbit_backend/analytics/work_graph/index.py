"""Assign shared task identities from native evidence and bounded local task spans.

This projection never changes source records. Local task candidates stay candidates;
neither sequence proximity nor a child's parent metadata establishes a confirmed task.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass

from ...models import stable_id
from ..common import canonical_task_reference
from ..respond.calls import native_sequence
from ..respond.relations import build_execution_relations
from ..task import segment_tasks

WORK_GRAPH_VERSION = "work-graph-v1"
REPORTED_TASK_QUALITIES = {"native", "human_confirmed", "explicit_boundary", "explicit"}


@dataclass
class WorkIndex:
    task_result: dict
    events: list[dict]
    calls: list[dict] | None
    model_calls: list[dict] | None
    membership: dict[tuple[str, str], dict]
    lineage: dict
    diagnostics: dict


def _membership(task, boundary):
    quality = "explicit" if task.get("canonical_task_uid") else "native" if task.get("native_task_id") else (
        "explicit_boundary" if boundary["status"] == "explicit" else "candidate")
    return {"task_uid": task["task_id"], "task_identity_quality": quality,
            "task_relation_source": "canonical_task_uid" if quality == "explicit" else "native_task_id" if quality == "native" else "local_task_boundary",
            "task_evidence_uids": [boundary["start"]["event_uid"]]}


def build_work_index(events, sessions, calls, model_calls):
    """One task partition shared by execution, validation, delivery and instructions."""
    result = segment_tasks(events, sessions)
    spans = defaultdict(list)
    for task in result["records"]:
        task["task_uid"] = task["task_id"]
        task["task_identity_quality"] = ("explicit" if task.get("canonical_task_uid") else "native" if task.get("native_task_id") else
            "explicit_boundary" if all(b["status"] == "explicit" for b in task["task_boundaries"]) else "candidate")
        for boundary in task["task_boundaries"]:
            spans[boundary["session_uid"]].append((boundary["start"]["seq"], boundary, task))
    for boundaries in spans.values():
        boundaries.sort(key=lambda row: row[0])
    starts = {sid: [row[0] for row in boundaries] for sid, boundaries in spans.items()}
    sessions_by_id = {s["session_uid"]: s for s in sessions}
    native_tasks = {(sessions_by_id[sid].get("source_id"),
                     sessions_by_id[sid].get("project_id") or ("legacy_project", sessions_by_id[sid].get("legacy_project_id") or sid),
                     task["native_task_id"]): task["task_id"]
                    for task in result["records"] if task.get("native_task_id")
                    for sid in task["related_session_ids"]}
    selected = defaultdict(list)
    keys_by_session = defaultdict(list)
    for event in events or []:
        key = (event["session_uid"], event["event_uid"])
        if key not in selected:
            keys_by_session[event["session_uid"]].append(key)
        selected[key].append(event)
    membership, reasons = {}, {}
    for key, matches in selected.items():
        event = matches[0]
        seq, sid = event.get("seq"), event["session_uid"]
        if len(matches) > 1 or not native_sequence(seq):
            reasons[key] = "ambiguous_event_identity_or_sequence"
            continue
        position = bisect_right(starts.get(sid, []), seq) - 1
        if position < 0:
            reasons[key] = "no_observed_task_boundary"
            continue
        _, boundary, task = spans[sid][position]
        end = boundary.get("end")
        if end and (seq > end["seq"] or seq == end["seq"] and not boundary["end_inclusive"]):
            reasons[key] = "outside_observed_task_span"
            continue
        membership[key] = _membership(task, boundary)

    # An explicit typed reference takes precedence over a local boundary. It can
    # exist before the first observed human request or without visible prompt text.
    for key, matches in selected.items():
        if len(matches) != 1 or not native_sequence(matches[0].get("seq")):
            continue
        event = matches[0]
        attrs, sid = event.get("attrs", {}), event["session_uid"]
        canonical = canonical_task_reference(event)
        native = (attrs.get("native_task_id") if attrs.get("native_task_id_source") in ("native", "human_confirmed")
                  else attrs.get("task_id") if attrs.get("task_id_source") in ("native", "human_confirmed") else None)
        if canonical:
            uid, quality, source = canonical, "explicit", "canonical_task_uid"
        elif isinstance(native, str) and native:
            session = sessions_by_id.get(sid, {})
            project = session.get("project_id") or ("legacy_project", session.get("legacy_project_id") or sid)
            uid, quality, source = stable_id("task", session.get("source_id"), project, native), "native", "native_task_id"
        else:
            continue
        membership[key] = {"task_uid": uid, "task_identity_quality": quality,
                           "task_relation_source": source, "task_evidence_uids": [event["event_uid"]]}
        reasons.pop(key, None)

    for call in calls or []:
        key = (call["session_uid"], call.get("call_event_uid"))
        matches = selected.get(key, [])
        canonical = canonical_task_reference(call)
        if (canonical and membership.get(key, {}).get("task_identity_quality") not in REPORTED_TASK_QUALITIES and len(matches) == 1
                and matches[0].get("kind") == "tool.call" and native_sequence(matches[0].get("seq"))):
            membership[key] = {"task_uid": canonical, "task_identity_quality": "explicit",
                               "task_relation_source": "canonical_task_uid", "task_evidence_uids": [key[1]]}
            reasons.pop(key, None)

    lineage = build_execution_relations(events, sessions)
    inherited, ambiguous_children = {}, set()
    calls_by_id = {(c["session_uid"], c["call_uid"]): c for c in calls or []}
    # A reported creator alone cannot identify which task was delegated. Require
    # the selected spawn event or an explicit spawn-call reference inside a task.
    for _ in range(len(lineage["subagent_runs"])):
        changed = False
        for run in lineage["subagent_runs"]:
            child, parent = run["child_session_uid"], run["parent_session_uid"]
            if child in inherited or child in ambiguous_children or parent is None:
                continue
            candidates = []
            for uid in run["evidence_uids"]:
                matches = selected.get((parent, uid), [])
                if len(matches) == 1 and matches[0]["kind"] == "subagent.spawn":
                    found = membership.get((parent, uid))
                    if found:
                        candidates.append((found, uid))
            call = calls_by_id.get((parent, run.get("spawn_call_uid")))
            if call:
                found = membership.get((parent, call.get("call_event_uid")))
                if found:
                    candidates.append((found, call["call_event_uid"]))
            if len({row[0]["task_uid"] for row in candidates}) > 1:
                ambiguous_children.add(child)
                continue
            if candidates:
                found = candidates[0][0]
                inherited[child] = {**found, "task_relation_source": "explicit_spawn_task",
                                    "task_evidence_uids": sorted({*found["task_evidence_uids"],
                                                                  *(uid for _, uid in candidates)})}
                for key in keys_by_session[child]:
                    membership[key] = dict(inherited[child])
                    reasons.pop(key, None)
                changed = True
        if not changed:
            break

    # A tool result belongs to its paired invocation even if a new task has begun.
    for call in calls or []:
        sid = call["session_uid"]
        found = membership.get((sid, call.get("call_event_uid")))
        end_key = (sid, call.get("result_event_uid"))
        if end_key in selected:
            membership.pop(end_key, None)
            if found:
                membership[end_key] = {**found, "task_relation_source": "paired_tool_invocation"}

    projected_events = []
    for event in events or []:
        key = (event["session_uid"], event["event_uid"])
        found = membership.get(key)
        attrs = dict(event.get("attrs", {}))
        target = attrs.get("feedback_target")
        if isinstance(target, dict) and isinstance(target.get("task_id"), str) and target["task_id"]:
            session = sessions_by_id.get(event["session_uid"], {})
            project = session.get("project_id") or ("legacy_project", session.get("legacy_project_id") or event["session_uid"])
            canonical = native_tasks.get((session.get("source_id"), project, target["task_id"]))
            if canonical:
                attrs["feedback_target"] = {**target, "task_id": canonical}
        if found:
            # Preserve the native identifier separately; compatibility consumers use
            # task_id while the graph and execution families use task_uid.
            if attrs.get("task_id_source") in ("native", "human_confirmed"):
                attrs["native_task_id"] = attrs.get("task_id")
                attrs["native_task_id_source"] = attrs["task_id_source"]
            attrs.update(found, task_id=found["task_uid"],
                         task_id_source="explicit" if found["task_identity_quality"] in REPORTED_TASK_QUALITIES
                         else "work_graph_candidate")
        projected_events.append({**event, **(found or {}), "attrs": attrs})

    projected_calls = None if calls is None else []
    for original in calls or []:
        key = (original["session_uid"], original.get("call_event_uid"))
        found = membership.get(key)
        call = {**original, **(found or {})}
        if not found:
            call.update(task_uid=None, task_identity_quality="unknown",
                        task_unknown_reason=reasons.get(key, "call_event_not_selected"))
        matches = selected.get(key, [])
        if len(matches) == 1:
            attrs = matches[0].get("attrs", {})
            if (call.get("argument_digest") and call["argument_digest"] == attrs.get("argument_digest")
                    and attrs.get("argument_digest_basis") == "canonical_json"):
                if call.get("argument_digest_kind") is None:
                    call["argument_digest_kind"] = "canonical_json"
        projected_calls.append(call)

    turns = defaultdict(list)
    for event in projected_events:
        if event.get("turn_uid"):
            turns[event["session_uid"], event["turn_uid"]].append(event)
    projected_models = None if model_calls is None else []
    for original in model_calls or []:
        key = (original["session_uid"], original.get("usage_event_uid"))
        found = membership.get(key)
        turn = turns.get((original["session_uid"], original.get("turn_uid")), [])
        tasks = {e.get("task_uid") for e in turn if e.get("task_uid")}
        model = dict(original)
        if found and len(tasks) <= 1:
            model.update(found)
        elif len(tasks) == 1:
            member = next(e for e in turn if e.get("task_uid"))
            model.update({k: member[k] for k in ("task_uid", "task_identity_quality",
                                                "task_relation_source", "task_evidence_uids")})
            if any(not e.get("task_uid") for e in turn):
                model["task_identity_quality"] = "candidate"
        else:
            model.update(task_uid=None, task_identity_quality="unknown",
                         task_unknown_reason="ambiguous_turn_task" if len(tasks) > 1 else "model_task_evidence_missing")
        projected_models.append(model)
    diagnostics = {"unassigned_events": len(projected_events) - len(membership),
                   "unassigned_calls": sum(not c.get("task_uid") for c in projected_calls or []),
                   "unassigned_model_calls": sum(not c.get("task_uid") for c in projected_models or []),
                   "ambiguous_child_tasks": sorted(ambiguous_children),
                   "child_task_unknown_n": sum(r["child_session_uid"] not in inherited for r in lineage["subagent_runs"]),
                   "assignment_semantics": "candidate boundaries never establish confirmed retry, acceptance or durable preference"}
    return WorkIndex(result, projected_events, projected_calls, projected_models, membership, lineage, diagnostics)
