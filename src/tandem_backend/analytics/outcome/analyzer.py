"""Objective validation evidence, separate from subjective acceptance."""

import re
import shlex
from collections import Counter, defaultdict

from ...models import stable_id
from ..common import annotation_visible, human, task_uid, timestamp
from ..respond import result_status


def legacy_objective_candidates(calls):
    """Keep the v1 candidate fields; these never establish task success."""
    return {"explicit_tool_failures": sum(c.get("status") == "failed" for c in calls) if calls is not None else None,
                 "validation_command_candidates": sum(bool(re.search(r"\b(test|pytest|lint|typecheck|build)\b", c.get("command_head") or "")) for c in calls or []),
                 "task_success": None, "validation_scope": None}


VALIDATION_KINDS = {"test", "build", "check", "lint", "typecheck"}
RESULTS = {"passed", "failed", "interrupted", "unknown"}
COMMAND_SCOPES = {"command", "command_return", "command_transport"}
SCOPE_KEYS = {"project_id", "artifact_uid", "artifact_revision", "coverage"}


def _command_kind(call):
    """Recognize an explicitly complete direct command, never a mention/head only."""
    command = call.get("command_head") or ""
    if (call.get("command_complete") is not True or call.get("is_wrapper")
            or call.get("kind") != "shell" or re.search(r"[;&|<>`$\n]", command)):
        return None
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if not args or any(a in ("--help", "-h", "--version", "-V", "--collect-only", "--co", "--setup-only",
                            "--fixtures", "--fixtures-per-test", "--markers", "--no-run", "--list", "-list",
                            "--show-settings", "--show-files") for a in args):
        return None
    executable = args[0].replace("\\", "/").rsplit("/", 1)[-1]
    if executable == "pytest" or (executable in ("python", "python3") and args[1:3] == ["-m", "pytest"]):
        return "test"
    if executable == "ruff" and args[1:2] == ["check"]:
        return "lint"
    if executable == "mypy" or (executable == "tsc" and "--noEmit" in args):
        return "typecheck"
    if executable in ("cargo", "go") and len(args) > 1:
        return {"test": "test", "build": "build", "check": "check", "vet": "check"}.get(args[1])
    return None


def _scope_equal(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict) or not SCOPE_KEYS <= a.keys() or not SCOPE_KEYS <= b.keys():
        return False
    if any(not a[k] or not b[k] for k in SCOPE_KEYS):
        return False
    if a["coverage"] not in ("full", "subset") or b["coverage"] not in ("full", "subset"):
        return False
    if any(s["coverage"] == "subset" and not (s.get("files") or s.get("test_ids")) for s in (a, b)):
        return False
    # Exact coverage is conservative: no subset-to-full or version extrapolation.
    def normalized(scope):
        return {k: sorted(v) if isinstance(v, list) else v for k, v in scope.items()}
    return normalized(a) == normalized(b)


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
        scope = meta.get("scope") if declared else c.get("validation_scope")
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
        runs.append({"validation_uid": stable_id(c["session_uid"], c["call_uid"], "validation"),
                     "session_uid": c["session_uid"], "call_uid": c["call_uid"],
                     "task_uid": c.get("task_uid"), "root_session_uid": c.get("root_session_uid"), "kind": kind,
                     "check_name": meta.get("check_name") if declared else c.get("command_head"),
                     "validation_result": result, "validation_scope": scope,
                     "criterion_uids": meta.get("criterion_uids", []) if declared else [],
                     "validation_evidence": {"call_event_uid": c.get("call_event_uid"),
                         "result_event_uid": c.get("result_event_uid") if visible else None,
                         "report_uid": report_id, "artifact_revision": (scope or {}).get("artifact_revision")},
                     "available_at": available if visible or report_id else None,
                     "seq": c.get("seq"), "result_seq": c.get("result_seq"),
                     "status_scope": c.get("status_scope") if visible else None,
                     "raw_status": c.get("status") if visible else None,
                     "identification_source": meta.get("source") if declared else "complete_direct_command",
                     "missing_reason": reason})
    return {"validation_runs": runs if calls is not None else None,
            "validation_candidates": candidates if calls is not None else None,
            "unclassified_call_n": unknown if calls is not None else None}


