"""Template explanations and A7-shaped UI cards (RC-15). No model calls.

`explain()` fills the KB sentence with problem facts; a sentence that cannot be
filled, or that fails the readability checker, falls back to a plain count.
`ui()` returns exactly the fields `46-a7-recs.js` binds (RECS in 05-data.js).
"""

import string

TYPE_ZH = {
    "permission_friction": "只读命令反复弹审批", "tool_env_failure": "工具 / 环境失败",
    "communication_gap": "说明不清需返工", "repeated_instruction": "同一要求反复说明",
    "missing_verification": "改完没验证", "buggy_output": "验证反复失败",
    "correction": "方向纠偏", "wrong_approach": "方向纠偏", "misunderstood_request": "理解偏差",
    "excessive_changes": "改动过度", "resident_cost": "常驻上下文过大", "context_loss": "压缩后丢约定",
    "repeated_workflow": "重复的多步流程", "parallel_conflict": "并行会话冲突",
    "process_overhead": "旁支任务淹没主会话", "quota_interrupt": "撞到额度上限",
    "installed_unused": "已装未用", "quality_drop": "质量下滑",
    "review_loop": "PR review 来回拉锯", "readonly_review": "长时间只读审查", "late_build_failure": "改完才发现构建失败",
    "polling": "反复手动查看进度", "deploy_platform_mix": "部署平台混用",
}
TYPE_LABEL = {"rule": "规则", "prompt": "Prompt", "skill": "Skill", "hook": "Hook", "permission_rule": "Hook",
              "builtin": "内置功能", "mcp": "MCP", "plugin": "插件", "subagent": "子代理", "model": "模型与思考",
              "workflow": "工作流", "removal": "精简", "generate": "AI 草稿"}
ICON = {"rule": "rule", "skill": "book", "hook": "bolt", "mcp": "plug", "agent": "bot", "model": "gauge",
        "flow": "flow"}
AGENT_NAME = {"claude_code": "Claude Code", "codex": "Codex", "gemini": "Gemini CLI", "pi": "Pi",
              "opencode": "OpenCode", "hermes": "Hermes"}
PRIMARY = {1: "一键应用", 2: "预览并安装", 3: "查看步骤", 4: "查看方案"}
METRIC_ZH = {"approvals_per_week": "每周审批次数", "would_prompt_count": "每周审批次数",
             "retry_segments": "重复失败序列", "correction_count": "纠偏次数", "resident_tokens": "每会话常驻 tokens",
             "rework_count": "返工次数", "session_minutes": "会话时长", "friction_rate": "相关会话摩擦率"}
ACTION_NOTES = {"needs_context", "未扣除已装项"}

_formatter = string.Formatter()
_text_check = None


def _fill(template: str, values: dict) -> str | None:
    try:
        fields = {f for _, f, _, _ in _formatter.parse(template) if f}
        if not fields <= values.keys():
            return None
        return template.format(**values)
    except (ValueError, IndexError, KeyError, AttributeError):
        return None


def _readable(text: str) -> bool:
    """Lazy readability check (evaluation module); missing checker counts as readable."""
    global _text_check
    if _text_check is None:
        try:
            from ..evaluation.readability import evaluate_text
            _text_check = evaluate_text
        except ImportError:
            _text_check = False
    if not _text_check:
        return True
    issues = _text_check(text, "recommendation").get("issues", [])
    return not any(i.get("severity") == "error" for i in issues)


def generic_reason(problem: dict) -> str:
    return f"{problem.get('sessions', 0)} 个会话出现「{TYPE_ZH.get(problem.get('type'), problem.get('type'))}」"


def _trial(raw: dict, problem: dict | None) -> str:
    hints = raw.get("explain_hints") or {}
    if hints.get("trial"):
        return hints["trial"]
    item = raw.get("item") or {}
    if (raw.get("source") or {}).get("origin") == "legacy" and item.get("id") and item.get("trial"):
        try:
            from .legacy import trial_method
            return trial_method(item, {"scene": (problem or {}).get("scene"), "readers": []})
        except (ImportError, KeyError, TypeError):
            return item["trial"]
    trial = raw.get("trial")
    if isinstance(trial, dict):
        return trial.get("text") or "；".join(trial.get("steps") or [])
    return trial or ""


