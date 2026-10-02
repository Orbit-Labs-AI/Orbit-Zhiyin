"""Template explanations and A7-shaped UI cards (RC-15). No model calls.

`explain()` fills the KB sentences with problem facts; a sentence that cannot be
filled, or that fails the readability checker, falls back to a plain count.
`ui()` returns the fields `46-a7-recs.js` binds (RECS in 05-data.js) plus the REC_X
numbers (`save` / `tok` / `n`), so every surface reads cards straight from the backend.
"""

import re
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
WEEKS_PER_MONTH = 4.345
# Subtraction cards: minutes a resident token costs per session (reading/latency), tunable.
TOKEN_MINUTES = .00005
TRIAL_FALLBACK = "下次遇到同类情况时观察是否改善，7 天后看效果追踪"
_RC = re.compile(r"（?RC-\d+[^）)]*[）)]?")
METRIC_ZH = {"approvals_per_week": "每周审批次数", "would_prompt_count": "每周审批次数",
             "retry_segments": "重复失败序列", "correction_count": "纠偏次数", "resident_tokens": "每会话常驻 tokens",
             "rework_count": "返工次数", "session_minutes": "会话时长", "friction_rate": "相关会话摩擦率",
             "readonly_prompts": "只读命令审批次数", "tool_failures_per_session": "每会话工具失败次数",
             "session_count": "会话数", "invocations": "调用次数", "使用次数": "使用次数"}
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




def clean(text) -> str:
    """User-visible text without internal plan ids such as「（RC-06 第 1 行）」."""
    return _RC.sub("", str(text)).strip() if text else ""


def _filled(template: str | None, values: dict) -> str | None:
    """Fill ``{var}`` slots; None when a slot stays unfilled (never leak a template)."""
    if not template:
        return ""
    text = _fill(template, values)
    return None if text is None or "{" in text else clean(text)


def audience_default(kind: str | None, level: int) -> int:
    """Audience floor when neither the KB nor the catalog says (0 新手 · 1 熟练 · 2 进阶)."""
    aud = 1 if (kind in ("hook", "skill") and level >= 2) or kind in ("mcp", "plugin", "subagent") else 0
    return 2 if level >= 4 else aud


def generic_reason(problem: dict) -> str:
    return f"{problem.get('sessions', 0)} 个会话出现「{TYPE_ZH.get(problem.get('type'), problem.get('type'))}」"


def _values(raw: dict, problem: dict | None) -> dict:
    hints = raw.get("explain_hints") or {}
    p = problem or {}
    values = {**(p.get("vars") or {}), **(hints.get("vars") or {})}
    if problem:
        values.update(sessions=p.get("sessions", 0), weekly=p.get("weekly_count", 0),
                      denominator=p.get("denominator", 0))
    return values


def _trial(raw: dict, problem: dict | None, values: dict) -> str:
    hints = raw.get("explain_hints") or {}
    if hints.get("trial"):
        return _filled(hints["trial"], values) or TRIAL_FALLBACK
    item = raw.get("item") or {}
    if (raw.get("source") or {}).get("origin") == "legacy" and item.get("id") and item.get("trial"):
        try:
            from .legacy import trial_method
            return clean(trial_method(item, {"scene": (problem or {}).get("scene"), "readers": []}))
        except (ImportError, KeyError, TypeError):
            return clean(item["trial"])
    trial = raw.get("trial")
    if isinstance(trial, dict):
        trial = trial.get("text") or "；".join(trial.get("steps") or [])
    return (_filled(trial, values) or TRIAL_FALLBACK) if trial else ""


def explain(raw: dict, problem: dict | None, gates: dict) -> dict:
    hints = raw.get("explain_hints") or {}
    values = _values(raw, problem)
    if problem:
        reason = _filled(hints.get("reason_template"), values) or generic_reason(problem)
        if not _readable(reason):
            reason = generic_reason(problem)
    else:
        reason = clean(raw.get("summary") or raw.get("title") or "")
    notes = [n for n in gates.get("notes", []) if n not in ACTION_NOTES]
    limitation = "；".join(clean(x) for x in [_filled(hints.get("limitation"), values), *notes] if x)
    return {"reason": reason, "mechanism": _filled(hints.get("mechanism"), values) or "",
            "capability": clean(raw.get("summary")), "trial": _trial(raw, problem, values),
            "limitation": limitation, "source": "template"}


