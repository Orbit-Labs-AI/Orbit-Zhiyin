"""Template explanations and A7-shaped UI cards (RC-15). No model calls.

`explain()` fills the KB sentences with problem facts; a sentence that cannot be
filled, or that fails the readability checker, falls back to a plain count.
`ui()` returns the fields `46-a7-recs.js` binds (RECS in 05-data.js) plus the REC_X
numbers (`save` / `tok` / `tok_pct` / `n`), so every surface reads cards straight from the backend.
Savings are shares of the scope's real trajectory (tokens and active time), never hours.
"""

import re
import string

from .benefit import beta_interval
from .problems import observed_weeks

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
              "dsh": "DeepSeek Harness", "kimi": "Kimi CLI",
              "opencode": "OpenCode", "hermes": "Hermes"}
UNESTIMATED = "未估算"
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
    else:  # a Chinese template when the route gave one, else the item's own summary
        reason = _filled(hints.get("reason_template"), values) or clean(raw.get("summary") or raw.get("title") or "")
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
        elif support == "adaptation_required":
            parts.append(f"转换给 {name}")
        elif support == "unknown":  # e.g. Kimi: no upstream source read, never shown as compatible
            parts.append(f"{name} 未核实")
    return " · ".join(parts)


def _tokens(cand: dict, raw: dict) -> int:
    """Resident tokens a removal frees (rules files without a count: ~15 tokens per line)."""
    v = {**((raw.get("explain_hints") or {}).get("vars") or {}), **((cand.get("problem") or {}).get("vars") or {})}
    tokens = int(v.get("tokens") or 0) or int(v.get("lines") or 0) * 15
    return tokens or int((raw.get("cost") or {}).get("context_tokens") or 0)


# Problem type → the trajectory operation class one occurrence stands for (section._ledger):
# approvals only wait, failures (tool, test or build) are failed calls, polling and repeated
# workflows are tool calls; every other problem (correction, repeated instruction, compaction,
# review round …) costs about one user turn of rework. Removals free resident context instead.
OP_OF = {"permission_friction": "readonly", "tool_env_failure": "failed", "buggy_output": "failed",
         "late_build_failure": "failed", "polling": "call", "repeated_workflow": "call"}
OP_ZH = {"readonly": "只读审批等待", "failed": "失败的工具调用", "call": "工具调用", "turn": "返工轮次",
         "resident": "常驻上下文"}
REMOVAL_TYPES = {"resident_cost", "installed_unused"}


def pct_text(value: float | None) -> str:
    """0.04 →「<0.1%」, 3.21 →「3.2%」, 12.6 →「13%」."""
    if value is None:
        return "—"
    if value <= 0:
        return "0%"
    if value < .1:
        return "<0.1%"
    return f"{value:.1f}%" if value < 10 else f"{round(value)}%"


def save_label(time_pct: float | None, token_pct: float | None) -> str:
    parts = [f"省时 {pct_text(time_pct)}" if time_pct is not None else None,
             f"省 token {pct_text(token_pct)}" if token_pct is not None else None]
    return " · ".join(p for p in parts if p) or UNESTIMATED


def _unestimated(basis: str) -> dict:
    return {"time_pct": None, "token_pct": None, "time_range": None, "token_range": None,
            "share": None, "effect": None, "op": None, "key": None, "group": None, "cap": None,
            "label": UNESTIMATED, "basis": basis}


def _requests(ledger: dict, agents) -> int:
    """Requests of the agents a card targets (resident context is re-sent with each), else all."""
    by_agent = ledger.get("requests_by_agent") or {}
    picked = sum(int(by_agent.get(a) or 0) for a in agents or ())
    return picked or int(ledger.get("requests") or 0)


