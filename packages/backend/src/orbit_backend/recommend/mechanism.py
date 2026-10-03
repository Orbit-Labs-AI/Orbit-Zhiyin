"""RC-06 mechanism table: which kind of change to try first for each problem type.

The order encodes reliability per cost: e.g. permission friction is solved by
a permission rule before a hook, and resident cost can only be subtracted.
"""

REMEDY_PRIORITY: dict[str, list[str]] = {
    "permission_friction": ["permission_rule", "builtin", "hook"],
    "tool_env_failure": ["hook", "skill", "rule", "builtin"],
    "communication_gap": ["skill", "rule", "prompt"],
    "repeated_instruction": ["rule", "hook", "prompt"],
    "missing_verification": ["rule", "hook", "subagent", "workflow"],
    "buggy_output": ["skill", "subagent", "prompt", "workflow"],
    "wrong_approach": ["prompt", "rule", "workflow"],
    "resident_cost": ["removal"],
    "context_loss": ["rule", "skill", "workflow"],
    "installed_unused": ["removal"],
    "repeated_workflow": ["skill", "plugin", "subagent"],
    "review_loop": ["skill", "rule", "subagent"],
    "parallel_conflict": ["workflow", "rule"],
    "readonly_review": ["subagent", "model", "rule"],
    "late_build_failure": ["hook", "rule", "skill"],
    "polling": ["workflow", "hook"],
    "deploy_platform_mix": ["rule", "prompt"],
    "high_effort_readonly": ["model"],  # model route only (recall/models.py), never a problem
}

# RC-06 rows implemented for the MVP; other types use the default order (row 0).
_ROWS = {
    "repeated_instruction": (1, "重复指令首选写进规则文件"),
    "wrong_approach": (11, "方向问题默认不装东西，先改开场与工作方式"),
    "resident_cost": (12, "常驻成本只能做减法"),
    "permission_friction": (13, "权限摩擦先用权限规则，只放行只读命令"),
    "review_loop": (14, "review 来回拉锯先用 skill 约定轮数和修复范围"),
    "parallel_conflict": (15, "并行会话冲突先改工作方式，用独立工作区隔开"),
    "readonly_review": (16, "只读审查交给只读子代理，主会话保持干净"),
    "late_build_failure": (17, "改完才发现构建失败，用项目级 hook 在编辑后自动构建"),
    "polling": (18, "反复手动查看进度，改成无人值守的定时任务"),
    "deploy_platform_mix": (19, "部署目标不统一，先写进项目规则"),
}


def _installed_rule_for(problem: dict, memory: dict, rules) -> bool:
    """True when a KB rule of kind 'rule' for this problem is already installed."""
    kinds = {rule.id: rule for rule in rules or ()
             if rule.remedy.kind == "rule" and problem["type"] in rule.problem.types}
    for rec_key, state in (memory.get("state") or {}).items():
        if state.get("status") != "installed" or not rec_key.startswith("kb:"):
            continue
        rule_id, _, key = rec_key[3:].partition("@")
        if rule_id in kinds and (not key or key == problem["key"]):
            return True
    return False


def choose(problem: dict, memory: dict, inventory=None, rules=None) -> dict:
    """Return {kinds, row, note}; row 2 escalates to a hook when a rule did not help."""
    kinds = list(REMEDY_PRIORITY.get(problem["type"], []))
    row, note = _ROWS.get(problem["type"], (0, "按默认机制优先序"))
    if problem.get("status") == "active" and "hook" in kinds and _installed_rule_for(problem, memory, rules):
        kinds.remove("hook")
        kinds.insert(0, "hook")
        row, note = 2, "已装规则后问题仍在，升级为执行层 hook"
    return {"kinds": kinds, "row": row, "note": note}


def weight(kind: str, choice: dict) -> float:
    """1.0 for the first-choice kind, minus 0.1 per position; 0.5 if not listed."""
    kinds = choice["kinds"]
    return max(.1, 1 - .1 * kinds.index(kind)) if kind in kinds else .5
