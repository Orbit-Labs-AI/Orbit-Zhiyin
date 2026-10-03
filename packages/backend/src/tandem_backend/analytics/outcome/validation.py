"""Executed validation evidence, scoped results and legacy command candidates."""

import re

from ...models import stable_id
from ..common import annotation_visible, timestamp
from ..respond import result_status
from .rules import COMMAND_SCOPES, RESULTS, VALIDATION_KINDS, _command_kind, _scope_equal


def legacy_objective_candidates(calls):
    """Keep the v1 candidate fields; these never establish task success."""
    return {"explicit_tool_failures": sum(c.get("status") == "failed" for c in calls) if calls is not None else None,
                 "validation_command_candidates": sum(bool(re.search(r"\b(test|pytest|lint|typecheck|build)\b", c.get("command_head") or "")) for c in calls or []),
                 "task_success": None, "validation_scope": None}


def extract_validation_runs(calls, until_ts=None):
    runs, candidates, unknown = [], [], 0
    for c in calls or []:
        meta = c.get("validation") or {}
        declared = (meta.get("kind") in VALIDATION_KINDS and meta.get("executed") is True
                    and bool(meta.get("source")) and annotation_visible(meta, until_ts))
        inferred = _command_kind(c) if (c.get("result_event_uid") and c.get("status_scope") in COMMAND_SCOPES) else None
        if result_status(c) == "rejected":
            declared, inferred = False, None
        kind = meta["kind"] if declared else inferred
        if kind is None:
            if re.search(r"\b(test|pytest|lint|typecheck|build|check)\b", c.get("command_head") or "", re.I) or meta:
                candidates.append({"call_uid": c["call_uid"], "session_uid": c["session_uid"],
                                   "call_event_uid": c.get("call_event_uid"),
                                   "reason": "no_confirmed_validation_execution"})
            else:
                unknown += 1
            continue
        spec = c.get("command_spec") or {}
        scope = meta.get("scope") if declared else c.get("validation_scope", spec.get("validation_scope"))
        available = c.get("result_available_at", c.get("ended_at"))
        visible = until_ts is None or (timestamp(available) and available < until_ts)
        result, reason, report_id = "unknown", "missing_or_unscoped_result", None
        report = c.get("validation_result") or {}
        if (report.get("status") in RESULTS and report.get("source") and report.get("report_uid")
                and report.get("call_uid") == c["call_uid"] and _scope_equal(report.get("scope"), scope)
                and annotation_visible(report, until_ts) and c.get("pairing_status") != "conflict"):
            result, reason, report_id = report["status"], None, report["report_uid"]
            available = report.get("available_at")
        elif (visible and c.get("result_event_uid") and c.get("status_scope") in COMMAND_SCOPES
              and not c.get("is_wrapper") and c.get("pairing_status") != "conflict"):
            result = {"success": "passed", "failed": "failed", "interrupted": "interrupted"}.get(result_status(c), "unknown")
            reason = None if result != "unknown" else "protocol_result_unknown_or_not_executed"
        elif not visible:
            reason = "result_not_visible_at_cutoff"
        elif c.get("is_wrapper") or c.get("status_scope") not in COMMAND_SCOPES:
            reason = "outer_or_unknown_status_scope"
        # A later annotation can identify the check/scope only when it exists.
        # The result timestamp alone must not backdate that relationship.
        if declared:
            available = max(available, meta["available_at"]) if timestamp(available) and timestamp(meta.get("available_at")) else None
        runs.append({"validation_uid": stable_id(c["session_uid"], c["call_uid"], "validation"),
                     "session_uid": c["session_uid"], "call_uid": c["call_uid"],
                     "task_uid": c.get("task_uid"), "root_session_uid": c.get("root_session_uid"), "kind": kind,
                     "task_identity_quality": c.get("task_identity_quality", "explicit"),
                     "check_name": meta.get("check_name") if declared else
                         " ".join(str(v) for v in (spec.get("executable"), spec.get("subcommand")) if v)
                         or c.get("command_head"),
                     "validation_result": result, "validation_scope": scope,
                     "criterion_uids": meta.get("criterion_uids", []) if declared else [],
                     "validation_evidence": {"call_event_uid": c.get("call_event_uid"),
                         "result_event_uid": c.get("result_event_uid") if visible else None,
                         "report_uid": report_id, "artifact_revision": (scope or {}).get("artifact_revision")},
                     "available_at": available if visible or report_id else None,
                     "seq": c.get("seq"), "result_seq": c.get("result_seq"),
                     "status_scope": c.get("status_scope") if visible else None,
                     "raw_status": c.get("status") if visible else None,
                     "identification_source": meta.get("source") if declared else
                         "structured_command_spec" if spec else "complete_direct_command",
                     "missing_reason": reason})
    return {"validation_runs": runs if calls is not None else None,
            "validation_candidates": candidates if calls is not None else None,
            "unclassified_call_n": unknown if calls is not None else None}
