"""History content survives learning; scope, grounding and validation remain hard boundaries."""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager

import pytest

from orbit_backend.ai import pack, registry
from orbit_backend.ai.tasks_learning import finalize, validate
from orbit_backend.appdb import AppDB
from orbit_backend.recommend.learned import record_validation, retrieve, validation_state


def example():
    refs = [{"session_uid": "s1", "event_uid": "e1"}, {"session_uid": "s2", "event_uid": "e2"}]
    return {"name": "inspect-edit-verify", "kind": "skill", "description": "Edit structured documents reliably",
            "activation": "Use for structured document edits", "avoid": ["Unrelated interactive tasks"],
            "keywords": ["structured", "document", "edit"], "requires": ["read", "write"],
            "procedure": [{"action": "Inspect field names before editing", "evidence": refs[:1]},
                          {"action": "Reopen output and check the requested fields", "evidence": refs[1:]}],
            "verification": ["Compare requested edits to saved output"], "termination": "Stop after reread checks",
            "evidence": refs, "limitations": ["History outcomes were not independently verified"]}


def evidence_pack():
    return {"content": {"trajectories": {"sessions": [
        {"session_uid": "s1", "events": [{"event_uid": "e1"}]},
        {"session_uid": "s2", "events": [{"event_uid": "e2"}]}]}},
        "refs": {"session": ["s1", "s2"]}, "preview_digest": "digest"}


def library(candidates=None):
    result = finalize({"candidates": candidates or [example()], "gaps": []}, evidence_pack(), "model")
    return {"artifact_id": "library", "content_hash": "library-hash", "payload": result["result"],
            "checks": {"validation_receipts": []}}


def test_grounding_rejects_foreign_sessions_and_fabricated_step_refs():
    candidate = example()
    assert not validate({"candidates": [candidate]}, evidence_pack())
    candidate["procedure"][1]["evidence"] = [{"session_uid": "s2", "event_uid": "invented"}]
    assert validate({"candidates": [candidate]}, evidence_pack())
    candidate = example()
    candidate["evidence"] = candidate["evidence"][:1]
    candidate["procedure"][1]["evidence"] = candidate["evidence"]
    assert validate({"candidates": [candidate]}, evidence_pack())


def test_unavailable_projection_is_not_misreported_as_missing_history():
    from orbit_backend.ai.learning_feedback import validate_history_pack, validate_pack

    unavailable = {"content": {"trajectories": {"sessions": [], "unavailable": True}}}
    for check in (validate_history_pack, validate_pack):
        assert "rebuild" in check(unavailable)[0]
    assert "two selected" in validate_history_pack({"content": {"trajectories": {"sessions": []}}})[0]
    assert not validate_history_pack(evidence_pack())


def test_step_evidence_is_merged_instead_of_demanding_redundant_citations():
    candidate = example()
    candidate["evidence"] = candidate["evidence"][:1]
    assert not validate({"candidates": [candidate]}, evidence_pack())
    result = finalize({"candidates": [candidate], "gaps": []}, evidence_pack(), "model")
    assert result["result"]["candidates"][0]["support_sessions"] == 2
    assert len(result["result"]["candidates"][0]["evidence"]) == 2


def test_refinement_rejects_test_feedback_and_keeps_training_support_separate():
    from orbit_backend.ai.learning_feedback import validate_request

    item = {"split": "test", "case_id": "case", "session_uid": "validation:case",
            "event_uid": "evaluation:case", "report_digest": "a" * 64, "body": "A check failed"}
    request = {"params": {"artifact_id": "library", "validation_feedback": [item]}}
    assert validate_request(request)
    item["split"] = "validation"
    assert not validate_request(request)
    context = evidence_pack()
    context["content"]["validation_feedback"] = [item]
    candidate = example()
    candidate["procedure"][1]["evidence"] = [{"session_uid": item["session_uid"], "event_uid": item["event_uid"]}]
    assert not validate({"candidates": [candidate]}, context)
    result = finalize({"candidates": [candidate], "gaps": []}, context, "model")
    assert result["result"]["training_session_uids"] == ["s1", "s2"]
    assert result["result"]["candidates"][0]["support_sessions"] == 2
    candidate["evidence"] = candidate["evidence"][:1]
    assert validate({"candidates": [candidate]}, context)  # One history + validation is not two histories.


def test_refinement_preserves_unedited_content_and_its_validation_receipts():
    first, second = example(), example()
    second["name"] = "other-operation"
    old = library([first, second])["payload"]["candidates"]
    receipt = {"candidate_id": old[1]["candidate_id"], "content_hash": old[1]["content_hash"]}
    context = evidence_pack()
    context["content"]["procedure_draft"] = {"artifact_id": "old-library", "candidates": old,
        "editable_candidate_ids": [old[0]["candidate_id"]], "validation_receipts": [receipt]}
    assert validate({"candidates": [second]}, context)
    first["verification"].append("Independently check required decisions against the request")
    result = finalize({"candidates": [first], "gaps": []}, context, "model")
    assert result["result"]["parent_library"] == "old-library"
    assert result["result"]["candidates"][1] == old[1]
    assert result["artifact"]["checks"]["validation_receipts"] == [receipt]
    assert result["result"]["candidates"][0]["content_hash"] != old[0]["content_hash"]


