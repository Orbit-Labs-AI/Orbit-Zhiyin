"""Evidence graph and task trajectories; unsupported object versions remain unknown."""

import re
from collections import Counter, defaultdict

from ...models import stable_id
from ..common import timestamp
from ..outcome_subjective import analyze_subjective_outcomes
from ..respond import result_status
from .index import REPORTED_TASK_QUALITIES, WORK_GRAPH_VERSION, WorkIndex


class Graph:
    """Request-local writer. Entity namespaces prevent cross-kind UID collisions.

    Each row keeps its evidence set and a running clock summary, so a repeated merge
    (an artifact touched by many calls) only scans the new evidence instead of the
    whole union; rows are identical to recomputing provenance from scratch.
    """

    def __init__(self, events):
        self.events = {e["event_uid"]: e for e in events}
        self.nodes, self.edges = {}, {}
        self._clock = {uid: (e.get("ts"), timestamp(e.get("ts"))) for uid, e in self.events.items()}
        self._node_evidence, self._edge_evidence = {}, {}

    def _scan(self, ids, summary=(0, True, None)):
        """Extend (unknown evidence count, all known times valid, latest time)."""
        unknown, valid, latest = summary
        clock = self._clock
        for uid in ids:
            entry = clock.get(uid)
            if entry is None:
                unknown += 1
            elif not entry[1]:
                valid = False
            elif latest is None or entry[0] > latest:
                latest = entry[0]
        return unknown, valid, latest

    def _provenance(self, ids, summary, source, state, available_at):
        unknown, valid, latest = summary
        complete = unknown == 0 and bool(ids)
        # max(known evidence times + [available_at]) when every time is a timestamp.
        usable = complete and valid and (available_at is None or timestamp(available_at))
        return {"evidence_uids": ids, "source": source,
                "confidence": {"tier": "reported" if state == "confirmed" else "candidate",
                               "calibrated_probability": None},
                "coverage": {"status": "available" if complete else "partial",
                             "missing_reasons": [] if complete else ["event_evidence_unavailable"]},
                "available_at": (None if not usable else latest if available_at is None
                                 else max(latest, available_at))}

    def _merge(self, store, uid, old, evidence):
        """Union new evidence into a row's set; return its sorted ids and summary."""
        new = set(filter(None, evidence))
        if old is None:
            ids = sorted(new)
            summary = self._scan(ids)
            store[uid] = (new, summary)
            return ids, summary
        seen, summary = store[uid]
        added = sorted(new - seen)
        if not added:
            return old["evidence_uids"], summary
        seen.update(added)
        summary = self._scan(added, summary)
        store[uid] = (seen, summary)
        return sorted([*old["evidence_uids"], *added]), summary

    def provenance(self, evidence, source, state, available_at=None):
        ids = sorted(set(filter(None, evidence)))
        return self._provenance(ids, self._scan(ids), source, state, available_at)

    def node(self, kind, entity_uid, *, session_uid=None, evidence=(), source="typed_fact",
             state="confirmed", attributes=None, task_uid=None, available_at=None):
        uid = stable_id(WORK_GRAPH_VERSION, kind, session_uid, entity_uid)
        old = self.nodes.get(uid)
        if old is None:
            ids, summary = self._merge(self._node_evidence, uid, None, evidence)
            self.nodes[uid] = {"node_uid": uid, "kind": kind, "entity_uid": entity_uid,
                               "session_uid": session_uid, "task_uid": task_uid,
                               "attributes": attributes or {},
                               **self._provenance(ids, summary, source, state, available_at)}
            return uid
        # This call's own availability first, then the union keeps the old attributes/source.
        added = self.provenance(evidence, source, state, available_at)["available_at"]
        if old["confidence"]["tier"] == "candidate":
            state = "candidate"
        previous = old["available_at"]
        available = max(previous, added) if timestamp(previous) and timestamp(added) else None
        ids, summary = self._merge(self._node_evidence, uid, old, evidence)
        self.nodes[uid] = {**old, **self._provenance(ids, summary, old["source"], state, available)}
        return uid

    def edge(self, kind, start, end, *, evidence, source, state="confirmed", missing=(), available_at=None):
        if start is None or end is None:
            return
        assert start in self.nodes and end in self.nodes
        uid = stable_id(WORK_GRAPH_VERSION, kind, start, end)
        old = self.edges.get(uid)
        if old:
            if old["state"] != state:
                state = "candidate"
            missing = [*missing, *old["missing_reasons"]]
        ids, summary = self._merge(self._edge_evidence, uid, old, evidence)
        times = [self.nodes[start]["available_at"], self.nodes[end]["available_at"]]
        if available_at is not None:
            times.append(available_at)
        available = max(times) if all(timestamp(t) for t in times) else None
        provenance = self._provenance(ids, summary, source, state, available)
        if available is None:
            provenance["available_at"] = None
        self.edges[uid] = {"edge_uid": uid, "kind": kind, "from_node_uid": start,
                           "to_node_uid": end, "state": state,
                           "missing_reasons": sorted(set(missing)),
                           **provenance}


