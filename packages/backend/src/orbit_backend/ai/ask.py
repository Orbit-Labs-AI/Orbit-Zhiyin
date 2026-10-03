"""L0 ask (ASK-02 / POP-11): preset questions and template answers, no model.

Ported from the Advance demo (`53-ask.js` askAnswer). Every number in an answer
comes from `queries.run`, so the same whitelist backs both L0 and AI answers.
Conditional presets only appear when the data supports them.
"""

from __future__ import annotations

import logging
import re

from . import queries
from .errors import AIError
from .pack import features_profile

log = logging.getLogger(__name__)

ASKQ = {
    "overview": ["和上一个周期比，最大的变化是什么？", "我现在最该先做哪一件事？", "摩擦率为什么是这个数？"],
    "persona": ["为什么判定我是这个类型？", "换一种协作方式会更好吗？", "我的盲点该怎么补？"],
    "recs": ["按投入产出比给这些建议排个序", "哪些建议可以一起装？", "还有没有我没想到的方向？"],
    "session": ["这个会话卡在哪里？", "下次同类任务该怎么开场？", "帮我写一条规则避免重复"],
    "tools": ["哪个工具最值得优化？", "审批太多怎么办？", "哪个 MCP 可以删掉？"],
    "projects": ["哪个项目最花时间？", "哪个项目摩擦最多？", "各项目的工具习惯有什么不同？"],
    "sentiment": ["我最常用的纠偏说法是什么？", "纠偏集中在哪些项目？", "怎样减少重复提醒？"],
    "library": ["哪些已装组件很少被用到？", "我都装了哪些组件？", "还有哪些方向值得装？"],
}
CONDITIONAL = {  # index 3: shown only when `gate(metrics)` holds
    "overview": ("为什么本周纠偏率上升？", "correction_rate"),
    "tools": ("为什么最近工具失败变多了？", "tool_failure_rate"),
}
RISE = 1.2
HOURS_NOTE = "按会话跨度合并计算，重叠的会话只算一次"
MIN_KNOWN_CALLS = 20  # a project needs this many calls with a known status to rank by failure rate
FRIC_RULE = {
    "wrong_approach": "开始改动前，先用三句话复述目标和完成条件，等我确认再动手。",
    "excessive_changes": "只改与任务直接相关的文件；超出范围的改动先列出来问我。",
    "tool_env_failure": "同一命令失败 2 次后停止重试，先检查认证与环境，再告诉我原因。",
    "process_overhead": "简单任务不要启动子代理；确实需要时先问我。",
    "misunderstood_request": "需求有歧义时先提问，不要猜。",
    "parallel_conflict": "并行会话各自使用独立的 worktree，不要改同一个工作目录。",
    "quota_interrupt": "长任务分段完成，每段结束时写一段进度摘要。",
}
PAGES = [("A9", "生成工坊", r"生成|写.*规则|hook|工坊"), ("A4", "工具调用", r"工具|mcp|审批|命令|bash"),
         ("A8", "组件库", r"已装|组件|插件|plugin|skill"), ("A7", "优化建议", r"建议|推荐|装什么"),
         ("A6", "情绪与纠偏", r"纠偏|情绪|说法|不满"), ("A5", "项目", r"项目"), ("A3", "会话", r"会话|session"),
         ("A2", "协作人格", r"人格|类型|画像"), ("A1", "概览", r"概览|本周|周期|总体|变化")]
OUT_OF_SCOPE = "这个问题现在还不能处理"


def route_pages(question: str) -> list[dict]:
    hits = [{"page": p, "label": label} for p, label, rx in PAGES if re.search(rx, question or "", re.I)]
    return hits[:2] or [{"page": "A1", "label": "概览"}]


def out_of_scope(question: str) -> dict:
    return {"answer": OUT_OF_SCOPE, "refs": [], "next": "none", "pages": route_pages(question)}


SCOPE_KEYS = ("days", "start_ms", "end_ms", "project_id", "source_ids")


