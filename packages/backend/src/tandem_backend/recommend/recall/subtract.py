"""Route ⑤ (RC-07): subtraction — trim resident context and disable unused components."""

from .kb_route import from_rule

DIM_BY_TYPE = {"rule": "rule", "skill": "skill", "mcp": "mcp", "plugin": "mcp", "hook": "hook"}


def recall(problems: list[dict], rules, inputs: dict, memory: dict) -> tuple[list, dict]:
    by_id = {rule.id: rule for rule in rules}
    muted = set(memory.get("muted_kb_rules") or ())
    rows, payload = [], {}
    for problem in problems:
        if problem["type"] not in ("resident_cost", "installed_unused") or problem["status"] == "insufficient":
            continue
        v = problem["vars"]
        split = problem["key"].startswith("resident_cost:rules_file")
        rule_id = "split-rules-file" if split else "trim-resident" if problem["type"] == "resident_cost" else "disable-unused"
        rule = by_id.get(rule_id)
        if rule is None or rule_id in muted:
            continue
        key = f"removal:{v.get('inv_id') or problem['key']}"
        if key in payload:
            continue
        cand = from_rule(rule, problem, inputs, rec_key=key, match_basis="inventory_fact", origin="inventory")
        name = v.get("name") or v.get("inv_id")
        if split:
            title = f"精简 {name}（{v.get('lines', 0)} 行，建议拆分到子目录）"
        elif problem["type"] == "installed_unused":
            title = f"停用 {v.get('days', 14)} 天未用的 {str(v.get('inv_type') or '组件').upper()} {name}"
        else:
            title = f"精简常驻内容 {name}（约 {v.get('tokens', 0)} tokens）"
        cand.update({"title": title, "dim": DIM_BY_TYPE.get(v.get("inv_type"), "rule"), "level": 3 if split else 2,
                     "unit_minutes": round(int(v.get("tokens") or 0) / 1000 * .2, 4)})
        cand["target"].update({"path_hint": v.get("config_path"), "scope": "user", "project_id": None})
        cand["source"]["item_id"] = v.get("inv_id") or rule.id
        payload[key] = cand
        rows.append((key, 1. if problem["status"] == "active" else .5))
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows, payload