def _used_agents(inputs: dict) -> list[str]:
    agents = inputs.get("agents") or {}
    return [a for a, n in sorted(agents.items(), key=lambda kv: (-kv[1], kv[0])) if n]


def _compat(agents: dict, inputs: dict | None = None) -> str:
    """Support for the Agents this user actually runs; the rest of the matrix is noise here."""
    if agents.get("*") in {"native", "manual"}:
        return "所有 Agent"
    used = _used_agents(inputs or {})
    if not used:
        if len(agents) >= 3 and all(v in {"native", "manual"} for v in agents.values()):
            return "所有 Agent"
        used = list(agents)
    parts = []
    for agent in used:
        name, support = AGENT_NAME.get(agent, agent), agents.get(agent, "unknown")
        if support in {"native", "manual"}:
            parts.append(name)
        elif support != "unsupported":
            parts.append(f"转换给 {name}")
    return " · ".join(parts)


def _p(raw: dict) -> float:
    prior = raw.get("prior") or {}
    alpha, beta = float(prior.get("alpha") or 1), float(prior.get("beta") or 1)
    return alpha / (alpha + beta)


def _tokens(cand: dict, raw: dict) -> int:
    """Resident tokens a removal frees (rules files without a count: ~15 tokens per line)."""
    v = {**((raw.get("explain_hints") or {}).get("vars") or {}), **((cand.get("problem") or {}).get("vars") or {})}
    tokens = int(v.get("tokens") or 0) or int(v.get("lines") or 0) * 15
    return tokens or int((raw.get("cost") or {}).get("context_tokens") or 0)


def _num(x: float) -> float:
    return round(x) if x >= 10 else round(x, 1)


def _label(minutes: float) -> str:
    if minutes >= 60:
        return f"≈ {minutes / 60:.1f} h"
    return f"≈ {max(1, round(minutes)) if minutes > 0 else 0} min"


def _unit_text(raw: dict, problem: dict) -> str:
    unit = ((raw.get("kb") or {}).get("benefit") or {}).get("unit") or problem.get("unit") or "次"
    if unit in ("次", "会话") and problem.get("type") in TYPE_ZH:
        unit = f"{unit}「{TYPE_ZH[problem['type']]}」"
    return unit


def _save(cand: dict, raw: dict, inputs: dict) -> dict:
    """Minutes saved per month (estimate): events × minutes per event × prior effectiveness."""
    problem = cand.get("problem") or {}
    sessions = inputs.get("sessions") or {}
    weeks = max(1., float(sessions.get("weeks") or 1))
    if cand.get("kind") == "removal":
        tokens = _tokens(cand, raw)
        per_month = float(sessions.get("main") or problem.get("denominator") or 0) / weeks * WEEKS_PER_MONTH
        minutes = tokens * per_month * TOKEN_MINUTES
        return {"min_month": _num(minutes), "label": _label(minutes), "low": _num(minutes * .5),
                "high": _num(minutes * 1.5),
                "basis": f"每个会话常驻约 {tokens} tokens × 每月约 {round(per_month)} 个会话 × "
                         f"每 token {TOKEN_MINUTES:g} 分钟（估计）"}
    weekly = float(problem.get("weekly_count") or 0)
    if weekly <= 0:
        return {"min_month": 0, "label": "—", "low": 0, "high": 0, "basis": "没有可折算的问题证据"}
    p, unit_minutes = _p(raw), float(raw.get("unit_minutes") or 1)
    k, n, lo = problem.get("sessions") or 0, problem.get("denominator") or 0, problem.get("wilson_lo") or 0
    scale = min(1., lo / (k / n)) if k and n else 0.
    minutes = weekly * WEEKS_PER_MONTH * unit_minutes * p
    return {"min_month": _num(minutes), "label": _label(minutes),
            "low": _num(minutes * scale), "high": _num(weekly * WEEKS_PER_MONTH * unit_minutes),
            "basis": f"近 {weeks:.1f} 周共 {round(weekly * weeks)} {_unit_text(raw, problem)} × "
                     f"每次 {unit_minutes:g} 分钟 × 生效率 {round(p, 2):g}（估计）"}


