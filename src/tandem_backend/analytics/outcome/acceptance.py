"""Match upstream acceptance criteria against task, artifact and version evidence."""

from collections import Counter, defaultdict

from ..common import annotation_visible, human, task_uid, timestamp
from .rules import VALIDATION_KINDS, _scope_equal


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
            elif (len({v["session_uid"] for v in matched}) == 1
                  and all(isinstance(v.get("result_seq"), int) for v in matched)):
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