def _op_cost(cand: dict, raw: dict, problem: dict, ledger: dict, total: float) -> tuple | None:
    """(op class, tokens, ms, note, pool) the problem's ``total`` occurrences cost in this scope's
    trajectory; ms None = not measured. Per-occurrence cost is the measured mean of the class,
    capped at what the whole class (or the whole scope) cost. ``pool`` is the class whose
    measurements were actually used: an unmeasured class borrows the average tool call, and then
    its cost (and so its cap in ``total_saving``) comes from the tool-call pool."""
    if cand.get("kind") == "removal" or problem.get("type") in REMOVAL_TYPES:
        values = {**((raw.get("explain_hints") or {}).get("vars") or {}), **(problem.get("vars") or {})}
        resident = _tokens(cand, raw)
        requests = _requests(ledger, [values["agent"]] if values.get("agent") else ())
        if resident <= 0 or requests <= 0:
            return None
        guess = "（估计）" if values.get("tokens_basis") == "estimate" else ""
        return "resident", min(resident * requests, ledger.get("tokens") or 0), None, \
            f"每次请求常驻约 {resident} tokens{guess} × {requests} 次请求", "resident"
    if total <= 0:
        return None
    name = OP_OF.get(problem.get("type"), "turn")
    steps = max(1, int((problem.get("vars") or {}).get("n_steps") or 1)) if problem.get("type") == "repeated_workflow" else 1
    pool = name
    if name == "turn":
        n, tokens, ms, note = _turn_cost(problem, ledger)
    else:
        cls = (ledger.get("ops") or {}).get(name) or {}
        note = "逐次实测"
        if name == "readonly":
            # Approval waits are priced only from recorded waits (R8): the mean of the measured
            # prompts; none recorded → not estimated, never the run time or an average tool call.
            if not cls.get("n"):
                return None
            missing = int(cls.get("unmeasured") or 0)
            note = (f"按 {int(cls['n'])} 次实测审批等待的均值" + (f"，另 {missing} 次未记录等待" if missing else ""))
        elif not cls.get("n"):  # nothing of this class was timed: an average tool call stands in
            cls, note, pool = (ledger.get("ops") or {}).get("call") or {}, "按平均工具调用近似", "call"
        n, tokens, ms = int(cls.get("n") or 0), cls.get("tokens") or 0, cls.get("ms") or 0
    if n <= 0:
        return None
    count = total * steps
    if name == "turn":  # per-turn means of the measured turns, bounded by the whole trajectory
        all_tokens, all_ms = ledger.get("tokens") or 0, ledger.get("active_ms") or 0
        return name, min(count * tokens / n, all_tokens), min(count * ms / n, all_ms), note, pool
    op_tokens = 0 if name == "readonly" else min(count * tokens / n, tokens)
    return name, op_tokens, min(count * ms / n, ms), note, pool


def _turn_cost(problem: dict, ledger: dict) -> tuple[int, float, float, str]:
    """(turns, tokens, ms, note) whose mean prices one rework turn (R10), most specific first:
    the problem's own evidence turns, else the turns of the sessions it occurred in, else every
    turn of the scope. Each is the measured cost of those turns (section._turn_costs), never all
    tokens spread over the human turns of other sessions."""
    turn_cost = ledger.get("turn_cost") or {}
    evidence = problem.get("evidence") or {}
    by_event = turn_cost.get("by_event") or {}
    rows = [by_event[e] for e in evidence.get("event_ids") or () if e in by_event]
    if rows:
        return len(rows), sum(r[0] for r in rows), sum(r[1] for r in rows), f"按证据里 {len(rows)} 轮的实测成本"
    by_session = turn_cost.get("by_session") or {}
    rows = [by_session[u] for u in dict.fromkeys(evidence.get("session_uids") or ()) if u in by_session]
    if sum(r[0] for r in rows):
        return (sum(r[0] for r in rows), sum(r[1] for r in rows), sum(r[2] for r in rows),
                f"按问题所在 {len(rows)} 个会话每轮的实测成本")
    if by_session:
        rows = list(by_session.values())
        return sum(r[0] for r in rows), sum(r[1] for r in rows), sum(r[2] for r in rows), "按全部轮次每轮的实测成本"
    # Older ledgers without per-turn costs: the scope average, said as such.
    return (int(ledger.get("turns") or 0), ledger.get("tokens") or 0, ledger.get("active_ms") or 0,
            "按全部 token 与时长 ÷ 人类轮次的平均（旧账本）")