def explain(raw: dict, problem: dict | None, gates: dict) -> dict:
    hints = raw.get("explain_hints") or {}
    if problem:
        values = {**(problem.get("vars") or {}), **(hints.get("vars") or {}),
                  "sessions": problem.get("sessions", 0), "weekly": problem.get("weekly_count", 0),
                  "denominator": problem.get("denominator", 0)}
        reason = _fill(hints.get("reason_template") or "", values) or generic_reason(problem)
        if not _readable(reason):
            reason = generic_reason(problem)
    else:
        reason = raw.get("summary") or raw.get("title") or ""
    notes = [n for n in gates.get("notes", []) if n not in ACTION_NOTES]
    limitation = "；".join(x for x in [hints.get("limitation"), *notes] if x)
    return {"reason": reason, "mechanism": hints.get("mechanism") or "", "capability": raw.get("summary") or "",
            "trial": _trial(raw, problem), "limitation": limitation, "source": "template"}


def _compat(agents: dict) -> str:
    if agents.get("*") in {"native", "manual"} or (len(agents) >= 3 and all(
            v in {"native", "manual"} for v in agents.values())):
        return "所有 Agent"
    parts = []
    for agent, support in agents.items():
        name = AGENT_NAME.get(agent, agent)
        if support in {"native", "manual"}:
            parts.append(name)
        elif support == "adaptation_required":
            parts.append(f"转换给 {name}")
    return " · ".join(parts)


def _gain(cand: dict, raw: dict) -> str:
    problem = cand.get("problem") or {}
    sessions = problem.get("sessions") or len((cand.get("evidence") or {}).get("session_uids") or [])
    if cand.get("kind") == "permission_rule" or problem.get("type") == "permission_friction":
        return f"−{(problem.get('weekly_count') or 0) * 4:.0f} 次审批 / 月"
    if cand.get("kind") == "removal":
        tokens = ((problem.get("vars") or {}).get("tokens") or ((raw.get("explain_hints") or {}).get("vars") or {})
                  .get("tokens") or (raw.get("cost") or {}).get("context_tokens") or 0)
        return f"−{tokens} 常驻 token"
    return f"{sessions} 个会话出现"


def _primary(cand: dict) -> str:
    kind, level = cand.get("kind"), cand.get("level") or 1
    if kind == "generate":
        return "生成草稿"
    if kind in {"rule", "prompt"} and level == 1:
        return "复制片段"
    if kind == "removal" and level == 1:
        return "一键移除"
    return PRIMARY.get(level, "查看方案")


def _track(track: dict | None) -> list:
    rows = []
    for key in ("mechanical", "guardrail"):
        metric = (track or {}).get(key)
        if isinstance(metric, dict):
            rows.append([metric.get("name_zh") or METRIC_ZH.get(metric.get("name"), metric.get("name")),
                         None, None, metric.get("unit", "")])
        elif metric:
            rows.append([METRIC_ZH.get(metric, metric), None, None, ""])
    return rows


def _commands(steps: list, trial, raw: dict) -> list:
    """Copyable command per step (None where a step has none); [] when the card has none."""
    commands = (trial.get("commands") if isinstance(trial, dict) else None) or raw.get("commands") or []
    if not any(commands):
        return []
    commands = list(commands)[:len(steps)]
    return commands + [None] * (len(steps) - len(commands))


def ui(cand: dict, inputs: dict, raw: dict | None = None) -> dict:
    """A7 card fields; `raw` (the RawCand) supplies token counts the Cand no longer carries."""
    raw = raw or cand
    problem = cand.get("problem") or {}
    sessions = problem.get("sessions") or len((cand.get("evidence") or {}).get("session_uids") or [])
    uids = (cand.get("evidence") or {}).get("session_uids") or (problem.get("evidence") or {}).get("session_uids") or []
    trial = cand.get("trial")
    dim = cand.get("dim")
    steps = list((trial.get("steps") if isinstance(trial, dict) else None) or raw.get("steps") or [])
    return {
        "dim": dim, "type": TYPE_LABEL.get(cand.get("kind"), cand.get("kind")),
        "icon": ICON.get(dim, "rule"), "lvl": cand.get("level") or 1, "aud": cand.get("audience_min") or 0,
        "title": cand.get("title") or "", "gain": _gain(cand, raw),
        "why": (cand.get("explain") or {}).get("reason") or "", "ev": f"{sessions} 个会话",
        "evq": {"session_uids": list(uids)}, "compat": _compat(cand.get("agents") or {}),
        "primary": _primary(cand), "target": (cand.get("target") or {}).get("path_hint") or "",
        "file": [list(line) for line in raw.get("file") or []],
        "steps": steps,
        "commands": _commands(steps, trial, raw),
        "track": _track(cand.get("track")),
    }