def collect_acceptance_criteria(events, main_ids, until_ts=None):
    """Consume upstream Instruction labels. This module never invents criteria."""
    groups, unknown = {}, []
    for e in sorted(events or [], key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        block = e.get("attrs", {}).get("acceptance")
        if not block or not human(e, main_ids):
            continue
        criteria = block.get("criteria")
        valid = (block.get("state") == "confirmed" and block.get("source")
                 and block.get("criteria_set_uid") and task_uid(e) and annotation_visible(block, until_ts)
                 and isinstance(criteria, list) and bool(criteria)
                 and all(isinstance(c, dict) and c.get("criterion_uid") and c.get("kind") in VALIDATION_KINDS for c in criteria)
                 and len({c["criterion_uid"] for c in criteria}) == len(criteria))
        if not valid:
            unknown.append(e["event_uid"])
            continue
        key = (e["session_uid"], task_uid(e), block["criteria_set_uid"])
        groups[key] = [{**c, "session_uid": e["session_uid"], "task_uid": task_uid(e),
                        "criteria_set_uid": block["criteria_set_uid"], "scope": c.get("scope", block.get("scope")),
                        "set_complete": block.get("complete") is True, "source": block["source"],
                        "available_at": block.get("available_at"), "evidence_event_uid": e["event_uid"]} for c in criteria]
    return {"criteria": [c for group in groups.values() for c in group], "unusable_criteria_events": unknown}


def match_acceptance_criteria(criteria, validations):
    results = []
    for c in criteria:
        candidates = [v for v in validations or [] if c["criterion_uid"] in v["criterion_uids"]
                      and v.get("task_uid") == c["task_uid"] and v["kind"] == c["kind"]
                      and (v.get("root_session_uid") or v["session_uid"]) == c["session_uid"]]
        matched = [v for v in candidates if _scope_equal(c.get("scope"), v.get("validation_scope"))]
        # Result order, not invocation order, determines freshness. Without a
        # comparable clock/sequence, contradictory outcomes remain unknown.
        latest, reason = matched, "no_matching_validation"
        if matched:
            if all(timestamp(v.get("available_at")) for v in matched):
                last = max(v["available_at"] for v in matched)
                latest = [v for v in matched if v["available_at"] == last]
            elif all(isinstance(v.get("result_seq"), int) for v in matched):
                last = max(v["result_seq"] for v in matched)
                latest = [v for v in matched if v["result_seq"] == last]
            states = {v["validation_result"] for v in latest}
            state = next(iter(states)) if len(states) == 1 else "unknown"
            reason = None if state in ("passed", "failed") else "conflicting_incomplete_or_interrupted_evidence"
        else:
            state = "unknown"
            if candidates:
                reason = "scope_or_artifact_revision_mismatch"
        results.append({**c, "acceptance_result": state,
                        "validation_uids": [v["validation_uid"] for v in latest],
                        "available_at": max([c["available_at"], *[v["available_at"] for v in latest]])
                            if latest and timestamp(c.get("available_at")) and all(timestamp(v.get("available_at")) for v in latest) else None,
                        "missing_reason": reason})
    return results


def summarize_objective_outcomes(results):
    groups = defaultdict(list)
    for r in results:
        groups[(r["session_uid"], r["task_uid"], r["criteria_set_uid"])].append(r)
    tasks = []
    for (sid, task, criteria_set), rows in groups.items():
        states = {r["acceptance_result"] for r in rows}
        complete = all(r["set_complete"] for r in rows)
        success = (False if "failed" in states else True if states == {"passed"} else None) if complete else None
        tasks.append({"session_uid": sid, "task_uid": task, "criteria_set_uid": criteria_set,
                      "criteria_complete": complete, "task_success": success,
                      "meaning": "only the explicitly declared acceptance set",
                      "criterion_uids": [r["criterion_uid"] for r in rows]})
    known = sum(r["acceptance_result"] in ("passed", "failed") for r in results)
    return {"acceptance_counts": dict(Counter(r["acceptance_result"] for r in results)),
            "effective_n": known, "unknown_n": len(results) - known,
            "task_results": tasks, "task_success": tasks[0]["task_success"] if len(tasks) == 1 else None,
            "missing_reason": "no_explicit_acceptance_criteria" if not results else None}


def analyze_outcome(calls, events, main_ids, until_ts=None, dataset_status="available"):
    extracted = extract_validation_runs(calls, until_ts)
    criteria = collect_acceptance_criteria(events, main_ids, until_ts)
    accepted = match_acceptance_criteria(criteria["criteria"], extracted["validation_runs"])
    return {"status": dataset_status if calls is not None else "unavailable", "grain": "validation/criterion",
            **extracted, "acceptance_results": accepted,
            "unusable_criteria_events": criteria["unusable_criteria_events"],
            "validation_result_counts": dict(Counter(r["validation_result"] for r in extracted["validation_runs"] or [])) if calls is not None else None,
            **summarize_objective_outcomes(accepted)}