def test_pack_preserves_arguments_redacts_and_cannot_be_replaced_by_slots(tmp_path):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""CREATE TABLE session(session_uid TEXT, kind TEXT, started_at INTEGER,
        project_id TEXT, source_id TEXT, cwd TEXT);
        CREATE TABLE event(event_uid TEXT, session_uid TEXT, kind TEXT, seq INTEGER, call_id TEXT,
        attrs TEXT, text TEXT);""")
    for uid in ("s1", "s2", "outside"):
        db.execute("INSERT INTO session VALUES (?, 'main', 100, NULL, 'source', '/task')", (uid,))
        db.execute("INSERT INTO event VALUES (?, ?, 'tool.call', 7, 'c1', ?, '')", (uid, uid,
                   json.dumps({"name": "bash", "input": {"command": "python3 -c 'reopen_and_verify()'",
                                                          "key": "sk-abcdefghijklmnop1234"}})))
        db.execute("INSERT INTO event VALUES (?, ?, 'reasoning', 8, NULL, '{}', 'private reasoning')",
                   (uid + "-reasoning", uid))

    @contextmanager
    def reads():
        yield db

    result = pack.build(registry.get("recommend.learn"), reads=reads, appdb=AppDB(tmp_path / "app.db"), home=tmp_path,
                        scope={"start_ms": 0, "end_ms": 1000, "session_uids": ["s1", "s2"],
                               "excluded_session_uids": ["s2"]},
                        slots={"trajectories": {"sessions": [{"session_uid": "outside"}]}})
    sessions = result["content"]["trajectories"]["sessions"]
    assert [s["session_uid"] for s in sessions] == ["s1"]
    assert "reopen_and_verify" in sessions[0]["events"][0]["input"]["command"]
    blob = json.dumps(result)
    assert "sk-abcdefghijklmnop1234" not in blob and "private reasoning" not in blob
    assert result["refs"]["event"] == ["s1"] and result["items"][0]["data_class"] == "snippets"


def test_validation_is_content_bound_and_negative_receipts_remain():
    lib = library()
    candidate = lib["payload"]["candidates"][0]
    kwargs = {"capabilities": ["read", "write"]}
    assert not retrieve(lib, "edit structured document", **kwargs)["candidates"]
    assert retrieve(lib, "edit structured document", **kwargs,
                    config={"require_validation": False})["candidates"]
    receipt = {"candidate_id": candidate["candidate_id"], "content_hash": candidate["content_hash"],
               "candidate_passed": True, "baseline_passed": False,
               "candidate_tokens": 100, "baseline_tokens_lower_bound": 50, "actual_usage": "confirmed"}
    lib["checks"]["validation_receipts"] = [receipt]
    assert retrieve(lib, "edit structured document", **kwargs)["candidates"]
    assert validation_state(candidate, [{**receipt, "content_hash": "old"}]) == "unvalidated"
    assert validation_state(candidate, [{**receipt, "actual_usage": "unknown"}]) == "usage_unconfirmed"
    lib["checks"]["validation_receipts"].append({**receipt, "candidate_passed": False})
    assert not retrieve(lib, "edit structured document", **kwargs)["candidates"]


def test_compatibility_is_capability_based_and_dedup_does_not_use_titles():
    first, second = example(), example()
    second.update(name="different-procedure")
    second["procedure"][0]["action"] = "Inspect schema types and constraints"
    lib = library([first, second])
    result = retrieve(lib, "edit structured document", capabilities=["read", "write"],
                      config={"require_validation": False})
    assert len(result["candidates"]) == 2
    missing = retrieve(lib, "edit structured document", capabilities=["read"],
                       config={"require_validation": False})
    assert not missing["candidates"]
    assert all(r["decisions"][-1]["reason"] == "missing_capabilities:write"
               for r in missing["funnel"]["candidates"])


def test_validation_receipt_rejects_test_and_unknown_outcomes_before_writing():
    candidate = library()["payload"]["candidates"][0]
    receipt = {"candidate_id": candidate["candidate_id"], "content_hash": candidate["content_hash"],
               "split": "test", "task_id": "heldout", "run_digest": "a" * 64, "model": "model",
               "baseline_passed": True, "candidate_passed": True, "candidate_tokens": 10,
               "baseline_tokens_lower_bound": 20, "actual_usage": "confirmed", "usage_evidence_digest": "b" * 64}
    with pytest.raises(ValueError, match="validation"):
        record_validation(None, "library", receipt)
    changed = copy.deepcopy(receipt)
    changed.update(split="validation", candidate_passed=None)
    with pytest.raises(ValueError, match="Unknown"):
        record_validation(None, "library", changed)


def test_receipts_persist_without_mutating_library_content(tmp_path):
    from types import SimpleNamespace

    from orbit_backend.ai.runner import Runner
    from orbit_backend.recommend.learned import read_library

    appdb = AppDB(tmp_path / "app.db")
    runner = Runner(SimpleNamespace(appdb=appdb))
    result = finalize({"candidates": [example()], "gaps": []}, evidence_pack(), "model")
    with appdb.write() as db:
        artifact_id = runner._save_artifact(db, {"job_id": "synthetic-job"}, result["artifact"], True)
    before = read_library(appdb, artifact_id)
    candidate = before["payload"]["candidates"][0]
    receipt = {"candidate_id": candidate["candidate_id"], "content_hash": candidate["content_hash"],
               "split": "validation", "task_id": "development", "run_digest": "a" * 64, "model": "model",
               "baseline_passed": True, "candidate_passed": True, "candidate_tokens": 10,
               "baseline_tokens_lower_bound": 20, "actual_usage": "confirmed", "usage_evidence_digest": "b" * 64}
    record_validation(appdb, artifact_id, receipt)
    record_validation(appdb, artifact_id, receipt)
    after = read_library(appdb, artifact_id)
    assert after["content_hash"] == before["content_hash"] and after["payload"] == before["payload"]
    assert len(after["checks"]["validation_receipts"]) == 1
    with pytest.raises(ValueError, match="immutable"):
        record_validation(appdb, artifact_id, {**receipt, "content_hash": "old"})
    assert retrieve(after, "edit structured document", capabilities=["read", "write"])["candidates"]
    appdb.close()