def _save(cand: dict, raw: dict, inputs: dict) -> dict:
    """Expected saving as shares of this scope's real trajectory, never extrapolated hours.

    The problem's operations cost op_tokens / op_ms (``_op_cost`` over ``facts.trajectory``);
    their share of all tokens / all active time is the 对应操作占比, and the expected saving is that
    share × the remedy's effectiveness (Beta prior mean; the range uses its ~90 % interval, a
    scenario bound, not a confidence interval). Alternatives on one problem share ``key`` and are
    not additive."""
    problem = cand.get("problem") or {}
    ledger = (inputs.get("facts") or {}).get("trajectory") or {}
    if cand.get("kind") == "model":
        return _unestimated("降低思考档位只影响推理 token，轨迹里没有可靠地分开记录推理 token，暂不折算")
    if not problem:
        return _unestimated("没有对应的问题证据，轨迹里找不到可折算的操作")
    if not ledger.get("tokens") and not ledger.get("active_ms"):
        return _unestimated("还没有轨迹账本（token 与协作时长），重新计算后按轨迹折算")
    sessions = inputs.get("sessions") or {}
    weeks = observed_weeks(sessions) if (sessions.get("weeks") or sessions.get("first_ts")) else 1.
    total = float(problem.get("weekly_count") or 0) * weeks
    cost = _op_cost(cand, raw, problem, ledger, total)
    if cost is None and OP_OF.get(problem.get("type")) == "readonly":
        return _unestimated("这些只读审批没有记录等待时长（approval_wait_ms 或审批请求到决定的间隔），不拿命令运行时长代替，暂不折算")
    if cost is None:
        return _unestimated("轨迹里没有可计量的对应操作")
    op, op_tokens, op_ms, note, pool = cost
    tokens, active = ledger.get("tokens") or 0, ledger.get("active_ms") or 0
    share_k = min(100., 100 * op_tokens / tokens) if tokens > 0 else None
    share_t = min(100., 100 * op_ms / active) if op_ms is not None and active > 0 else None
    # the pool whose measurements priced the share bounds it; a card's own share always fits its cap
    cap = _class_cap(pool, ledger)
    cap = (max(cap[0], round(share_t or 0., 4)), max(cap[1], round(share_k or 0., 4)))
    prior = raw.get("prior") or {}
    alpha, beta = float(prior.get("alpha") or 1), float(prior.get("beta") or 1)
    p, (lo, hi) = alpha / (alpha + beta), beta_interval(alpha, beta)

    def scaled(share, f):  # four decimals: a tiny positive share stays「<0.1%」, never rounds to「0%」
        return None if share is None else round(share * f, 4)

    time_pct, token_pct = scaled(share_t, p), scaled(share_k, p)
    span = f"近 {weeks:.1f} 周 {round(total)} {_unit_text(raw, problem)}（{note}）" if op != "resident" else note
    shares = "、".join(x for x in (f"时间 {pct_text(share_t)}" if share_t is not None else None,
                                  f"token {pct_text(share_k)}" if share_k is not None else None) if x)
    basis = (f"{OP_ZH[op]}：{span}，在全部轨迹里占{' ' if shares[:1].isascii() else ''}{shares}"
             f" × 生效率 {round(p, 2):g}（先验，区间 {lo:.2f}–{hi:.2f}）")
    if share_t is None:
        basis += "；常驻上下文的时间代价未实测，只按 token 计"
    return {"time_pct": time_pct, "token_pct": token_pct,
            "time_range": None if share_t is None else [scaled(share_t, lo), scaled(share_t, hi)],
            "token_range": None if share_k is None else [scaled(share_k, lo), scaled(share_k, hi)],
            "share": {"time": scaled(share_t, 1), "token": scaled(share_k, 1)}, "effect": round(p, 3),
            "op": op, "key": problem.get("key") or problem.get("problem_id"),
            "group": CAP_GROUP[pool], "cap": {"time": None if share_t is None else cap[0], "token": cap[1]},
            "label": save_label(time_pct, token_pct), "basis": basis}