def _state(row):
    return "confirmed" if row.get("task_identity_quality") in REPORTED_TASK_QUALITIES else "candidate"


def task_subgraph(graph, trajectory):
    """Keep task relations plus reachable artifact ownership/version ancestry.

    A version reached through VALIDATES or PRODUCES needs its VERSION_OF edge.
    Other tasks using the same artifact are not pulled into this trajectory.
    """
    seeds = {trajectory["task_node_uid"], *(uid for values in trajectory["members"].values() for uid in values)}
    node_ids, edges, frontier = set(seeds), {}, set(seeds)
    outgoing = defaultdict(list)
    nodes = {n["node_uid"]: n for n in graph["nodes"]}
    for edge in graph["edges"]:
        outgoing[edge["from_node_uid"]].append(edge)
    visited = set()
    while frontier:
        start = frontier.pop()
        if start in visited:
            continue
        visited.add(start)
        for edge in outgoing[start]:
            if start not in seeds and not (nodes[start]["kind"] == "ArtifactVersion"
                                           and edge["kind"] in ("VERSION_OF", "SUPERSEDES")):
                continue
            edges[edge["edge_uid"]] = edge
            end = edge["to_node_uid"]
            node_ids.add(end)
            if end not in visited:
                frontier.add(end)
    return {"nodes": [n for n in graph["nodes"] if n["node_uid"] in node_ids],
            "edges": [e for e in graph["edges"] if e["edge_uid"] in edges]}


def _files(call, event):
    """Read explicit file arguments/patch headers, never infer artifacts from shell text."""
    reported = call.get("files")
    files = set(path for path in reported if isinstance(path, str)) if isinstance(reported, list) else set()
    if call.get("kind") not in ("file.edit", "file.write"):
        return sorted(files)
    args = event.get("attrs", {}).get("input")
    items = args if isinstance(args, list) else [args] if isinstance(args, dict) else []
    for item in items:
        if isinstance(item, dict):
            files.update(item[k] for k in ("path", "file_path", "filename")
                         if isinstance(item.get(k), str))
    if isinstance(args, dict) and (call.get("name_raw") or "").rsplit(".", 1)[-1] == "apply_patch":
        # Native Codex patch input is {path: {type: add/update/delete, ...}}.
        files.update(path for path, change in args.items() if isinstance(path, str)
                     and isinstance(change, dict) and change.get("type") in ("add", "update", "delete"))
        files.update(change["move_path"] for change in args.values() if isinstance(change, dict)
                     and isinstance(change.get("move_path"), str))
    if isinstance(args, str) and (call.get("name_raw") or "").rsplit(".", 1)[-1] == "apply_patch":
        files.update(re.findall(r"(?m)^\*\*\* (?:Add|Update|Delete) File: ([^\r\n]+)$", args))
    return sorted(path for path in files if path and len(path) <= 1024 and "[REDACTED" not in path.upper())