class _Q:
    """Runs whitelisted queries for one answer and collects their refs."""

    def __init__(self, reads, appdb, scope, home):
        self.reads, self.appdb, self.scope, self.home = reads, appdb, scope or {}, home
        self.refs: list[dict] = []

    def __call__(self, api: str, **params) -> list[dict]:
        if "scope" in queries.SCHEMAS[api]["properties"]:
            scope = {k: self.scope[k] for k in SCOPE_KEYS if self.scope.get(k) not in (None, [])}
            if scope:  # Forwarded as given (days/start_ms/end_ms/project_id/source_ids).
                params.setdefault("scope", scope)
        try:
            r = queries.run(api, params, reads=self.reads, appdb=self.appdb, home=self.home)
        except Exception:  # noqa: BLE001 - no orbit.db yet: answer degrades, never 500
            log.debug("ask query %s failed", api, exc_info=True)
            return []
        self.refs += [x for x in r["refs"] if x not in self.refs]
        return r["rows"]

    def inventory(self) -> dict:
        """Full-inventory aggregates: {"totals": {type: {count, unused}}, "unused": [...]}."""
        try:
            r = queries.run("inventory", {"limit": 20}, reads=self.reads, appdb=self.appdb, home=self.home)
        except Exception:  # noqa: BLE001 - no orbit.db yet
            log.debug("ask inventory failed", exc_info=True)
            return {"totals": {}, "unused": [], "hooks": []}
        return {"totals": r.get("totals") or {}, "unused": r.get("unused") or [], "hooks": r.get("hooks") or []}

    def metrics(self) -> dict:
        return {r["metric"]: r for r in self("metrics")}


def _rising(m: dict, name: str) -> bool:
    row = m.get(name) or {}
    prev, cur = row.get("prev"), row.get("value")
    if prev is None or cur is None:
        return False
    return cur > 0 and cur >= prev * RISE


def _check(context: str, scope=None, index: int | None = None) -> None:
    """B15: an unknown context, preset index or malformed scope is a 422, not overview answers."""
    if context not in ASKQ:
        raise AIError(422, "invalid_context", f"未知问答上下文：{context}", allowed=sorted(ASKQ))
    if index is not None and (context, index) not in _ANSWERS:
        raise AIError(422, "invalid_preset", f"{context} 没有第 {index} 个预置问题")
    try:
        queries.check_scope(scope)
    except ValueError as error:
        raise AIError(422, "invalid_scope", str(error)) from None


def presets(context: str, *, reads, appdb=None, scope=None, session_uid=None, home=None) -> list[dict]:
    _check(context, scope)
    out = [{"index": i, "question": q} for i, q in enumerate(ASKQ[context])]
    if context in CONDITIONAL:
        question, metric = CONDITIONAL[context]
        if _rising(_Q(reads, appdb, scope, home).metrics(), metric):
            out.append({"index": 3, "question": question})
    return out


def _pct(x) -> str:
    return f"{round((x or 0) * 100, 1):g}%"


def _change(a, b) -> str:
    if not b:
        return "新增"
    return ("+" if a >= b else "−") + f"{round(abs(a - b) / b * 100):g}%"


def preset_answer(context: str, index: int, *, reads, appdb=None, scope=None, session_uid=None, home=None) -> dict:
    _check(context, scope, index)
    q = _Q(reads, appdb, scope, home)
    fn = _ANSWERS[(context, index)]
    answer, nxt = fn(q, session_uid)
    out = {"answer": answer, "refs": q.refs[:12], "next": nxt, "source": "template"}
    if nxt == "studio":
        out["handoff"] = handoff(answer, q.refs)
    return out


def handoff(answer: str, refs: list[dict]) -> dict:
    """Studio goal from an answer (ASK-05): the first suggestion line, redacted, ≤200 chars."""
    from .redact import redact2

    lines = [line.strip().lstrip("·").strip() for line in answer.splitlines()]
    suggestion = next((line for line in lines if line and answer.find("· " + line) >= 0), None)
    if suggestion is None:
        first = re.split(r"(?<=[。！？!?])", answer.strip(), maxsplit=1)[0]
        suggestion = first.strip()
    goal, _ = redact2(suggestion)
    return {"goal": goal[:200], "goal_source": "ask", "refs": refs[:12]}


# ---------------------------------------------------------------- overview

def _ov_compare(q, _):
    m = q.metrics()
    if not m or not (m.get("sessions") or {}).get("prev"):
        return "上一个同样长度的周期没有会话，暂时没有可比的数据。换一个时间范围再问我。", "none"
    s, h, cr = m["sessions"], m["hours"], m["correction_rate"]
    text = (f"和上一个同样长度的周期相比：\n\n· 会话 {s['prev']} → {s['value']}（{_change(s['value'], s['prev'])}）\n"
            f"· 协作时长 {h['prev']}h → {h['value']}h（{HOURS_NOTE}）\n· 纠偏率 {_pct(cr['prev'])} → {_pct(cr['value'])}")
    projects = sorted((p for p in q("projects", limit=20) if not p.get("unattributed")),
                      key=lambda p: -(p["hours"] or 0))
    if projects:
        text += f"\n\n花时间最多的项目是「{projects[0]['name']}」，{projects[0]['hours']} 小时。"
    text += "纠偏率在上升，值得看看最近的卡点。" if (cr["value"] or 0) > (cr["prev"] or 0) else "纠偏率没有上升。"
    return text, "none"