# Operation classes that draw on the same part of the trajectory: failed calls are tool calls, so
# both are bounded by what all tool calls cost; approval waits, rework turns (bounded by all human
# turns, i.e. the whole trajectory) and resident context are their own pools.
CAP_GROUP = {"call": "call", "failed": "call", "readonly": "readonly", "turn": "turn", "resident": "resident"}


def _class_cap(op: str, ledger: dict) -> tuple[float, float]:
    """(time %, token %) the operation pool of ``op`` takes of the whole trajectory: the most any
    number of problems on that pool can share between them (see ``total_saving``)."""
    tokens, active = ledger.get("tokens") or 0, ledger.get("active_ms") or 0
    group = CAP_GROUP[op]
    if group in ("turn", "resident"):
        return 100., 100.
    cls = (ledger.get("ops") or {}).get(group) or {}

    def pct(part, whole):
        return round(min(100., 100 * (part or 0) / whole), 4) if whole > 0 else 0.
    return pct(cls.get("ms"), active), pct(cls.get("tokens"), tokens)


def total_saving(saves) -> dict | None:
    """The combined expected saving of several cards, as shares of the trajectory, never above
    what the operations involved really take.

    Alternatives on one problem (same ``key``) count once, the best of them. Problems on one
    operation pool (``group``) cannot together take more than the pool (``cap``): their shares
    are scaled down in proportion when they overlap, and all pools together never exceed the
    whole trajectory (100 %). Each card keeps its own effectiveness, so the total is the sum of
    scaled share × effect. ``None`` when no card has a share. The App computes the same total
    (prototypes/advance/src/js/46-a7-recs.js ``recTotal``)."""
    best: dict = {}
    for save in saves or ():
        if not save:
            continue
        key = save.get("key") or id(save)
        for field, pct_key in (("time", "time_pct"), ("token", "token_pct")):
            pct = save.get(pct_key)
            if pct is None:
                continue
            share = (save.get("share") or {}).get(field)
            share = pct if share is None else share
            cap = (save.get("cap") or {}).get(field)  # a pool holds at least the share it priced
            entry = (pct, share, save.get("group") or save.get("op") or key, 100. if cap is None else max(cap, share))
            if (key, field) not in best or pct > best[(key, field)][0]:
                best[(key, field)] = entry
    if not best:
        return None
    out = {}
    for field in ("time", "token"):
        rows = [v for (_key, f), v in best.items() if f == field]
        if not rows:
            out[field] = None
            continue
        pools: dict = {}
        for _pct, share, group, cap in rows:
            used, limit = pools.get(group, (0., 100.))
            pools[group] = (used + share, min(limit, cap))
        scale = {g: (min(1., limit / used) if used > 0 else 1.) for g, (used, limit) in pools.items()}
        whole = sum(share * scale[group] for _pct, share, group, _cap in rows)
        overall = min(1., 100. / whole) if whole > 0 else 1.
        out[field] = round(sum(pct * scale[group] * overall for pct, _share, group, _cap in rows), 4)
    return out


def _unit_text(raw: dict, problem: dict) -> str:
    unit = ((raw.get("kb") or {}).get("benefit") or {}).get("unit") or problem.get("unit") or "次"
    if unit in ("次", "会话") and problem.get("type") in TYPE_ZH:
        unit = f"{unit}「{TYPE_ZH[problem['type']]}」"
    return unit


def _gain(cand: dict, save: dict) -> str:
    """Headline: the saving shares; without them the evidence count (never「0 个会话出现」), and
    nothing for a removal, whose「sessions」are every session that loads the item."""
    if save.get("time_pct") is not None or save.get("token_pct") is not None:
        return save["label"]
    sessions = _sessions(cand)
    return f"{sessions} 个会话出现" if sessions > 0 and cand.get("kind") != "removal" else ""