def _gain(cand: dict, raw: dict) -> str:
    problem = cand.get("problem") or {}
    if cand.get("kind") == "removal":
        return f"−{_tokens(cand, raw)} 常驻 token"
    weekly = float(problem.get("weekly_count") or 0)
    if weekly <= 0:
        sessions = problem.get("sessions") or len((cand.get("evidence") or {}).get("session_uids") or [])
        return f"{sessions} 个会话出现"
    unit = ((raw.get("kb") or {}).get("benefit") or {}).get("unit") or problem.get("unit") or "次"
    return f"−{max(1, round(weekly * WEEKS_PER_MONTH * _p(raw)))} {unit} / 月"


def _tok(cand: dict, raw: dict) -> int:
    if cand.get("kind") == "removal":
        return -_tokens(cand, raw)
    return int((raw.get("cost") or {}).get("context_tokens") or 0)


def _primary(cand: dict, raw: dict) -> tuple[str, int]:
    """(button, level): the action decides the button, not the difficulty level alone."""
    kind, level = cand.get("kind"), cand.get("level") or 1
    file, path = raw.get("file") or [], (cand.get("target") or {}).get("path_hint")
    if kind == "permission_rule":
        return "一键应用", level
    if kind == "generate":
        return "交给 Agent 生成", level
    if kind in ("rule", "prompt") and file:
        return "复制片段", level
    if kind == "removal":
        return ("一键移除" if level <= 2 else "查看方案"), level
    if kind in ("workflow", "builtin") and not file and not path:
        return "查看教程", 4  # nothing to write: a how-to, shown as L4 everywhere
    if kind == "workflow" and file:
        return "复制片段", level
    if level >= 4:
        return "查看方案", level
    return "预览并安装", level


def _window(inputs: dict, days: int = 28) -> tuple[list[dict], float]:
    """session_days of the last ``days`` days (relative to the newest session) and its weeks."""
    rows = [d for d in (inputs.get("facts") or {}).get("session_days") or () if isinstance(d, dict)]
    stamps = [d["started_at"] for d in rows if isinstance(d.get("started_at"), (int, float))]
    if not stamps:
        return rows, 1.
    scale = 1000 if max(stamps) > 1e11 else 1
    last, span = max(stamps), days * 86400 * scale
    recent = [d for d in rows if isinstance(d.get("started_at"), (int, float)) and d["started_at"] >= last - span]
    first = min(d["started_at"] for d in recent)
    return recent, max(1., (last - first) / (7 * 86400 * scale))


def _guardrail(name: str, inputs: dict) -> tuple[float | None, str]:
    days, weeks = _window(inputs)
    if not days:
        return None, ""
    if name in ("会话摩擦率", "相关会话摩擦率"):
        return round(100 * sum(bool(d.get("problems")) for d in days) / len(days), 1), "%"
    if name in ("相关失败次数", "每会话工具失败次数"):
        return round(sum(int(d.get("tool_failures") or 0) for d in days) / len(days), 2), "次/会话"
    if name == "纠偏次数":
        return round(sum("wrong_approach" in (d.get("problems") or ()) for d in days) / weeks, 2), "会话/周"
    if name == "会话数":
        return round(len(days) / weeks, 2), "会话/周"
    return None, ""


def _metric_name(metric, values: dict) -> tuple[str, str]:
    if isinstance(metric, dict):
        return metric.get("name_zh") or METRIC_ZH.get(metric.get("name"), metric.get("name")), metric.get("unit", "")
    text = str(metric)
    if text in TYPE_ZH:
        return f"{TYPE_ZH[text]}次数", ""
    return METRIC_ZH.get(text) or _filled(text, values) or clean(text.split("{")[0]) or text, ""