def _ov_top(q, _):
    cands = q("candidates", limit=2)
    if cands:
        c = cands[0]
        text = f"先做「{c['title']}」。" + (f"\n\n理由：{c['reason']}" if c.get("reason") else "")
        if len(cands) > 1:
            text += f"\n\n做完之后再看「{cands[1]['title']}」。"
        return text, "recs"
    problems = q("problems", limit=1)
    if problems:
        p = problems[0]
        return f"先处理「{p.get('key')}」：出现 {p.get('count') or p.get('weekly_count')} 次。可以交给生成工坊写一条规则。", \
            "studio"
    return "当前没有明显的卡点，也没有待处理的建议。过一周再来看看。", "none"


def _ov_friction(q, _):
    m = q.metrics()
    if not m:
        return "还没有导入会话，暂时算不出摩擦率。", "none"
    c, n, r = m["corrections"]["value"], m["human_messages"]["value"], m["correction_rate"]["value"]
    text = f"摩擦率 = 纠偏消息 ÷ 你的消息 = {c} ÷ {n} = {_pct(r)}。"
    problems = q("problems", limit=2)
    if problems:
        text += "\n\n最常见的是" + "和".join(f"「{p.get('key')}」（{p.get('sessions')} 个会话）" for p in problems) + \
            "。这类问题都能用规则前置：写进 AGENTS.md 后，Agent 会先遵守，而不是等你提醒。"
    return text, "studio" if problems else "none"


def _ov_rise(q, _):
    m = q.metrics()
    cr, c = m.get("correction_rate") or {}, m.get("corrections") or {}
    text = f"纠偏率从 {_pct(cr.get('prev'))} 升到 {_pct(cr.get('value'))}，纠偏消息 {c.get('prev')} → {c.get('value')} 条。"
    rows = sorted(q("sessions", limit=20), key=lambda r: -r["corrections"])[:2]
    rows = [r for r in rows if r["corrections"]]
    if rows:
        text += "\n\n主要来自：" + "；".join(f"「{r['title']}」{r['corrections']} 次" for r in rows) + "。"
    return text, "sessions"


# ---------------------------------------------------------------- persona

def _profile(q) -> dict:
    return features_profile(q.scope)


def _weight(value) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{round(value * 100):g}%" if 0 <= value <= 1 else f"{value:g}"
    return str(value or "")


_PLACEHOLDER_TYPES = {"当前类型", "未知", "unknown", "type"}
_SHELL_EDGE = re.compile(r"^[\s;&|<>()]+|[\s;&|<>()]+$")


def _tag_label(value) -> str:
    """Readable tag label: no namespace prefix, no shell separators ("cmd:b1;" → "b1")."""
    text = str(value or "")
    if ":" in text and " " not in text:
        text = text.split(":", 1)[1]
    return _SHELL_EDGE.sub("", text)


def _evidence_lines(p: dict) -> list[str]:
    """Top profile features as "· label weight"; tags are dicts (features.profile) or names."""
    weights = p.get("weights") or p.get("tags") or {}
    raw = []
    if isinstance(weights, dict):
        raw = [(_tag_label(k), _weight(v)) for k, v in weights.items()]
    else:
        for tag in weights:
            if isinstance(tag, dict):
                raw.append((_tag_label(tag.get("label") or tag.get("id")), _weight(tag.get("weight"))))
            else:
                raw.append((_tag_label(tag), ""))
    items, seen = [], set()
    for label, weight in raw:
        if label and label not in seen:
            seen.add(label)
            items.append((label, weight))
    return [f"· {label} {weight}".rstrip() for label, weight in items[:4]]


def _pe_why(q, _):
    p = _profile(q)
    if not p:
        n = (q.metrics().get("sessions") or {}).get("value") or 0
        return f"画像还没生成：当前有 {n} 个会话，特征模块完成计算后才判断类型。", "none"
    lines = _evidence_lines(p)
    code = p.get("code")
    if not code or not str(p.get("label") or code).strip() or p.get("label") in _PLACEHOLDER_TYPES:
        tail = ("\n\n目前最明显的特征：\n" + "\n".join(lines)) if lines else ""
        return "样本不足，暂不判断类型。" + tail, "none"
    head = f"判定为「{p.get('label') or code}」"
    return head + ("，主要依据：\n\n" + "\n".join(lines) if lines else "。"), "none"