def _tok(cand: dict, raw: dict) -> int:
    if cand.get("kind") == "removal":
        return -_tokens(cand, raw)
    return int((raw.get("cost") or {}).get("context_tokens") or 0)


def _tok_pct(tok: int, cand: dict, inputs: dict) -> float | None:
    """The card's resident tokens as a share of all trajectory tokens (re-sent with each request)."""
    ledger = (inputs.get("facts") or {}).get("trajectory") or {}
    total = ledger.get("tokens") or 0
    if not tok or total <= 0:
        return 0. if tok == 0 and total > 0 else None
    requests = _requests(ledger, (cand.get("target") or {}).get("agents"))
    return round(100 * tok * requests / total, 4) if requests else None


def _primary(cand: dict, raw: dict) -> tuple[str, int]:
    """(button, level): the action decides the button, not the difficulty level alone."""
    kind, level = cand.get("kind"), cand.get("level") or 1
    file, path = raw.get("file") or [], (cand.get("target") or {}).get("path_hint")
    if kind == "permission_rule":
        # one-click apply needs a known settings file for the user's agent; otherwise it is manual
        return ("一键应用", level) if path else ("查看方案", max(level, 3))
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
    if (cand.get("source") or {}).get("origin") == "catalog" and not file:
        return "查看方案", level  # nothing to preview or write: read the source first
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


def _sessions(cand: dict) -> int:
    """One count for ev, gain and evidence.counts: problem sessions, else the route's count,
    else the uids we carry."""
    problem = cand.get("problem") or {}
    evidence = cand.get("evidence") or {}
    counted = int(problem.get("sessions") or (evidence.get("counts") or {}).get("sessions") or 0)
    return max(counted, len(evidence.get("session_uids") or ()))  # never fewer than A3 will open


def _ev(cand: dict, sessions: int, uids: list) -> str:
    if cand.get("kind") == "removal":
        problem = cand.get("problem") or {}
        note = "均未调用" if problem.get("type") == "installed_unused" else "每次都加载"
        return f"{problem.get('sessions') or len(uids)} 个会话（{note}）"
    return f"{sessions} 个会话" if sessions else ""


def _tilde(path: str) -> str:
    from .recall.subtract import tilde
    return tilde(path) if path.startswith("/") else path


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
    sessions = _sessions(cand)
    uids = (cand.get("evidence") or {}).get("session_uids") or (problem.get("evidence") or {}).get("session_uids") or []
    save = _save(cand, raw, inputs)
    tok = _tok(cand, raw)
    trial = cand.get("trial")
    dim = cand.get("dim")
    primary, level = _primary(cand, raw)
    cand["level"] = level
    steps = list((trial.get("steps") if isinstance(trial, dict) else None) or raw.get("steps") or [])
    return {
        "dim": dim, "type": TYPE_LABEL.get(cand.get("kind"), cand.get("kind")),
        "icon": ICON.get(dim, "rule"), "lvl": level, "aud": cand.get("audience_min") or 0,
        "title": clean(cand.get("title")), "gain": _gain(cand, save),
        "why": clean((cand.get("explain") or {}).get("reason")), "ev": _ev(cand, sessions, uids),
        # evq filters A3 to exactly these sessions; {} (no jump) when there is nothing to resolve
        "evq": {"session_uids": list(uids)} if uids else {},
        "compat": _compat(cand.get("agents") or {}, inputs),
        "primary": primary, "target": _tilde((cand.get("target") or {}).get("path_hint") or ""),
        "file": [list(line) for line in raw.get("file") or []],
        "steps": [clean(s) for s in steps],
        "commands": _commands(steps, trial, raw),
        "track": _track(cand, raw, inputs),
        "save": save, "tok": tok, "tok_pct": _tok_pct(tok, cand, inputs),
        "n": [problem.get("denominator") if problem else None, None],
    }
