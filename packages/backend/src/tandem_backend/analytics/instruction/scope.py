"""Task-local instruction history with explicit replacement and conservative conflicts."""

from itertools import product


def resolve_instruction_scope(instructions, task, at=None):
    """Resolve a single explicit (session_uid, task_id) through inclusive UTC-ms at.

    A later message alone never revokes an earlier rule. Unknown scope/time,
    conditional requirements and incompatible rules remain unresolved.
    """
    if not isinstance(task, dict) or not task.get("session_uid") or not task.get("task_id"):
        raise ValueError("task 必须包含明确的 session_uid 和 task_id")
    if at is not None and (not isinstance(at, int) or isinstance(at, bool)):
        raise ValueError("at 必须是 UTC 毫秒整数")
    history, unresolved, invalid_replacements = {}, [], []
    for row in sorted(instructions, key=lambda r: (r["seq"], r["event_uid"])):
        if row["session_uid"] != task["session_uid"]:
            continue
        if not row["constraints"] and not row.get("supersedes_instruction_ids"):
            continue  # A greeting/unknown observation is not an unresolved instruction.
        if row.get("task_id") not in (None, task["task_id"]):
            continue
        if at is not None and row.get("ts") is not None and row["ts"] > at:
            continue
        reason = ("task_unknown" if row.get("task_id") is None else
                  "time_unknown" if at is not None and row.get("ts") is None else None)
        if reason:
            unresolved.append({"event_uid": row["event_uid"], "reason": reason})
            continue
        inferred = [c for c in row["constraints"] if c.get("source") == "semantic_model"]
        unresolved.extend({"constraint_uid": c["constraint_uid"], "reason": "model_inference_not_execution_authority"}
                          for c in inferred)
        incoming = [c for c in row["constraints"] if c.get("source") != "semantic_model"]
        for uid in row.get("supersedes_instruction_ids", []):
            prior = history.get(uid)
            replacement = next((c for c in incoming if prior
                                and c["feature"] == prior["feature"]
                                and c["targets"] == prior["targets"]
                                and c["condition"] == prior["condition"]), None)
            if prior and replacement and prior["seq"] < row["seq"]:
                prior["state"] = "superseded"
                prior["superseded_by"] = replacement["constraint_uid"]
            else:
                invalid_replacements.append(uid)
        for constraint in incoming:
            history[constraint["constraint_uid"]] = {**constraint, "state": "candidate"}

    groups = {}
    for item in history.values():
        if item["state"] == "superseded":
            continue
        if item["condition"]:
            item["state"] = "conditional"
            unresolved.append({"constraint_uid": item["constraint_uid"], "reason": "condition_not_evaluated"})
            continue
        key = (item["feature"], item["value"], item["action"], tuple(item["targets"] or []))
        groups.setdefault(key, []).append(item)
    conflicts = []
    buckets = {}
    for key, items in groups.items():
        buckets.setdefault(key[0], []).append((key, items))
    pairs = [
        ([g for g in buckets.get("requested_autonomy", []) if g[0][1] == "ask_first"],
         [g for g in buckets.get("requested_autonomy", []) if g[0][1] == "explicit"]),
        ([g for g in buckets.get("execution_order", []) if g[0][1] == "execute_first"],
         [g for g in buckets.get("execution_order", []) if g[0][1] != "execute_first"]),
        (buckets.get("allowed_scope", []), buckets.get("prohibited_actions", [])),
        (buckets.get("verification_requirements", []), buckets.get("prohibited_actions", [])),
    ]
    for left_groups, right_groups in pairs:
        for (a, left), (b, right) in product(left_groups, right_groups):
            targets_overlap = not a[3] or not b[3] or bool(set(a[3]) & set(b[3]))
            same_action = a[0] == b[0] or a[2] is not None and a[2] == b[2]
            if targets_overlap and same_action:
                ids = [c["constraint_uid"] for c in left + right]
                conflicts.append({"constraint_uids": ids, "reason": "incompatible_explicit_requirements"})
                for item in left + right:
                    item["state"] = "conflict"
    for item in history.values():
        if item["state"] == "candidate":
            item["state"] = "active"
    return {
        "task": dict(task), "at": at, "time_boundary": "inclusive UTC milliseconds",
        "active": [c for c in history.values() if c["state"] == "active"],
        "history": list(history.values()), "conflicts": conflicts, "unresolved": unresolved,
        "invalid_replacements": invalid_replacements,
        "status": "needs_confirmation" if conflicts or unresolved or invalid_replacements else "resolved" if history else "unknown",
    }