def _pe_tradeoff(q, _):
    p = _profile(q)
    lines = _evidence_lines(p) if p else []
    if not lines:
        return "画像还没生成，暂时说不出你的取舍。特征模块完成计算后再问。", "none"
    cands = q("candidates", limit=1)
    tail = f"\n\n可以从「{cands[0]['title']}」开始补位。" if cands else ""
    head = "你的画像里最突出的倾向（权重从高到低）：\n" + "\n".join(lines[:3])
    return (head + "\n\n越突出的倾向，对应的环节越容易成为代价来源；不必换类型，"
            "把这些环节里最常出问题的一步写成规则。" + tail), "recs" if cands else "studio"


def _pe_blind(q, _):
    problems = q("problems", limit=2)
    if not problems:
        return "暂时没有发现集中出现的卡点。", "none"
    rule = FRIC_RULE.get(problems[0].get("type") or "", "在第一条消息里写清完成条件。")
    return f"你的盲点主要在「{problems[0].get('key')}」。\n\n建议：\n· {rule}", "studio"


# ---------------------------------------------------------------- recs

def _re_rank(q, _):
    cands = q("candidates", limit=10)
    if not cands:
        return "当前还没有推荐候选。先导入会话，或到建议页刷新。", "recs"
    cands = sorted(cands, key=lambda c: -(c.get("priority") or 0))[:5]
    return "按优先级排序：\n\n" + "\n".join(f"{k + 1}. {c['title']}" for k, c in enumerate(cands)), "recs"


def _re_pair(q, _):
    cands = q("candidates", limit=10)
    by_kind: dict = {}
    for c in cands:
        by_kind.setdefault(c.get("kind"), c)
    pairs = list(by_kind.values())
    if len(pairs) < 2:
        return "当前候选类型太少，暂时给不出组合。", "recs"
    # Kinds differing says nothing about compatibility (catalog has no conflict data yet), so
    # only list one candidate per kind and leave the compatibility judgement to the item pages.
    picks = "、".join(f"「{c['title']}」（{c.get('kind') or '未分类'}）" for c in pairs[:3])
    return f"不同类型各取一个：{picks}。是否能同时启用请看各自的说明，目前没有冲突数据。", "recs"


def _re_more(q, _):
    problems = q("problems", limit=1)
    hits = q("catalog", q=str(problems[0].get("key"))[:80]) if problems and problems[0].get("key") else []
    if hits:
        return "目录里还有这些方向：\n" + "\n".join(f"· {h['name']}：{h.get('summary') or ''}" for h in hits[:3]), "recs"
    return "目录里暂时没有与你的卡点直接相关的新方向。", "none"


# ---------------------------------------------------------------- session

def _session(q, uid):
    rows = q("sessions", session_uid=uid, limit=1) if uid else []
    return rows[0] if rows else None


def _se_stuck(q, uid):
    s = _session(q, uid)
    if not s:
        return "先在左侧选一个会话。", "sessions"
    text = f"「{s['title']}」：{s['minutes']} 分钟，{s['tools']} 次工具调用，{s['errors']} 次错误，{s['corrections']} 次纠偏。"
    rules = _session_rules(s)
    if rules:
        # Errors (tool calls) and corrections (user messages) are different units, so they are
        # stated side by side instead of compared to name "the" cause.
        text += "\n\n下次可以约定：\n" + "\n".join(f"· {r}" for r in rules)
    else:
        text += "\n\n这次没有记录到错误或纠偏。"
    return text, "studio" if rules else "none"


def _session_rules(s: dict) -> list[str]:
    rules = []
    if s.get("errors"):
        rules.append(FRIC_RULE["tool_env_failure"])
    if s.get("corrections"):
        rules.append(FRIC_RULE["wrong_approach"])
    return rules


def _se_opening(q, uid):
    s = _session(q, uid)
    if not s:
        return "先在左侧选一个会话。", "sessions"
    rule = "；".join(_session_rules(s)) or "不要改与任务无关的文件。"
    return (f"下次同类任务，第一条消息可以这样写：\n\n目标：{s['title']}\n完成条件：（写清可以验证的结果）\n"
            f"约定：{rule}\n验证方式：完成后贴出命令输出"), "none"


