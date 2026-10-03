"""Explicit validation counterexamples; never infer a test/train label from content."""

from __future__ import annotations

import json
import re


def validate_request(req, *, needs_library=True):
    params = req.get("params") or {}
    if needs_library and not isinstance(params.get("artifact_id"), str):
        return ["Refinement requires an existing learned library artifact_id"]
    selected = params.get("candidate_ids")
    if selected is not None and (not isinstance(selected, list) or not 1 <= len(selected) <= 8
                                 or not all(isinstance(x, str) for x in selected)):
        return ["candidate_ids must explicitly select one to eight candidates"]
    feedback = params.get("validation_feedback")
    if not isinstance(feedback, list) or not 1 <= len(feedback) <= 8:
        return ["Select one to eight explicit validation counterexamples"]
    for item in feedback:
        if not isinstance(item, dict) or set(item) != {
                "split", "case_id", "session_uid", "event_uid", "report_digest", "body"}:
            return ["Invalid validation counterexample fields"]
        if item["split"] != "validation":
            return ["Test feedback cannot enter skill refinement"]
        if not all(isinstance(item[k], str) for k in item):
            return ["Counterexample fields must be text"]
        if not item["session_uid"].startswith("validation:") or not item["event_uid"].startswith("evaluation:"):
            return ["External feedback must be distinguished from native history events"]
        if not re.fullmatch(r"[a-f0-9]{64}", item["report_digest"]) or not 1 <= len(item["body"]) <= 32000:
            return ["Counterexample needs a report digest and bounded body"]
    return []


def draft(c):
    with c.appdb.read() as db:
        row = db.execute("SELECT payload, checks FROM ai_artifact WHERE artifact_id=? AND template_id=?",
                         (c.params.get("artifact_id"), "history-procedures@1")).fetchone()
    if row is None:
        raise ValueError("Unknown learned procedure library")
    value = json.loads(row[0])
    allowed = set(c.allowed_sessions(value["training_session_uids"]))
    candidates = [candidate for candidate in value["candidates"] if
                  all(e["session_uid"] in allowed or e["session_uid"].startswith("validation:")
                      for e in candidate["evidence"])]
    ids = {candidate["candidate_id"] for candidate in candidates}
    selected = set(c.params.get("candidate_ids") or ids)
    if not selected <= ids:
        raise ValueError("Only in-scope library candidates may be revised")
    return {"artifact_id": c.params["artifact_id"], "candidates": candidates,
            "editable_candidate_ids": sorted(selected),
            "validation_receipts": json.loads(row[1]).get("validation_receipts", []),
            "omitted_by_scope": len(value["candidates"]) - len(candidates), "gaps": value["gaps"]}


def feedback(c):
    errors = validate_request({"params": c.params}, needs_library=False)
    if errors:
        raise ValueError(errors[0])
    return c.params["validation_feedback"]


def validate_history_pack(pack):
    history = (pack.get("content") or {}).get("trajectories") or {}
    if history.get("unavailable") or any(item.get("unavailable") for item in pack.get("items", [])
                                         if item.get("key") == "trajectories"):
        return ["History is unavailable; finish import or migrate and rebuild the data projection"]
    if len(history.get("sessions", [])) < 2:
        return ["Learning needs at least two selected history sessions"]
    return []


def validate_pack(pack):
    errors = validate_history_pack(pack)
    if errors:
        return errors
    content = pack.get("content") or {}
    if not (content.get("procedure_draft") or {}).get("editable_candidate_ids"):
        return ["No selected, in-scope library candidate is available for refinement"]
    if not content.get("validation_feedback"):
        return ["Validation feedback must remain enabled for refinement"]
    return []


ITEMS = {
    "procedure_draft": ("已有技能草稿", "所选范围内的历史技能，保留正文版本与证据", "snippets", draft),
    "validation_feedback": ("验证反例", "调用方明确标注为 validation 的有界评估反馈；不接收 test", "snippets", feedback),
}