def _track(cand: dict, raw: dict, inputs: dict) -> list:
    """Three rows (triggered, mechanical, guardrail): [name, baseline before install, after, unit]."""
    track, problem = cand.get("track") or {}, cand.get("problem") or {}
    values = _values(raw, problem or None)
    rows = []
    for key in ("triggered", "mechanical", "guardrail"):
        metric = track.get(key)
        if key == "triggered" and problem and metric in TYPE_ZH:
            metric = problem.get("type") or metric  # recall may have attached a stronger problem
        if not metric:
            continue
        name, unit = _metric_name(metric, values)
        base = None
        if key == "triggered" and problem:
            if cand.get("kind") == "removal":
                base, unit = _tokens(cand, raw), "tokens/会话"
            elif "比例" in name or "摩擦率" in name:
                days, _ = _window(inputs)
                hit = sum(problem.get("type") in (d.get("problems") or ()) for d in days)
                base, unit = (round(100 * hit / len(days), 1) if days else None), "%"
            else:
                base, unit = problem.get("weekly_count"), f"{problem.get('unit') or '次'}/周"
        elif key == "guardrail":
            base, guard_unit = _guardrail(name, inputs)
            unit = guard_unit or unit
        rows.append([name, base, None, unit])
    return rows


def _ev(cand: dict, sessions: int, uids: list) -> str:
    if cand.get("kind") == "removal":
        problem = cand.get("problem") or {}
        note = "均未调用" if problem.get("type") == "installed_unused" else "每次都加载"
        return f"{problem.get('sessions') or len(uids)} 个会话（{note}）"
    return f"{sessions} 个会话"


def _commands(steps: list, trial, raw: dict) -> list:
    """Copyable command per step (None where a step has none); [] when the card has none."""
    commands = (trial.get("commands") if isinstance(trial, dict) else None) or raw.get("commands") or []
    if not any(commands):
        return []
    commands = list(commands)[:len(steps)]
    return commands + [None] * (len(steps) - len(commands))


def ui(cand: dict, inputs: dict, raw: dict | None = None) -> dict:
    """A7 card fields; `raw` (the RawCand) supplies token counts the Cand no longer carries.

    Also settles the action level on ``cand`` (a tutorial with nothing to write is L4), so
    the stored ``level`` column and ``ui.lvl`` agree."""
    raw = raw or cand
    problem = cand.get("problem") or {}
    sessions = problem.get("sessions") or len((cand.get("evidence") or {}).get("session_uids") or [])
    uids = (cand.get("evidence") or {}).get("session_uids") or (problem.get("evidence") or {}).get("session_uids") or []
    trial = cand.get("trial")
    dim = cand.get("dim")
    primary, level = _primary(cand, raw)
    cand["level"] = level
    steps = list((trial.get("steps") if isinstance(trial, dict) else None) or raw.get("steps") or [])
    return {
        "dim": dim, "type": TYPE_LABEL.get(cand.get("kind"), cand.get("kind")),
        "icon": ICON.get(dim, "rule"), "lvl": level, "aud": cand.get("audience_min") or 0,
        "title": clean(cand.get("title")), "gain": _gain(cand, raw),
        "why": clean((cand.get("explain") or {}).get("reason")), "ev": _ev(cand, sessions, uids),
        "evq": {"session_uids": list(uids)}, "compat": _compat(cand.get("agents") or {}, inputs),
        "primary": primary, "target": (cand.get("target") or {}).get("path_hint") or "",
        "file": [list(line) for line in raw.get("file") or []],
        "steps": [clean(s) for s in steps],
        "commands": _commands(steps, trial, raw),
        "track": _track(cand, raw, inputs),
        "save": _save(cand, raw, inputs), "tok": _tok(cand, raw),
        "n": [problem.get("denominator") if problem else None, None],
    }