def _se_rule(q, uid):
    s = _session(q, uid)
    if not s:
        return "先在左侧选一个会话。", "sessions"
    rules = _session_rules(s) or ["只改与任务直接相关的文件。"]
    body = "".join(f"- {r}\n" for r in rules)
    return (f"## {s.get('project') or '项目'} 协作约定\n\n{body}- 完成后先自查，再向我汇报验证结果。\n\n"
            "可以复制到项目的 AGENTS.md，或交给生成工坊做成 Hook。"), "studio"


# ---------------------------------------------------------------- tools

def _to_worst(q, _):
    rows = q("tools", limit=5)
    if not rows or not rows[0]["failures"]:
        return "这段时间没有工具失败。", "none"
    t = rows[0]
    text = f"{t['tool']} 失败最多：{t['failures']} 次（错误率 {_pct(t['failure_rate'])}）。"
    if t.get("top_error_class"):
        text += f"最多的错误是「{t['top_error_class']}」。"
    if any("retry-breaker" in str(h) for h in q.inventory()["hooks"]):
        return text + "\n\n「重复失败熔断」Hook 已安装；可以看看它的阈值是否需要调低。", "tools"
    return text + "\n\n装「重复失败熔断」后，同一命令连续失败达到阈值会先停下诊断，不再原样重试。", "tools"


def _to_approvals(q, _):
    rows = sorted(q("tools", limit=20), key=lambda r: -(r["approvals"] + r.get("denied", 0)))
    if not rows or not rows[0]["approvals"] + rows[0].get("denied", 0):
        return "这段时间没有记录到需要审批的调用。", "none"
    t = rows[0]
    parts = ([f"{t['approvals']} 次经你批准后执行"] if t["approvals"] else []) + \
        ([f"{t['denied']} 次被你拒绝"] if t.get("denied") else [])
    return (f"{t['tool']} 的调用中有 " + "，".join(parts) + f"（共 {t['calls']} 次）。\n\n"
            "把只读命令放进允许列表可以少掉大部分审批；含写操作的命令仍然需要你确认。"), "studio"


def _to_mcp(q, _):
    inv = q.inventory()
    if not inv["totals"].get("mcp"):
        return "还没有扫描到已装的 MCP。到设置里运行一次扫描。", "none"
    unused = [r for r in inv["unused"] if r["type"] == "mcp"]
    if not unused:
        return "已装的 MCP 近 30 天都有调用（含子代理），暂时没有可以删的。", "none"
    names = "、".join(r["name"] for r in unused[:3])
    more = f" 等 {inv['totals']['mcp']['unused']} 个" if inv["totals"]["mcp"]["unused"] > 3 else ""
    return f"{names}{more} 近 30 天没有被调用过（含子代理），但每个会话都会加载它的工具描述。可以先移除，需要时再装回来。", "tools"


def _to_rise(q, _):
    m = q.metrics()
    fr = m.get("tool_failure_rate") or {}
    text = f"工具失败率从 {_pct(fr.get('prev'))} 升到 {_pct(fr.get('value'))}。"
    rows = q("tools", limit=1)
    if rows and rows[0]["failures"]:
        text += f"失败最多的是 {rows[0]['tool']}（{rows[0]['failures']} 次）。"
    return text, "tools"


# ---------------------------------------------------------------- projects / sentiment / library

def _pr_time(q, _):
    rows = sorted(q("projects", limit=20), key=lambda r: -(r["hours"] or 0))[:3]
    if not rows:
        return "还没有按项目归类的会话。", "none"
    return ("花时间最多的项目（" + HOURS_NOTE + "）：\n"
            + "\n".join(f"· {r['name']}：{r['hours']} 小时，{r['sessions']} 个会话" for r in rows)), "none"


