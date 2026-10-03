"""Shared task trajectories, attribution abstention and temporal/source isolation."""

import copy
import json

from fastapi.testclient import TestClient

from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.analytics.work_graph import build_work_graph, build_work_index
from tandem_backend.api import create_app


def trajectory_bundle(*, native=True, spawn=True):
    scope = {"project_id": "p", "artifact_uid": "report", "artifact_revision": "v1", "coverage": "full"}
    sessions = [{"session_uid": "root", "root_uid": "root", "kind": "main", "source_id": "src", "project_id": "p", "started_at": 0},
                {"session_uid": "child", "root_uid": "root", "parent_uid": "root", "kind": "subagent", "project_id": "p", "started_at": 5}]
    events, calls = [], []

    def event(uid, seq, kind, *, sid="root", text=None, **attrs):
        row = {"event_uid": uid, "session_uid": sid, "turn_uid": "turn-" + sid, "seq": seq, "ts": seq * 100 + 10,
               "kind": kind, "actor": "human" if kind == "message.user" else "assistant" if kind != "tool.result" else "tool",
               "text": text, "attrs": attrs}
        events.append(row)
        return row

    attrs = {"origin": "human"}
    if native:
        attrs.update(task_id="job", task_id_source="native")
    attrs["acceptance"] = {"state": "confirmed", "source": "fictional_criteria", "criteria_set_uid": "set",
                           "available_at": 10, "complete": True, "scope": scope, "criteria": [{"criterion_uid": "unit", "kind": "test"}]}
    event("request", 0, "message.user", text="请修复代码。请用 JSON 输出。运行测试", **attrs)

    def call(uid, seq, *, sid="root", name="exec_command", kind="shell", status="success", path=None):
        event(uid, seq, "tool.call", sid=sid, name=name, argument_digest="same", argument_digest_basis="canonical_json",
              input={"path": path} if path else {"cmd": "pytest"})
        event("r-" + uid, seq + 1, "tool.result", sid=sid, status=status, status_scope="direct_command")
        row = {"call_uid": uid, "session_uid": sid, "turn_uid": "turn-" + sid, "call_event_uid": uid, "result_event_uid": "r-" + uid,
               "name_raw": name, "kind": kind, "status": status, "status_scope": "direct_command", "argument_digest": "same",
               "started_at": seq * 100 + 10, "ended_at": (seq + 1) * 100 + 10}
        calls.append(row)
        return row

    call("write", 1, name="write_file", kind="file.write", path="report.md")
    if spawn:
        event("spawn", 3, "subagent.spawn", child_session_uid="child")
    first = call("check1", 4, status="failed")
    second = call("check2", 6)
    for row in (first, second):
        row["validation"] = {"kind": "test", "executed": True, "source": "fictional_typed_validation",
                             "available_at": row["started_at"], "scope": scope, "criterion_uids": ["unit"]}
    event("final", 8, "message.assistant", text="已交付 report.md", phase="final", artifact_id="report", artifact_version="v1")
    event("feedback", 9, "message.user", text="不对。请重写", origin="human",
          feedback_target={"delivery_event_uid": "final", "task_id": "job"} if native else None)
    event("request2", 10, "message.user", text="新任务：解释数学定理", origin="human",
          task_id="job2" if native else None, task_id_source="native" if native else None)
    call("child-work", 0, sid="child", name="write_file", kind="file.write", path="appendix.md")
    event("child-model", 2, "model.usage", sid="child")
    models = [{"call_uid": "model", "session_uid": "child", "turn_uid": "turn-child", "usage_event_uid": "child-model", "ts": 210,
               "request_identity_quality": "reported", "boundary_quality": "reported", "input_tokens": 1,
               "output_tokens": 1, "cache_read_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0, "coverage": "self"}]
    coverage = {k: {"status": "available"} for k in ("sessions", "events", "tool_calls", "model_calls", "lineage", "turns", "projects")}
    return AnalysisInputBundle(sessions, events, calls, models, coverage)


def analyze(bundle, scope=None):
    return analyze_bundle(bundle, scope, with_text=False, with_recommendations=False)


def test_one_task_connects_execution_validation_delivery_feedback_and_preference():
    bundle = trajectory_bundle()
    before = copy.deepcopy(bundle)
    result = analyze(bundle)
    graph = result["work_graph"]
    kinds = {n["kind"] for n in graph["nodes"]}
    assert kinds == {"Task", "Turn", "ToolCall", "ModelCall", "SubagentRun", "Artifact", "ArtifactVersion",
                     "Delivery", "ValidationAttempt", "Feedback", "Instruction", "PreferenceObservation"}
    rows = {n["node_uid"]: n for n in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["from_node_uid"] in rows and edge["to_node_uid"] in rows
        assert edge["evidence_uids"]
        assert edge["available_at"] is None or edge["available_at"] <= 1010
        assert edge["confidence"]["calibrated_probability"] is None
    kinds = {edge["kind"] for edge in graph["edges"]}
    assert {"BELONGS_TO_TASK", "RETRIES", "SPAWNS", "PRODUCES", "VALIDATES", "EVALUATES", "CORRECTS", "DERIVED_FROM"} <= kinds
    task = next(t for t in graph["task_trajectories"] if t["counts"].get("validation_passed"))
    assert task["counts"]["validation_failed"] == 1
    assert task["counts"]["confirmed_retries"] == 1
    assert task["counts"]["rework_feedback"] == 1
    assert task["task_success"] is True  # only the explicitly complete, exact-version check set
    assert len(task["members"]["ToolCall"]) == 4
    assert len(task["members"]["ModelCall"]) == 1
    assert len(task["members"]["Instruction"]) == len(result["instruction"]["records"][0]["constraints"])
    assert bundle == before
    assert result == analyze(bundle)
    json.dumps(result, allow_nan=False)


def test_candidate_boundaries_cannot_confirm_retry_or_complete_acceptance():
    result = analyze(trajectory_bundle(native=False))
    retry = result["bottleneck_features"]["respond"]["retry_links"][0]
    assert retry["state"] == "candidate" and "task_identity_unconfirmed" in retry["missing"]
    assert result["bottleneck_features"]["outcome"]["task_success"] is None
    assert all(t["task_success"] is None for t in result["work_graph"]["task_trajectories"])
    assert result["preferences"]["evidence"]
    assert all(p["scope"]["kind"] == "task" for p in result["preferences"]["evidence"])
    assert result["preferences"]["records"] == []


def test_child_parent_metadata_does_not_guess_delegated_task():
    context = AnalysisContext.select(trajectory_bundle(spawn=False), Scope())
    child = next(c for c in context.calls if c["session_uid"] == "child")
    assert child["task_uid"] is None
    assert context.work_index.diagnostics["child_task_unknown_n"] == 1
    result = analyze(trajectory_bundle(spawn=False))
    assert not any(edge["kind"] == "SPAWNS" for edge in result["work_graph"]["edges"])


def test_late_tool_result_stays_with_its_original_task_and_mixed_turn_model_abstains():
    bundle = trajectory_bundle()
    call = next(c for c in bundle.tool_calls if c["call_uid"] == "check2")
    result = next(e for e in bundle.events if e["event_uid"] == "r-check2")
    result.update(seq=11, ts=1110)
    call["ended_at"] = 1110
    bundle.model_calls.append({**bundle.model_calls[0], "call_uid": "mixed-model", "session_uid": "root",
                               "turn_uid": "turn-root", "usage_event_uid": "r-check2", "ts": 1110})
    context = AnalysisContext.select(bundle, Scope())
    calls = {c["call_uid"]: c for c in context.calls}
    events = {e["event_uid"]: e for e in context.events}
    assert events["r-check2"]["task_uid"] == calls["check2"]["task_uid"]
    assert events["r-check2"]["task_uid"] != events["request2"]["task_uid"]
    mixed = next(m for m in context.model_calls if m["call_uid"] == "mixed-model")
    assert mixed["task_uid"] is None and mixed["task_unknown_reason"] == "ambiguous_turn_task"


def test_project_and_historical_cutoff_isolation():
    bundle = trajectory_bundle()
    prior = analyze(bundle, Scope(until_ts=850))
    text = json.dumps(prior["work_graph"])
    assert '"feedback"' not in text and '"request2"' not in text
    bundle.sessions.append({**bundle.sessions[0], "session_uid": "other", "root_uid": "other", "project_id": "other"})
    bundle.events.append({**bundle.events[0], "event_uid": "other-request", "session_uid": "other", "attrs": {"origin": "human", "task_id": "job", "task_id_source": "native"}})
    selected = analyze(bundle, Scope(project_ids=["p"], until_ts=850))
    assert selected["work_graph"] == prior["work_graph"]
    assert analyze(bundle)["tasks"]["summary"]["task_count"] == 3


def test_native_projection_is_idempotent_for_parallel_row_workers():
    bundle = trajectory_bundle()
    first = build_work_index(bundle.events, bundle.sessions, bundle.tool_calls, bundle.model_calls)
    second = build_work_index(first.events, bundle.sessions, first.calls, first.model_calls)
    assert second.task_result == first.task_result
    assert second.membership == first.membership
    assert second.events == first.events and second.calls == first.calls



def test_workers_reuse_the_parent_projection_with_canonical_task_references():
    # Re-projecting projected rows is not idempotent for a supplied canonical task UID,
    # so a process-pool job must reuse the parent's index instead of rebuilding it.
    from tandem_backend.analytics import service

    bundle = trajectory_bundle(native=False)
    for event in bundle.events:
        if event["event_uid"] == "request":
            event["attrs"]["task_uid"] = "C1"
    context = AnalysisContext.select(bundle, Scope())
    worker = service._whole_selection_job(service._context_blob(context), "families")
    assert worker == context.families(set(context.session_map))


def test_legacy_inferred_task_ids_never_become_explicit_tasks():
    bundle = trajectory_bundle(native=False, spawn=False)
    for event in bundle.events:
        event["attrs"].update(task_id="legacy-heuristic", task_id_source="legacy_inferred")
    graph = analyze(bundle)["work_graph"]
    assert "legacy-heuristic" not in {n["entity_uid"] for n in graph["nodes"] if n["kind"] == "Task"}

def test_explicit_canonical_task_references_survive_missing_human_text():
    bundle = trajectory_bundle(spawn=False)
    bundle.events = [e for e in bundle.events if e["kind"] in ("tool.call", "tool.result")]
    for event in bundle.events:
        event["attrs"]["task_uid"] = "typed-task"
    context = AnalysisContext.select(bundle, Scope())
    assert {c["task_uid"] for c in context.calls} == {"typed-task"}
    assert all(c["task_identity_quality"] == "explicit" for c in context.calls)
    graph = analyze(bundle)["work_graph"]
    assert any(n["kind"] == "Task" and n["entity_uid"] == "typed-task" for n in graph["nodes"])
    assert len(graph["task_trajectories"]) == 1
    assert context.work_index.task_result["records"] == []  # no invented human task goal
    replay = build_work_index(context.events, context.sessions, context.calls, context.model_calls)
    assert replay.membership == context.work_index.membership


def test_native_patch_mapping_identifies_attempted_files_without_invented_versions():
    bundle = trajectory_bundle()
    event = next(e for e in bundle.events if e["event_uid"] == "write")
    event["attrs"]["input"] = {"report.md": {"type": "update", "unified_diff": "fictional patch", "move_path": None}}
    call = next(c for c in bundle.tool_calls if c["call_uid"] == "write")
    call.update(name_raw="apply_patch", kind="file.edit")
    graph = analyze(bundle)["work_graph"]
    target = next(n for n in graph["nodes"] if n["kind"] == "Artifact" and n["attributes"]["path"] == "report.md")
    edge = next(e for e in graph["edges"] if e["kind"] == "REVISES" and e["to_node_uid"] == target["node_uid"])
    assert edge["state"] == "candidate" and "artifact_content_version_unreported" in edge["missing_reasons"]


def test_task_trajectory_endpoint_preserves_scoped_evidence(tmp_path, monkeypatch):
    result = analyze(trajectory_bundle())
    task = next(t for t in result["work_graph"]["task_trajectories"] if t["counts"].get("validation_passed"))
    monkeypatch.setattr("tandem_backend.analytics.service.analyze_store", lambda *args, **kwargs: copy.deepcopy(result))
    with TestClient(create_app(db=tmp_path / "legacy.db")) as client:
        response = client.get(f'/v1/analytics/tasks/{task["task_uid"]}/trajectory')
        assert response.status_code == 200
        body = response.json()
        assert body["trajectory"]["counts"]["confirmed_retries"] == 1
        ids = {n["node_uid"] for n in body["nodes"]}
        assert all(edge["from_node_uid"] in ids and edge["to_node_uid"] in ids for edge in body["edges"])
        assert client.get('/v1/analytics/tasks/missing/trajectory').status_code == 404


def test_task_trajectory_includes_validation_only_artifact_version_owner(tmp_path, monkeypatch):
    bundle = trajectory_bundle()
    next(c for c in bundle.tool_calls if c["call_uid"] == "check2")["validation"]["scope"]["artifact_revision"] = "v2"
    result = analyze(bundle)
    task = next(t for t in result["work_graph"]["task_trajectories"] if t["counts"].get("validation_passed"))
    monkeypatch.setattr("tandem_backend.analytics.service.analyze_store", lambda *a, **k: copy.deepcopy(result))
    with TestClient(create_app(db=tmp_path / "legacy.db")) as client:
        body = client.get(f'/v1/analytics/tasks/{task["task_uid"]}/trajectory').json()
    version = next(n for n in body["nodes"] if n["kind"] == "ArtifactVersion" and n["attributes"].get("revision") == "v2")
    edge = next(e for e in body["edges"] if e["kind"] == "VERSION_OF" and e["from_node_uid"] == version["node_uid"])
    assert any(n["node_uid"] == edge["to_node_uid"] and n["kind"] == "Artifact" for n in body["nodes"])


def test_task_projection_does_not_expand_through_artifact_to_other_tasks():
    from tandem_backend.analytics.work_graph import task_subgraph

    graph = {"nodes": [{"node_uid": uid, "kind": kind} for uid, kind in
                       (("task", "Task"), ("call", "ToolCall"), ("version", "ArtifactVersion"),
                        ("artifact", "Artifact"), ("other", "Task"))],
             "edges": [{"edge_uid": str(i), "from_node_uid": start, "to_node_uid": end, "kind": kind}
                       for i, (start, end, kind) in enumerate((("call", "version", "VALIDATES"),
                                                             ("version", "artifact", "VERSION_OF"),
                                                             ("artifact", "other", "BELONGS_TO_TASK")))]}
    projection = task_subgraph(graph, {"task_node_uid": "task", "members": {"ToolCall": ["call"]}})
    assert {n["node_uid"] for n in projection["nodes"]} == {"task", "call", "version", "artifact"}
    assert {e["kind"] for e in projection["edges"]} == {"VALIDATES", "VERSION_OF"}


def test_annotation_availability_and_artifact_version_owner_are_explicit():
    bundle = trajectory_bundle()
    call = next(c for c in bundle.tool_calls if c["call_uid"] == "check2")
    call["validation"].update(available_at=950)
    call["validation"]["scope"] = {**call["validation"]["scope"], "artifact_revision": "v2"}
    graph = analyze(bundle)["work_graph"]
    validation = next(n for n in graph["nodes"] if n["kind"] == "ValidationAttempt"
                      and n["evidence_uids"] == ["check2", "r-check2"])
    version = next(n for n in graph["nodes"] if n["kind"] == "ArtifactVersion" and n["attributes"]["revision"] == "v2")
    assert validation["available_at"] == version["available_at"] == 950
    assert any(e["kind"] == "VERSION_OF" and e["from_node_uid"] == version["node_uid"] for e in graph["edges"])
    prior = analyze(bundle, Scope(until_ts=850))["work_graph"]
    assert not any(n["kind"] == "ArtifactVersion" and n["attributes"]["revision"] == "v2" for n in prior["nodes"])


def test_instruction_replacements_require_same_task_and_prior_matching_requirement():
    bundle = trajectory_bundle()
    context = AnalysisContext.select(bundle, Scope())
    result = analyze(bundle)
    events = {e["event_uid"]: e for e in context.events}

    def instruction(uid, event, value, supersedes=()):
        row = events[event]
        return {"session_uid": "root", "event_uid": event, "seq": row["seq"],
                "constraints": [{"constraint_uid": uid, "feature": "format_requirements", "value": value,
                                 "condition": None, "targets": None, "method": "explicit_lexical_rule"}],
                "supersedes_instruction_ids": list(supersedes)}

    instructions = [instruction("old", "request", "json"),
                    instruction("valid", "feedback", "markdown", ["old"]),
                    instruction("other-task", "request2", "json", ["valid"])]
    graph = build_work_graph(context.work_index, context.sessions,
                             result["bottleneck_features"]["respond"], result["bottleneck_features"]["outcome"],
                             instructions, [])
    replacements = [e for e in graph["edges"] if e["kind"] == "SUPERSEDES"]
    assert len(replacements) == 1 and replacements[0]["state"] == "confirmed"
    assert graph["summary"]["invalid_instruction_replacements"][0]["previous_uid"] == "valid"
    instructions[0]["supersedes_instruction_ids"] = ["valid"]
    graph = build_work_graph(context.work_index, context.sessions,
                             result["bottleneck_features"]["respond"], result["bottleneck_features"]["outcome"],
                             instructions, [])
    assert len([e for e in graph["edges"] if e["kind"] == "SUPERSEDES"]) == 1
    assert any(r["previous_uid"] == "valid" for r in graph["summary"]["invalid_instruction_replacements"])


def _bare_event(uid, seq, kind, **attrs):
    return {"event_uid": uid, "session_uid": "s", "turn_uid": "t", "seq": seq, "ts": seq * 100, "kind": kind,
            "actor": "human" if kind == "message.user" else "tool" if kind == "tool.result" else "assistant",
            "text": "请修复代码" if kind == "message.user" else None, "attrs": attrs}


def test_result_keeps_its_own_typed_task_when_paired_call_has_none():
    from tandem_backend.models import stable_id

    # The call precedes every task boundary (no task); a human request then opens a
    # local task span that also covers the result.
    sessions = [{"session_uid": "s", "root_uid": "s", "kind": "main", "source_id": "src", "project_id": "p", "started_at": 0}]
    calls = [{"call_uid": "c", "session_uid": "s", "call_event_uid": "c", "result_event_uid": "r", "status": "success"}]
    typed = [_bare_event("c", 0, "tool.call", name="x"), _bare_event("u", 1, "message.user", origin="human"),
             _bare_event("r", 2, "tool.result", status="success", task_id="job", task_id_source="native")]
    index = build_work_index(typed, sessions, calls, None)
    assert index.membership.get(("s", "c")) is None
    own = index.membership[("s", "r")]
    assert own["task_uid"] == stable_id("task", "src", "p", "job")
    assert own["task_evidence_uids"] == ["r"] and own["task_relation_source"] == "native_task_id"
    # Without its own reference the later span must not adopt the result of an earlier call.
    untyped = [*typed[:2], _bare_event("r", 2, "tool.result", status="success")]
    assert ("s", "r") not in build_work_index(untyped, sessions, calls, None).membership


def test_acceptance_sets_combine_like_criteria_within_one_set():
    from tandem_backend.analytics.work_graph.graph import combine_acceptance

    assert combine_acceptance([None, False]) is False   # a known failure is not hidden by an unknown set
    assert combine_acceptance([True, False]) is False
    assert combine_acceptance([True, None]) is None
    assert combine_acceptance([True, True]) is True
    assert combine_acceptance([]) is None


def test_retry_without_graph_call_nodes_is_not_counted():
    bundle = trajectory_bundle()
    context = AnalysisContext.select(bundle, Scope())
    families = context.families(set(context.session_map))
    respond = copy.deepcopy(families["respond"])
    link = respond["retry_links"][0]
    respond["retry_links"].append({**link, "to_call_uid": "missing-call"})
    graph = build_work_graph(context.work_index, context.sessions, respond, families["outcome"], [], [])
    task = next(t for t in graph["task_trajectories"] if t["task_uid"] == link["task_uid"])
    retries = [e for e in graph["edges"] if e["kind"] == "RETRIES"]
    assert len(retries) == 1
    assert task["counts"][link["state"] + "_retries"] == 1
