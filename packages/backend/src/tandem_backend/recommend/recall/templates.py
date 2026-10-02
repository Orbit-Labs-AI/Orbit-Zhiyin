"""Route ⑥ (RC-16): workflow templates triggered by cross-problem predicates."""

from .kb_route import from_rule

MIXED_TASKS, MIXED_SHARE = 3, .3


def _active(problems, *types) -> list[dict]:
    return [p for p in problems if p["type"] in types and p["status"] == "active"]


def _mixed_share(inputs: dict) -> float:
    """Share of sessions touching >= 3 distinct task kinds; 0 when the data is unavailable."""
    days = inputs.get("facts", {}).get("session_days") or []
    counts = [day["tasks"] if isinstance(day.get("tasks"), int) else len(set(day["task_types"]))
              for day in days if isinstance(day.get("tasks"), int) or day.get("task_types") is not None]
    if not counts:
        return 0.
    return sum(count >= MIXED_TASKS for count in counts) / len(counts)


def predicate(name: str, problems: list[dict], inputs: dict) -> list[dict]:
    """Problems that satisfy the predicate (strongest first); empty means false."""
    if name == "verification_gap":
        return _active(problems, "missing_verification", "buggy_output")
    if name == "correction_spiral":
        return _active(problems, "wrong_approach")
    if name == "mixed_sessions":
        return _active(problems, "wrong_approach") if _mixed_share(inputs) >= MIXED_SHARE else []
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
        rows.append((key, round(.6 + .1 * min(len(matched), 4), 4)))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows, payload