def wilson_lower(failures: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson interval: small samples cannot win on a lucky ratio."""
    if not n:
        return 0.0
    p = failures / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (centre - margin) / denom)


def _pr_friction(q, _):
    rows = [r for r in q("projects", limit=20)
            if (r.get("known_calls") or 0) >= MIN_KNOWN_CALLS and not r.get("unattributed")]
    if not rows:
        return f"还没有足够的项目级工具数据（每个项目至少需要 {MIN_KNOWN_CALLS} 次有结果的调用）。", "none"
    r = max(rows, key=lambda r: (wilson_lower(r["tool_failures"], r["known_calls"]), r["known_calls"]))
    return (f"「{r['name']}」摩擦最多：{r['known_calls']} 次有结果的工具调用中失败 {r['tool_failures']} 次"
            f"（{_pct(r['tool_failures'] / r['known_calls'])}）。"), "tools"


def _pr_habits(q, _):
    rows = q("projects", limit=5)
    if not rows:
        return "还没有按项目归类的会话。", "none"
    return "各项目的工具使用：\n" + "\n".join(
        f"· {r['name']}：{r['tool_calls']} 次调用，失败 {r['tool_failures']} 次" for r in rows), "none"


def _se_phrases(q, _):
    rows = q("corrections", limit=3)
    if not rows:
        return "这段时间没有记录到纠偏说法。", "none"
    return "最近的纠偏原话：\n" + "\n".join(f"· {r['text'][:60]}" for r in rows), "sessions"


def _se_projects(q, _):
    totals: dict = {}
    for r in q("sessions", limit=20):
        totals[r.get("project") or "未归类"] = totals.get(r.get("project") or "未归类", 0) + r["corrections"]
    top = [(k, v) for k, v in sorted(totals.items(), key=lambda x: -x[1]) if v][:3]
    if not top:
        return "最近的会话里没有纠偏。", "none"
    return "纠偏集中在：" + "；".join(f"{k} {v} 次" for k, v in top) + "（最近 20 个会话）。", "sessions"


def _se_reduce(q, _):
    problems = q("problems", limit=1)
    rule = FRIC_RULE.get((problems[0].get("type") if problems else "") or "", FRIC_RULE["wrong_approach"])
    return f"把你反复说的话写成规则，Agent 会先遵守：\n\n· {rule}\n\n可以交给生成工坊做成规则或 Hook。", "studio"


def _li_unused(q, _):
    inv = q.inventory()
    if not inv["totals"]:
        return "还没有扫描本机组件。到设置里运行一次扫描。", "none"
    unused = [r for r in inv["unused"] if r["type"] in ("mcp", "skill")]
    if not unused:
        return "已装的 MCP 和 Skill 近 30 天都有调用。", "none"
    total = sum(inv["totals"].get(t, {}).get("unused", 0) for t in ("mcp", "skill"))
    head = "、".join(f"{r['name']}（{r['type']}）" for r in unused[:5])
    return f"近 30 天没有调用的有 {total} 个：{head}" + ("等。" if total > 5 else "。"), "tools"


def _li_all(q, _):
    totals = q.inventory()["totals"]
    if not totals:
        return "还没有扫描本机组件。到设置里运行一次扫描。", "none"
    return "已装组件：" + "，".join(f"{k} {v['count']} 个" for k, v in totals.items()) + "。", "none"


_ANSWERS = {
    ("overview", 0): _ov_compare, ("overview", 1): _ov_top, ("overview", 2): _ov_friction, ("overview", 3): _ov_rise,
    ("persona", 0): _pe_why, ("persona", 1): _pe_tradeoff, ("persona", 2): _pe_blind,
    ("recs", 0): _re_rank, ("recs", 1): _re_pair, ("recs", 2): _re_more,
    ("session", 0): _se_stuck, ("session", 1): _se_opening, ("session", 2): _se_rule,
    ("tools", 0): _to_worst, ("tools", 1): _to_approvals, ("tools", 2): _to_mcp, ("tools", 3): _to_rise,
    ("projects", 0): _pr_time, ("projects", 1): _pr_friction, ("projects", 2): _pr_habits,
    ("sentiment", 0): _se_phrases, ("sentiment", 1): _se_projects, ("sentiment", 2): _se_reduce,
    ("library", 0): _li_unused, ("library", 1): _li_all, ("library", 2): _re_more,
}


def opening_suggestion(reads, appdb=None, scope=None, home=None) -> dict | None:
    """POP-11 idle-state hint: one sentence for the top recent problem, or None."""
    q = _Q(reads, appdb, scope or {"days": 7}, home)
    problems = q("problems", limit=1)
    if problems:
        p = problems[0]
        rule = FRIC_RULE.get(p.get("type") or "")
        text = f"最近「{p.get('key')}」出现得最多" + (f"，可以试试：{rule}" if rule else "，可以交给生成工坊写一条规则。")
        return {"text": text, "refs": q.refs[:3], "next": "studio"}
    m = q.metrics()
    if (m.get("corrections") or {}).get("value"):
        return {"text": f"最近有 {m['corrections']['value']} 条纠偏消息，开场时先写清完成条件。",
                "refs": q.refs[:3], "next": "sessions"}
    return None