def build_work_graph(index: WorkIndex, sessions, respond, outcome, instructions, preferences,
                     *, event_status="available", context_events=(), interaction=None):
    """Project typed facts once; every edge references selected or explicitly linked evidence."""
    events = [*index.events, *context_events]
    graph = Graph(events)
    by_event = {(e["session_uid"], e["event_uid"]): e for e in events}
    session_map = {s["session_uid"]: s for s in sessions}
    tasks, turns, calls, deliveries, artifacts, versions, instruction_nodes = {}, {}, {}, {}, {}, {}, {}
    members = defaultdict(lambda: defaultdict(list))
    trajectory_counts = defaultdict(Counter)
    calls_by_id = {(c["session_uid"], c["call_uid"]): c for c in respond.get("tool_sequence") or []}
    events_by_session = defaultdict(list)
    for event in index.events:
        events_by_session[event["session_uid"]].append(event)

    for task in index.task_result["records"]:
        tasks[task["task_id"]] = graph.node("Task", task["task_id"], evidence=task["human_evidence_ids"],
            source="canonical_task_uid" if task.get("canonical_task_uid") else "native_task_id" if task.get("native_task_id") else "human_task_boundary",
            state=_state(task),
            attributes={k: task.get(k) for k in ("related_session_ids", "project_id", "domain", "task_type", "task_identity_quality")})
    for row in index.membership.values():
        if row["task_uid"] not in tasks and row["task_identity_quality"] in REPORTED_TASK_QUALITIES:
            uid = row["task_uid"]
            tasks[uid] = graph.node("Task", uid, evidence=row["task_evidence_uids"],
                source=row["task_relation_source"], attributes={"task_identity_quality": row["task_identity_quality"],
                                                            "missing_reasons": ["human_task_description_not_observed"]})

    def belongs(node, row, evidence, kind):
        task_uid = row.get("task_uid") or row.get("task_id")
        if task_uid not in tasks:
            return
        state = _state(row)
        graph.edge("BELONGS_TO_TASK", node, tasks[task_uid],
                   evidence=[*evidence, *row.get("task_evidence_uids", [])],
                   source=row.get("task_relation_source", "shared_task_identity"), state=state,
                   missing=[] if state == "confirmed" else ["task_identity_is_candidate"])
        members[task_uid][kind].append(node)

    groups = defaultdict(list)
    for event in index.events:
        if event.get("turn_uid"):
            groups[event["session_uid"], event["turn_uid"]].append(event)
    for (sid, turn), rows in sorted(groups.items()):
        node = graph.node("Turn", turn, session_uid=sid, evidence=[e["event_uid"] for e in rows],
                          source="native_or_canonical_turn_identity")
        turns[sid, turn] = node
        by_task = {e["task_uid"]: e for e in rows if e.get("task_uid")}
        for row in by_task.values():
            belongs(node, {**row, **({"task_identity_quality": "candidate"} if len(by_task) > 1 else {})},
                    [row["event_uid"]], "Turn")

    def artifact(aid, sid, evidence, source, *, revision=None, path=None, quality="confirmed", available_at=None):
        project = session_map.get(sid, {}).get("project_id")
        entity = stable_id("artifact", project or sid, aid)
        node = artifacts[entity] = graph.node("Artifact", entity, evidence=evidence, source=source,
            state=quality, available_at=available_at, attributes={"native_artifact_id": aid if path is None else None,
                                       "path": path, "project_id": project})
        version = None
        if isinstance(revision, (str, int)) and not isinstance(revision, bool) and str(revision):
            identity = stable_id(entity, str(revision), "artifact_version")
            version = versions[identity] = graph.node("ArtifactVersion", identity, evidence=evidence,
                source=source, state=quality, available_at=available_at,
                attributes={"artifact_uid": entity, "revision": str(revision)})
            graph.edge("VERSION_OF", version, node, evidence=evidence, source="explicit_artifact_revision",
                       state=quality, available_at=available_at)
        return node, version

    for call in respond.get("tool_sequence") or []:
        sid, cuid = call["session_uid"], call["call_uid"]
        evidence = [u for u in (call.get("call_event_uid"), call.get("result_event_uid")) if u]
        node = graph.node("ToolCall", cuid, session_uid=sid, evidence=evidence,
                          task_uid=call.get("task_uid"), attributes={k: call.get(k) for k in
                          ("name_raw", "kind", "status_scope", "exit_code", "task_identity_quality")}
                          | {"result": result_status(call)})
        calls[sid, cuid] = node
        belongs(node, call, evidence, "ToolCall")
        if call.get("task_uid"):
            trajectory_counts[call["task_uid"]]["tool_" + result_status(call)] += 1
        event = by_event.get((sid, call.get("call_event_uid")), {})
        for path in _files(call, event):
            obj, _ = artifact(path, sid, evidence, "structured_tool_file_argument", path=path,
                              quality="candidate")
            if call.get("kind") in ("file.edit", "file.write"):
                # File arguments identify attempted work, not a proven content version.
                graph.edge("REVISES" if call["kind"] == "file.edit" else "PRODUCES", node, obj,
                           evidence=evidence, source="file_operation_argument", state="candidate",
                           missing=["artifact_content_version_unreported"])
                if call.get("task_uid"):
                    trajectory_counts[call["task_uid"]]["artifact_edit_attempts"] += 1

    for model in index.model_calls or []:
        evidence = [model.get("usage_event_uid")]
        node = graph.node("ModelCall", model["call_uid"], session_uid=model["session_uid"],
            evidence=evidence, task_uid=model.get("task_uid"), attributes={k: model.get(k) for k in
            ("model_id", "request_id", "request_identity_quality", "boundary_quality", "task_identity_quality")})
        belongs(node, model, evidence, "ModelCall")

    for run in respond.get("subagent_runs") or []:
        sid = run["child_session_uid"]
        related = [e for e in events_by_session[sid] if e.get("task_uid")]
        row = related[0] if related else {}
        node = graph.node("SubagentRun", run["subagent_run_uid"], session_uid=sid,
                          evidence=run["evidence_uids"], source=run["source"],
                          attributes={k: run.get(k) for k in
                                      ("parent_session_uid", "child_session_uid", "status", "started_at", "completed_at")})
        belongs(node, row, run["evidence_uids"], "SubagentRun")
        for uid in run["evidence_uids"]:
            parent = run["parent_session_uid"]
            event = by_event.get((parent, uid), {})
            if event.get("kind") == "subagent.spawn":
                graph.edge("SPAWNS", turns.get((parent, event.get("turn_uid"))), node,
                           evidence=[uid], source="native_spawn_creator")
        graph.edge("SPAWNS", calls.get((run["parent_session_uid"], run.get("spawn_call_uid"))), node,
                   evidence=run["evidence_uids"], source="explicit_spawn_call_uid")

    for retry in respond.get("retry_links") or []:
        sid = retry["session_uid"]
        first = calls.get((sid, retry["from_call_uid"]))
        second = calls.get((sid, retry["to_call_uid"]))
        evidence = [*graph.nodes[first]["evidence_uids"], *graph.nodes[second]["evidence_uids"]] if first and second else []
        graph.edge("RETRIES", second, first, evidence=evidence, source=retry["basis"],
                   state=retry["state"], missing=retry["missing"])
        if retry.get("task_uid"):
            trajectory_counts[retry["task_uid"]][retry["state"] + "_retries"] += 1

    for validation in outcome.get("validation_runs") or []:
        evidence = [u for k, u in validation["validation_evidence"].items() if k.endswith("event_uid") and u]
        node = graph.node("ValidationAttempt", validation["validation_uid"],
                          session_uid=validation["session_uid"], evidence=evidence,
                          task_uid=validation.get("task_uid"), source=validation["identification_source"],
                          available_at=validation.get("available_at"),
                          attributes={k: validation.get(k) for k in
                                      ("kind", "validation_result", "validation_scope", "missing_reason")})
        call_node = calls.get((validation["session_uid"], validation["call_uid"]))
        call_row = calls_by_id.get((validation["session_uid"], validation["call_uid"]), {})
        belongs(node, {**validation, **{k: call_row[k] for k in
                      ("task_identity_quality", "task_relation_source", "task_evidence_uids") if k in call_row}},
                evidence, "ValidationAttempt")
        graph.edge("DERIVED_FROM", node, call_node, evidence=evidence, source="paired_validation_invocation")
        scope = validation.get("validation_scope") or {}
        if scope.get("artifact_uid"):
            obj, version = artifact(scope["artifact_uid"], validation["session_uid"], evidence,
                                    "typed_validation_scope", revision=scope.get("artifact_revision"),
                                    available_at=validation.get("available_at"))
            graph.edge("VALIDATES", node, version or obj, evidence=evidence, source="typed_validation_scope",
                       state="confirmed" if version else "candidate", missing=[] if version else ["artifact_version_unknown"])
        if validation.get("task_uid"):
            trajectory_counts[validation["task_uid"]]["validation_" + validation["validation_result"]] += 1

    subjective = analyze_subjective_outcomes(index.events,
        {s["session_uid"] for s in sessions if s.get("kind") == "main"}, event_status)
    for delivery in subjective.get("deliveries") or []:
        sid, uid = delivery["session_uid"], delivery["delivery_event_uid"]
        event = by_event[sid, uid]
        node = graph.node("Delivery", uid, session_uid=sid, evidence=[uid], task_uid=event.get("task_uid"),
                          source="assistant_final_message", attributes={"task_identity_quality": event.get("task_identity_quality")})
        deliveries[sid, uid] = node
        belongs(node, event, [uid], "Delivery")
        if delivery.get("artifact_id"):
            obj, version = artifact(delivery["artifact_id"], sid, [uid], "declared_delivery_artifact",
                                    revision=delivery.get("artifact_version"))
            graph.edge("PRODUCES", node, version or obj, evidence=[uid], source="declared_delivery_artifact",
                       state="candidate", missing=["artifact_persistence_not_verified"])

    for feedback in subjective.get("feedback") or []:
        sid, uid = feedback["session_uid"], feedback["event_uid"]
        event = by_event[sid, uid]
        node = graph.node("Feedback", uid, session_uid=sid, evidence=[uid], task_uid=event.get("task_uid"),
                          source=feedback.get("label_source", "direct_human_feedback"),
                          state="candidate" if feedback.get("label_source") == "semantic_model" else "confirmed",
                          attributes={k: feedback.get(k) for k in
                          ("user_acceptance", "user_confirmed_completion", "rework_feedback", "link_status", "link_reason")})
        belongs(node, event, [uid], "Feedback")
        target = deliveries.get((sid, feedback.get("delivery_event_uid")))
        if target:
            evidence = [uid, feedback["delivery_event_uid"]]
            state = "confirmed" if feedback["link_status"] == "linked" else "candidate"
            graph.edge("EVALUATES", node, target, evidence=evidence, source=feedback["link_basis"], state=state)
            if feedback["rework_feedback"] or feedback["user_acceptance"] in ("rejected", "mixed", "partial"):
                graph.edge("CORRECTS", node, target, evidence=evidence, source="explicit_feedback", state=state)
                if event.get("task_uid"):
                    trajectory_counts[event["task_uid"]]["rework_feedback"] += 1

    feedback_ids = {(f["session_uid"], f["event_uid"]) for f in subjective.get("feedback") or []}
    for observation in (interaction or {}).get("message_intents") or []:
        if observation.get("state") != "inferred" or "correction" not in (observation.get("intents") or []):
            continue
        sid, uid = observation["session_uid"], observation["event_uid"]
        event = by_event[sid, uid]
        identity = stable_id(WORK_GRAPH_VERSION, "Feedback", sid, uid)
        if (sid, uid) in feedback_ids:
            node = identity
            graph.nodes[node]["attributes"]["interaction_observation"] = observation
        else:
            node = graph.node("Feedback", uid, session_uid=sid, task_uid=event.get("task_uid"),
                              evidence=observation["evidence_event_uids"], source="bounded_semantic_parser",
                              state="candidate", available_at=observation["available_at"],
                              attributes={"interaction_observation": observation})
            belongs(node, event, [uid], "Feedback")
        target_uid = observation.get("target_event_uid")
        target_event = by_event.get((sid, target_uid), {})
        target = deliveries.get((sid, target_uid)) or turns.get((sid, target_event.get("turn_uid")))
        if target:
            graph.edge("CORRECTS", node, target, evidence=[uid, target_uid],
                       source="bounded_semantic_correction", state="candidate")
            if event.get("task_uid"):
                trajectory_counts[event["task_uid"]]["semantic_corrections"] += 1

    instruction_rows = {}
    invalid_replacements = []
    for observation in instructions or []:
        row = by_event.get((observation["session_uid"], observation["event_uid"]), observation)
        for constraint in observation["constraints"]:
            node = graph.node("Instruction", constraint["constraint_uid"], session_uid=observation["session_uid"],
                              evidence=[observation["event_uid"]], source=constraint["method"],
                              state="candidate" if constraint.get("source") == "semantic_model" else "confirmed",
                              available_at=constraint.get("available_at"),
                              task_uid=row.get("task_uid"), attributes={k: constraint.get(k) for k in
                                                                       ("feature", "value", "condition", "targets")})
            instruction_nodes[constraint["constraint_uid"]] = node
            instruction_rows[constraint["constraint_uid"]] = (observation, constraint, row)
            belongs(node, row, [observation["event_uid"]], "Instruction")
    for observation in instructions or []:
        for previous in observation.get("supersedes_instruction_ids", []):
            for constraint in observation["constraints"]:
                prior = instruction_rows.get(previous)
                current = instruction_rows[constraint["constraint_uid"]][2]
                if (not prior or prior[0]["session_uid"] != observation["session_uid"]
                        or not current.get("task_uid") or current.get("task_uid") != prior[2].get("task_uid")
                        or prior[0]["seq"] >= observation["seq"]
                        or any(prior[1].get(k) != constraint.get(k) for k in ("feature", "targets", "condition"))):
                    invalid_replacements.append({"constraint_uid": constraint["constraint_uid"],
                                                 "previous_uid": previous, "reason": "replacement_scope_order_or_dimension_invalid"})
                    continue
                graph.edge("SUPERSEDES", instruction_nodes.get(constraint["constraint_uid"]),
                           instruction_nodes.get(previous),
                           evidence=[observation["event_uid"], prior[0]["event_uid"]],
                           source="explicit_supersedes_reference", state=_state(current))
    for preference in preferences or []:
        node = graph.node("PreferenceObservation", preference["evidence_id"],
            session_uid=preference["session_uid"], evidence=preference["evidence_event_uids"],
            source=preference["source_type"], task_uid=preference.get("task_id"),
            state="confirmed" if preference["source_type"] == "explicit_preference" else "candidate",
            attributes={k: preference.get(k) for k in ("dimension", "value", "scope", "status", "polarity")})
        row = by_event.get((preference["session_uid"], preference["evidence_event_uids"][0]), {})
        belongs(node, row, preference["evidence_event_uids"], "PreferenceObservation")
        graph.edge("DERIVED_FROM", node, instruction_nodes.get(preference["source_id"]),
                   evidence=preference["evidence_event_uids"], source="shared_instruction_observation")

    results = defaultdict(list)
    for result in outcome.get("task_results") or []:
        if result.get("task_uid") in tasks:
            results[result["task_uid"]].append(result)
    def acceptance(uid):
        declared = results[uid]
        states = {row["task_success"] for row in declared}
        success = next(iter(states)) if len(states) == 1 else None
        return {"task_success": success,
                "acceptance_sets": declared,
                "missing_reasons": [] if success is not None else ["complete_task_acceptance_not_established"]}
    trajectories = [{"task_uid": uid, "task_node_uid": node, "members": {
        kind: sorted(set(values)) for kind, values in sorted(members[uid].items())},
        "counts": dict(sorted(trajectory_counts[uid].items())), **acceptance(uid)} for uid, node in sorted(tasks.items())]
    return {"schema_version": WORK_GRAPH_VERSION, "status": event_status,
            "nodes": sorted(graph.nodes.values(), key=lambda n: (n["kind"], n["node_uid"])),
            "edges": sorted(graph.edges.values(), key=lambda e: (e["kind"], e["edge_uid"])),
            "task_trajectories": trajectories,
            "summary": {"nodes_by_kind": dict(sorted(Counter(n["kind"] for n in graph.nodes.values()).items())),
                        "edges_by_kind": dict(sorted(Counter(e["kind"] for e in graph.edges.values()).items())),
                        "edges_by_state": dict(sorted(Counter(e["state"] for e in graph.edges.values()).items())),
                        "invalid_instruction_replacements": invalid_replacements,
                        **index.diagnostics},
            "confidence_semantics": "evidence tiers; no calibrated correctness or utility probability"}
