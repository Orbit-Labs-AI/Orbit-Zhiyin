"""Route ⑥ (RC-16): workflow templates triggered by cross-problem predicates."""

import hashlib

from ..problems import MIN_SESSIONS, MIN_WILSON_LO, observed_weeks, wilson_lo
from .kb_route import from_rule

MIXED_TASKS, MIXED_SHARE = 3, .3
MIXED_REASON = "{k} 个会话同时处理 ≥3 类任务（占 {share}%），任务之间容易互相干扰。"


def _active(problems, *types) -> list[dict]:
    return [p for p in problems if p["type"] in types and p["status"] == "active"]


def _task_count(day: dict) -> int:
    count = day["tasks"] if isinstance(day.get("tasks"), int) else 0
    return max(count, len(set(day.get("task_types") or ())))


def _mixed_roots(inputs: dict) -> tuple[list[str], int]:
    """Main sessions touching >= 3 distinct task kinds, and the denominator (all main sessions).

    Sessions without task data count in the denominator, so missing data never inflates the share."""
    days = (inputs.get("facts") or {}).get("session_days") or []
    if not any(isinstance(day.get("tasks"), int) or day.get("task_types") is not None for day in days):
        return [], 0
    n = max(int((inputs.get("sessions") or {}).get("main") or 0), len(days))
    return [day["session_uid"] for day in days if _task_count(day) >= MIXED_TASKS], n


def _mixed_recurs(inputs: dict) -> bool:
    roots, n = _mixed_roots(inputs)
    k = len(roots)
    return k >= MIN_SESSIONS and (k / n >= MIXED_SHARE or wilson_lo(k, n) >= MIN_WILSON_LO)


def _mixed_problem(inputs: dict) -> dict:
    """Problem-shaped evidence for the template when no correction problem backs it."""
    roots, n = _mixed_roots(inputs)
    k, weeks = len(roots), observed_weeks(inputs.get("sessions") or {})
    lo, weekly = wilson_lo(k, n), round(k / weeks, 2)
    key = "mixed_sessions:tasks"
    return {
        "problem_id": hashlib.sha256(f"{inputs.get('scope_hash') or ''}|mixed_sessions|{key}".encode()
                                     ).hexdigest()[:16],
        "type": "mixed_sessions", "key": key, "dimension": None, "sessions": k, "denominator": n,
        "wilson_lo": round(lo, 4), "weekly_count": weekly, "unit": "会话", "status": "active",
        "evidence": {"session_uids": roots[:50], "signal_ids": [], "event_ids": []},
        "reason": MIXED_REASON.format(k=k, share=round(100 * k / n)), "scene": None, "language": None,
        "project_ids": [], "basis": "sql_fact",
        "vars": {"k": k, "n": n, "weekly": round(weekly, 1), "share": round(100 * k / n)},
    }


def predicate(name: str, problems: list[dict], inputs: dict) -> list[dict]:
    """Problems that satisfy the predicate (strongest first); empty means false."""
    if name == "verification_gap":
        return _active(problems, "missing_verification", "buggy_output")
    if name == "correction_spiral":
        return _active(problems, "wrong_approach")
    if name == "mixed_sessions":
        if not _mixed_recurs(inputs):
            return []
        return _active(problems, "wrong_approach") or [_mixed_problem(inputs)]
    return []


def recall(problems: list[dict], rules, inputs: dict, memory: dict) -> tuple[list, dict]:
    muted = set(memory.get("muted_kb_rules") or ())
    rows, payload = [], {}
    for rule in rules:
        if not rule.predicate or rule.id in muted:
            continue
        matched = predicate(rule.predicate, problems, inputs)
        if not matched:
            continue
        problem = max(matched, key=lambda p: (p["weekly_count"], p["key"]))
        key = f"template:{rule.id}"
        payload[key] = from_rule(rule, problem, inputs, rec_key=key, match_basis="template", origin="template")
        payload[key]["explain_hints"]["predicate"] = rule.predicate
        if problem["type"] == "mixed_sessions":
            payload[key]["explain_hints"]["reason_template"] = MIXED_REASON
        rows.append((key, round(.6 + .1 * min(len(matched), 4), 4)))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows, payload
