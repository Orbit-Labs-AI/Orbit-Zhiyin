"""v1 AI tasks (C1 TaskSpec dicts): AI-04.1–04.4 classify / cluster, AI-05.2–05.4 narrate.

Every task has a prompt, a closed JSON schema, a deterministic validator (ids from the
input, numbers from the input, `evaluate_text` for prose), an L0 fallback used when the
engine fails or AI is off (`AIService.narrative`), and a finalize that merges model output
with the L0 result so each input item always gets an answer. Results are cached by the
runner on the input digest; every result carries the pack item's ``key``.
"""

from __future__ import annotations

import re

from tandem_backend.evaluation.readability import SCENE_BUDGETS, evaluate_text

from .pack import MISUNDERSTOOD, is_correction
from .redact import compact
from .runner import default_run
from .tasks_analysis import FEEDBACK, FRICTIONS, NARRATE_SCHEMA, S, numbers_ok

CONF = ["high", "medium", "low"]
SENTIMENTS = ["positive", "neutral", "negative", "frustrated"]
MECHANISMS = ["rule", "hook", "skill", "subagent", "workflow", "none"]
HANDOFF = ("rule", "hook", "skill", "subagent")
ID_KEYS = {"session_uid", "event_uid", "signal_id", "problem_id", "candidate_id", "call_uid", "cluster_id",
           "outcome_id"}
TEMPLATE_NOTE = "这是模板生成的内容，未经过模型个性化。"


# ---------------------------------------------------------------- shared gates

def _ids(value, out: set | None = None) -> set[str]:
    """Every id-like string in the input (plus metric names under ``metrics`` / ``row``)."""
    out = set() if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ID_KEYS and isinstance(v, str):
                out.add(v)
            elif k in ("metrics", "row") and isinstance(v, dict):
                out.update(str(x) for x in v)
            _ids(v, out)
    elif isinstance(value, list):
        for v in value:
            _ids(v, out)
    return out


def _numbers(value, out: set | None = None) -> set[float]:
    out = set() if out is None else out
    if isinstance(value, dict):
        for v in value.values():
            _numbers(v, out)
    elif isinstance(value, list):
        for v in value:
            _numbers(v, out)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out.add(float(value))
    return out


def _scene(name: str) -> str:
    return name if name in SCENE_BUDGETS else "developer_report"


def _item(pack: dict, key: str) -> dict:
    return (pack.get("content") or {}).get(key) or {}


def prose_errors(texts: list[str], source, scene: str, banned: tuple[str, ...] = ()) -> list[str]:
    text = "\n".join(t for t in texts if t)
    errors = []
    bad = numbers_ok(text, _numbers(source))
    if bad:
        errors.append(f"数字不在输入中：{', '.join(bad[:5])}")
    errors += [f"禁用词：{w}" for w in banned if w in text]
    errors += [f"可读性：{i['code']}" for i in evaluate_text(text, _scene(scene))["issues"]
               if i["severity"] == "error"]
    return errors


def foreign_ids(ids, allowed: set[str]) -> list[str]:
    bad = [i for i in ids if i not in allowed]
    return [f"引用不在输入中：{', '.join(bad[:5])}"] if bad else []


def _result(task: dict, pack: dict, item_key: str, body: dict, source: str) -> dict:
    src = {"fallback": "template"}.get(source, source)
    return {"status": "fallback" if source == "fallback" else "ok",
            "result": {"key": _item(pack, item_key).get("key", "default"), **body, "source": src,
                       "prompt_version": task["prompt_version"]},
            "artifact": None, "facets": None}


def _runner(empty):
    """default_run, except an empty input never reaches the engine."""
    def run(ctx, pack):
        if empty(pack):
            ctx.stage("pack", "ok", "没有需要处理的输入")
            return ctx.task["finalize"](ctx.task["fallback"](pack, "empty"), pack, "empty")
        return default_run(ctx, pack)
    return run


def _task(task_id: str, tier: str, item_key: str, *, system, schema, validate, fallback, finalize, empty,
          budget: int, out: int, title: str, cache_ttl_s=None) -> dict:
    slot = "cheap" if tier == "L2" else "main"
    return {"task_id": task_id, "title": title, "tier": tier, "slot": slot, "prompt_version": f"{task_id}@1",
            "schema_version": "1", "input_budget": budget, "out_budget": out,
            "max_budget_usd": 0.1 if slot == "cheap" else 0.5, "timeout_s": 120 if tier == "L2" else 180,
            "engines": ("claude_code", "codex", "api_key", "fake"), "pack_items": [(item_key, True)],
            "requires_preview": False, "cache_ttl_s": cache_ttl_s, "stages": ["pack", "draft", "check"],
            "system": system, "schema": schema,
            "build_prompt": lambda pack: f"<input>\n{compact(_item(pack, item_key))}\n</input>",
            "validate": validate, "fallback": fallback, "finalize": finalize, "run": _runner(empty)}


# ---------------------------------------------------------------- classify.feedback (AI-04.1)

FEEDBACK_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "maxItems": 20, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["signal_id", "is_correction", "feedback_kind", "friction_type", "sentiment", "confidence"],
        "properties": {"signal_id": {"type": "string"}, "is_correction": {"type": "boolean"},
                       "feedback_kind": {"enum": FEEDBACK}, "friction_type": {"enum": [*FRICTIONS, "none"]},
                       "sentiment": {"enum": SENTIMENTS}, "confidence": {"enum": CONF}}}}},
}
FEEDBACK_SYSTEM = (
    "你判断编码 Agent 会话里用户的一条反馈是什么意思。每个输入项有用户原话 text、前一条助手回复 prev_assistant 与任务"
    "上下文 context。is_correction：用户在纠正 Agent 的做法或理解；feedback_kind/friction_type/sentiment 是闭集；"
    "confidence 是闭集不是概率，拿不准写 low。rejudge=true 表示用户认为原判不准确，请独立重判。"
    "每个输入项输出一项，signal_id 原样抄写，不要编造新的 signal_id。")
_STRONG = re.compile(r"别再|又|还是不|说了多少次|!!|！！|again", re.I)
_POSITIVE = re.compile(r"谢谢|好的|不错|完美|great|thanks|lgtm", re.I)


def feedback_rule(item: dict) -> dict:
    """L0 rule classification (``type_source = rule``)."""
    text = item.get("text") or ""
    corr = is_correction(text)  # the single correction definition (pack.is_correction)
    sentiment = ("frustrated" if _STRONG.search(text) else "negative") if corr else (
        "positive" if _POSITIVE.search(text) else "neutral")
    # A rule cannot tell a wrong approach from buggy output; only explicit "you misread me"
    # wording maps to misunderstood_request, every other correction is "other".
    friction = ("misunderstood_request" if MISUNDERSTOOD.search(text) else "other") if corr else "none"
    return {"signal_id": item["signal_id"], "is_correction": corr, "feedback_kind": "correct" if corr else "other",
            "friction_type": friction, "sentiment": sentiment, "confidence": "low"}


def feedback_validate(output: dict, pack: dict) -> list[str]:
    allowed = [i["signal_id"] for i in _item(pack, "feedback_items").get("items") or []]
    seen = [i["signal_id"] for i in output.get("items") or []]
    errors = foreign_ids(seen, set(allowed))
    if len(seen) != len(set(seen)):
        errors.append("signal_id 重复")
    return errors


def feedback_fallback(pack: dict, reason: str) -> dict:
    return {"items": [feedback_rule(i) for i in _item(pack, "feedback_items").get("items") or []]}


def feedback_finalize(output: dict, pack: dict, source: str) -> dict:
    by_id = {i["signal_id"]: i for i in output.get("items") or []}
    items = []
    for inp in _item(pack, "feedback_items").get("items") or []:
        judged = by_id.get(inp["signal_id"])
        ai = judged is not None and source not in ("fallback", "empty")
        items.append({**(judged or feedback_rule(inp)), "event_uid": inp.get("event_uid"),
                      "session_uid": inp.get("session_uid"), "rejudge": bool(inp.get("rejudge")),
                      "type_source": "facet" if ai else "rule"})
    return _result(FEEDBACK_TASK, pack, "feedback_items", {"items": items}, source)


FEEDBACK_TASK = _task(
    "classify.feedback", "L2", "feedback_items", system=FEEDBACK_SYSTEM, schema=FEEDBACK_SCHEMA,
    validate=feedback_validate, fallback=feedback_fallback, finalize=feedback_finalize,
    empty=lambda pack: not _item(pack, "feedback_items").get("items"), budget=12_000, out=2_000,
    title="反馈语分类")

# ---------------------------------------------------------------- cluster.failure_names (AI-04.2)

FAILURE_LABELS = {"unknown": "未归类失败", "timeout": "超时", "permission": "权限不足", "permission_denied": "权限不足",
                  "not_found": "找不到文件或命令", "exit_nonzero": "命令返回非零", "tool_error": "工具报错",
                  "interrupted": "被中断", "rate_limit": "触发限流", "network": "网络错误"}
FAILURE_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False, "required": ["clusters"],
    "properties": {"clusters": {"type": "array", "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False, "required": ["error_class", "name", "member_ids"],
        "properties": {"error_class": {"type": "string"}, "name": {"type": "string", "minLength": 1, "maxLength": 16},
                       "member_ids": {"type": "array", "items": {"type": "string"}}}}}},
}
FAILURE_SYSTEM = (
    "给编码 Agent 的工具失败分组起可读的中文名。每个输入组是一个 error_class，members 是该类失败的输出首 200 字。"
    "name ≤16 字，说清是什么失败（如「测试断言失败」「依赖未安装」），不要写数字。member_ids 只能用该组里的 call_uid，"
    "可以只列与名字相符的成员。每组输出一项，error_class 原样抄写。")


def failure_label(error_class: str) -> str:
    return FAILURE_LABELS.get(error_class, error_class.replace("_", " ")[:16] or "未归类失败")


def failure_validate(output: dict, pack: dict) -> list[str]:
    groups = {g["error_class"]: {m["call_uid"] for m in g["members"]}
              for g in _item(pack, "failures").get("groups") or []}
    errors = []
    for c in output.get("clusters") or []:
        if c["error_class"] not in groups:
            errors.append(f"error_class 不在输入中：{c['error_class']}")
            continue
        errors += foreign_ids(c["member_ids"], groups[c["error_class"]])
        if re.search(r"\d", c["name"]):
            errors.append(f"簇名不要包含数字：{c['name']}")
    return errors


def failure_fallback(pack: dict, reason: str) -> dict:
    return {"clusters": [{"error_class": g["error_class"], "name": failure_label(g["error_class"]),
                          "member_ids": [m["call_uid"] for m in g["members"]]}
                         for g in _item(pack, "failures").get("groups") or []]}


def failure_finalize(output: dict, pack: dict, source: str) -> dict:
    named = {c["error_class"]: c for c in output.get("clusters") or []}
    ai = source not in ("fallback", "empty")
    clusters = []
    for g in _item(pack, "failures").get("groups") or []:
        c = named.get(g["error_class"])
        members = [m["call_uid"] for m in g["members"]]
        clusters.append({"error_class": g["error_class"], "count": g.get("count", len(members)),
                         "name": c["name"] if c else failure_label(g["error_class"]),
                         "member_ids": (c or {}).get("member_ids") or members,
                         "named_by": "ai" if c and ai else "rule"})
    return _result(FAILURE_TASK, pack, "failures", {"clusters": clusters}, source)


FAILURE_TASK = _task(
    "cluster.failure_names", "L2", "failures", system=FAILURE_SYSTEM, schema=FAILURE_SCHEMA,
    validate=failure_validate, fallback=failure_fallback, finalize=failure_finalize,
    empty=lambda pack: not _item(pack, "failures").get("groups"), budget=10_000, out=1_200, title="失败簇命名")

# ---------------------------------------------------------------- cluster.topic_names (AI-04.3)

TOPIC_KINDS = ["task", "domain", "tool", "project", "other"]
TOPIC_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False, "required": ["clusters"],
    "properties": {"clusters": {"type": "array", "maxItems": 30, "items": {
        "type": "object", "additionalProperties": False, "required": ["cluster_id", "name", "kind", "confidence"],
        "properties": {"cluster_id": {"type": "string"}, "name": {"type": "string", "minLength": 1, "maxLength": 12},
                       "kind": {"enum": TOPIC_KINDS}, "confidence": {"enum": CONF}}}}},
}
TOPIC_SYSTEM = (
    "给会话主题簇命名，只用于展示。每簇有 top_terms 与 ≤3 条代表会话摘要。name ≤12 字、具体（如「前端样式调整」），"
    "kind 是闭集：task 任务类型 / domain 业务领域 / tool 工具 / project 项目 / other；拿不准 confidence=low。"
    "每簇输出一项，cluster_id 原样抄写。")


def topic_validate(output: dict, pack: dict) -> list[str]:
    allowed = {c["cluster_id"] for c in _item(pack, "topic_clusters").get("clusters") or []}
    return foreign_ids([c["cluster_id"] for c in output.get("clusters") or []], allowed)


def topic_fallback(pack: dict, reason: str) -> dict:
    return {"clusters": [{"cluster_id": c["cluster_id"], "name": f"簇 #{c['cluster_id']}", "kind": "other",
                          "confidence": "low"} for c in _item(pack, "topic_clusters").get("clusters") or []]}


def topic_finalize(output: dict, pack: dict, source: str) -> dict:
    named = {c["cluster_id"]: c for c in output.get("clusters") or []}
    ai = source not in ("fallback", "empty")
    clusters = []
    for c in _item(pack, "topic_clusters").get("clusters") or []:
        n = named.get(c["cluster_id"]) if ai else None
        clusters.append({"cluster_id": c["cluster_id"], "top_terms": c.get("top_terms") or [],
                         "name": n["name"] if n else f"簇 #{c['cluster_id']}",
                         "kind": n["kind"] if n else "other", "confidence": n["confidence"] if n else "low",
                         "label": "AI 命名" if n else None})
    return _result(TOPIC_TASK, pack, "topic_clusters", {"clusters": clusters, "display_only": True}, source)


TOPIC_TASK = _task(
    "cluster.topic_names", "L2", "topic_clusters", system=TOPIC_SYSTEM, schema=TOPIC_SCHEMA,
    validate=topic_validate, fallback=topic_fallback, finalize=topic_finalize,
    empty=lambda pack: len(_item(pack, "topic_clusters").get("clusters") or []) < 2, budget=8_000, out=1_000,
    title="主题簇命名")

# ---------------------------------------------------------------- classify.failure_cause (AI-04.4)

CAUSES = ["permission", "not_found", "timeout", "syntax", "test_failure", "dependency", "network",
          "resource_limit", "user_interrupt", "other", "unknown"]
CAUSE_RULES = [("permission", r"permission denied|EACCES|not permitted|权限"),
               ("not_found", r"no such file|not found|ENOENT|找不到"),
               ("timeout", r"timed? ?out|超时"), ("syntax", r"syntaxerror|parse error|语法错误"),
               ("test_failure", r"\bfailed\b.*\btests?\b|assert(ion)?error|\d+ failed"),
               ("dependency", r"modulenotfounderror|cannot find module|command not found|no module named"),
               ("network", r"ECONNREFUSED|ENOTFOUND|network|connection (refused|reset)"),
               ("resource_limit", r"out of memory|ENOSPC|killed|rate limit"),
               ("user_interrupt", r"interrupted|cancelled by user|用户中断")]
CAUSE_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["call_uid", "cause", "explanation", "confidence"],
        "properties": {"call_uid": {"type": "string"}, "cause": {"enum": CAUSES},
                       "explanation": {"type": "string", "maxLength": 60}, "confidence": {"enum": CONF}}}}},
}
CAUSE_SYSTEM = (
    "判断编码 Agent 一次工具失败的原因。输入是 ≤4 条未归类失败（工具名、命令头、退出码、输出首 400 字）。"
    "cause 是闭集，看不出写 unknown；explanation ≤60 字，只依据输出内容，不要编造路径或数字。"
    "每条输出一项，call_uid 原样抄写。")


def cause_rule(item: dict) -> dict:
    text = f"{item.get('text') or ''} {item.get('command_head') or ''}"
    cause = next((c for c, rx in CAUSE_RULES if re.search(rx, text, re.I)), "unknown")
    return {"call_uid": item["call_uid"], "cause": cause,
            "explanation": "按输出关键词归类" if cause != "unknown" else "未能自动归类", "confidence": "low"}


def cause_validate(output: dict, pack: dict) -> list[str]:
    items = _item(pack, "unknown_failures").get("items") or []
    errors = foreign_ids([i["call_uid"] for i in output.get("items") or []], {i["call_uid"] for i in items})
    bad = numbers_ok(" ".join(i["explanation"] for i in output.get("items") or []), _numbers(items))
    return errors + ([f"数字不在输入中：{', '.join(bad[:5])}"] if bad else [])


def cause_fallback(pack: dict, reason: str) -> dict:
    return {"items": [cause_rule(i) for i in _item(pack, "unknown_failures").get("items") or []]}


def cause_finalize(output: dict, pack: dict, source: str) -> dict:
    by_id = {i["call_uid"]: i for i in output.get("items") or []}
    ai = source not in ("fallback", "empty")
    items = [{**(by_id.get(i["call_uid"]) if ai and i["call_uid"] in by_id else cause_rule(i)),
              "classified_by": "ai" if ai and i["call_uid"] in by_id else "rule"}
             for i in _item(pack, "unknown_failures").get("items") or []]
    return _result(CAUSE_TASK, pack, "unknown_failures", {"items": items}, source)


CAUSE_TASK = _task(
    "classify.failure_cause", "L2", "unknown_failures", system=CAUSE_SYSTEM, schema=CAUSE_SCHEMA,
    validate=cause_validate, fallback=cause_fallback, finalize=cause_finalize,
    empty=lambda pack: not _item(pack, "unknown_failures").get("items"), budget=4_000, out=600,
    title="失败原因归类")

# ---------------------------------------------------------------- narrate.session_review (AI-05.2)

_NARR = NARRATE_SCHEMA["properties"]
LESSON = {"type": "object", "additionalProperties": False, "required": ["text", "mechanism", "evidence_ids"],
          "properties": {"text": {"type": "string", "maxLength": 60}, "mechanism": {"enum": MECHANISMS},
                         "evidence_ids": {"type": "array", "items": {"type": "string"}}}}
REVIEW_SCHEMA = {**NARRATE_SCHEMA, "required": [*NARRATE_SCHEMA["required"], "lessons"],
                 "properties": {**_NARR, "lessons": {"type": "array", "maxItems": 3, "items": LESSON}}}
REVIEW_SYSTEM = (
    "你为一个编码 Agent 会话写复盘，先给结论。findings 依次写做得好(good)、卡在哪(stuck)、下次开场怎么说(next)，"
    "每段 ≤60 字。lessons ≤3 条，每条 ≤60 字并绑定一个机制：rule 写进规则 / hook 加钩子拦截 / skill 封装成技能 / "
    "subagent 交给子代理 / workflow 改做法 / none。所有数字原样来自输入；evidence_ids 只能用输入里的 session_uid、"
    "event_uid、signal_id 或 row 的字段名。不要使用「保证」「一定」「证明有效」。audience 固定 user。")


def _narr_texts(output: dict) -> list[str]:
    out = [output.get("summary", ""), output.get("next_step", "")] + list(output.get("caveats") or [])
    for f in output.get("findings") or []:
        out += [f.get("title", ""), f.get("text", "")]
    return out


def _narr_ids(output: dict) -> list[str]:
    return list(output.get("main_evidence_ids") or []) + [i for f in output.get("findings") or []
                                                         for i in f.get("evidence_ids") or []]


def review_validate(output: dict, pack: dict) -> list[str]:
    src = _item(pack, "session_review")
    lessons = output.get("lessons") or []
    ids = _narr_ids(output) + [i for lesson in lessons for i in lesson.get("evidence_ids") or []]
    return foreign_ids(ids, _ids(src)) + prose_errors(
        _narr_texts(output) + [lesson["text"] for lesson in lessons], src, "bottleneck")


def review_fallback(pack: dict, reason: str) -> dict:
    """Rule review: row + signals + key moments into template sentences."""
    src = _item(pack, "session_review")
    uid, row = src.get("session_uid") or "", src.get("row") or {}
    signals, moments = src.get("signals") or [], src.get("key_moments") or []
    findings, lessons = [], []
    if row:
        findings.append({"title": "做得好", "scene": "good", "evidence_ids": [uid] if uid else [],
                         "text": f"这次会话 {row.get('minutes', 0)} 分钟，调用工具 {row.get('tools', 0)} 次。"})
    run = next((m for m in moments if m.get("kind") == "failure_run"), None)
    if run:
        findings.append({"title": "卡在哪", "scene": "stuck", "evidence_ids": ["tool_errors"],
                         "text": f"同一命令「{run.get('command_head')}」连续失败。"})
        lessons.append({"text": "同一命令连续失败时先停下来排查原因。", "mechanism": "hook",
                        "evidence_ids": [uid] if uid else []})
    elif signals:
        findings.append({"title": "卡在哪", "scene": "stuck", "evidence_ids": [signals[0]["event_uid"]],
                         "text": f"有 {len(signals)} 处纠正，Agent 没理解到位。"})
    if signals:
        lessons.append({"text": "把这次反复纠正的要求写进规则。", "mechanism": "rule",
                        "evidence_ids": [signals[0]["event_uid"]]})
    next_text = "开场先写清目标、约束和验收方式。"
    findings.append({"title": "下次开场", "scene": "next", "evidence_ids": [], "text": next_text})
    return {"summary": (findings[0]["text"] if findings else "这次会话没有可复盘的数据。")[:40],
            "findings": findings[:3], "next_step": next_text, "caveats": [TEMPLATE_NOTE],
            "main_evidence_ids": [uid] if uid else [], "audience": "user", "lessons": lessons[:3]}


def review_finalize(output: dict, pack: dict, source: str) -> dict:
    uid = _item(pack, "session_review").get("session_uid")
    lessons = []
    for lesson in output.get("lessons") or []:
        lesson = dict(lesson)
        if lesson["mechanism"] in HANDOFF:
            lesson["handoff"] = {"task_id": f"generate.{lesson['mechanism']}", "goal": lesson["text"],
                                 "goal_source": "ask", "refs": list(lesson.get("evidence_ids") or []),
                                 "params": {"session_uids": [uid] if uid else []}}
        lessons.append(lesson)
    return _result(REVIEW_TASK, pack, "session_review", {**output, "lessons": lessons, "session_uid": uid},
                   source)


REVIEW_TASK = _task(
    "narrate.session_review", "L3", "session_review", system=REVIEW_SYSTEM, schema=REVIEW_SCHEMA,
    validate=review_validate, fallback=review_fallback, finalize=review_finalize,
    empty=lambda pack: not _item(pack, "session_review").get("row"), budget=10_000, out=1_000,
    title="单会话复盘")

# ---------------------------------------------------------------- narrate.weekly (AI-05.3)

SECTION_IDS = ["overview", "problems", "effects"]
SECTION = {"type": "object", "additionalProperties": False, "required": ["id", "title", "text", "evidence_ids"],
           "properties": {"id": {"enum": SECTION_IDS}, "title": {"type": "string", "maxLength": 12},
                          "text": {"type": "string", "maxLength": 200},
                          "evidence_ids": {"type": "array", "items": {"type": "string"}}}}
WEEKLY_SCHEMA = {**NARRATE_SCHEMA, "required": [*NARRATE_SCHEMA["required"], "sections", "at_a_glance"],
                 "properties": {**_NARR, "at_a_glance": {"type": "string", "maxLength": 80},
                                "sections": {"type": "array", "minItems": 3, "maxItems": 3, "items": SECTION}}}
WEEKLY_SYSTEM = (
    "你根据固定窗口快照写本周周报，先给结论。sections 依次三节：overview 概览、problems 问题变化、effects 已装建议的"
    "效果，每节 ≤200 字；at_a_glance ≤80 字一句话总览。效果一节只能引用 rec_outcomes 里 status=ok 的项，其余写「未测」。"
    "所有数字原样来自输入；evidence_ids 只能用输入里的 id 或 metrics 的指标名。不要使用「保证」「一定」「证明有效」。"
    "audience 固定 user。")


def _ok_outcomes(src: dict) -> set[str]:
    return {o.get("outcome_id") or o.get("candidate_id") for o in src.get("rec_outcomes") or []
            if o.get("status") == "ok"} - {None}


def weekly_validate(output: dict, pack: dict) -> list[str]:
    src = _item(pack, "snapshot")
    sections = output.get("sections") or []
    errors = []
    if [s["id"] for s in sections] != SECTION_IDS:
        errors.append("sections 必须依次是 overview / problems / effects")
    ids = _narr_ids(output) + [i for s in sections for i in s.get("evidence_ids") or []]
    errors += foreign_ids(ids, _ids(src))
    effects = next((s for s in sections if s["id"] == "effects"), None)
    ok = _ok_outcomes(src)
    if effects and [i for i in effects["evidence_ids"] if i not in ok and i in _ids(src.get("rec_outcomes"))]:
        errors.append("效果一节引用了未测的建议")
    if effects and not ok and "未测" not in effects["text"]:
        errors.append("没有已测效果时效果一节必须写「未测」")
    texts = _narr_texts(output) + [output.get("at_a_glance", "")] + [s["text"] for s in sections]
    return errors + prose_errors(texts, src, "weekly_report")


def _reports_markdown(src: dict) -> dict:
    """``analysis_reports.*_markdown`` over the snapshot's analysis data, when it has one."""
    analysis = src.get("analysis")
    if not isinstance(analysis, dict):
        return {}
    from tandem_backend import analysis_reports

    out = {}
    for name in ("profile", "bottlenecks", "process"):
        try:
            out[name] = getattr(analysis_reports, f"{name}_markdown")(analysis)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def weekly_fallback(pack: dict, reason: str) -> dict:
    src = _item(pack, "snapshot")
    m, fr = src.get("metrics") or {}, src.get("friction") or {}
    overview = (f"本周 {m.get('sessions', 0)} 个会话、{m.get('hours', 0)} 小时，纠偏 {m.get('corrections', 0)} 条，"
                f"工具失败 {m.get('tool_failures', 0)} 次。")
    problems = fr.get("problems") or []
    classes = fr.get("error_classes") or []
    if problems:
        p = problems[0]
        prob = f"最常见的问题是「{p.get('key') or p.get('type')}」。"
        prob_ids = [p["problem_id"]] if p.get("problem_id") else []
    elif classes:
        prob, prob_ids = f"失败最多的是「{classes[0]['error_class']}」。", []
    else:
        prob, prob_ids = "本周没有突出的问题。", []
    ok = [o for o in src.get("rec_outcomes") or [] if o.get("status") == "ok"]
    effects = (f"已测效果的建议 {len(ok)} 条，详见建议页。" if ok else "已装建议的效果暂未测。")
    sections = [{"id": "overview", "title": "概览", "text": overview, "evidence_ids": ["sessions"] if m else []},
                {"id": "problems", "title": "问题变化", "text": prob, "evidence_ids": prob_ids},
                {"id": "effects", "title": "建议效果", "text": effects,
                 "evidence_ids": [o.get("outcome_id") or o.get("candidate_id") for o in ok][:3]}]
    out = {"summary": overview[:40], "findings": [], "next_step": prob, "caveats": [TEMPLATE_NOTE],
           "main_evidence_ids": [], "audience": "user", "sections": sections, "at_a_glance": overview[:80]}
    markdown = _reports_markdown(src)
    return {**out, "markdown": markdown} if markdown else out


def weekly_finalize(output: dict, pack: dict, source: str) -> dict:
    src = _item(pack, "snapshot")
    return _result(WEEKLY_TASK, pack, "snapshot", {**output, "window": src.get("window")}, source)


WEEKLY_TASK = _task(
    "narrate.weekly", "L3", "snapshot", system=WEEKLY_SYSTEM, schema=WEEKLY_SCHEMA,
    validate=weekly_validate, fallback=weekly_fallback, finalize=weekly_finalize,
    empty=lambda pack: not ((_item(pack, "snapshot").get("metrics") or {}).get("sessions")), budget=10_000,
    out=1_500, title="周报叙述")

# ---------------------------------------------------------------- narrate.persona (AI-05.4)

AXES = ["D", "P", "M", "V"]
PERSONA_BANNED = ("性格", "人格测试")
PERSONA_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False,
    "required": ["headline", "traits", "tradeoffs", "blind_spots", "caveats"],
    "properties": {
        "headline": {"type": "string", "minLength": 1, "maxLength": 30},
        "traits": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "metric", "value_ref"],
            "properties": {"text": {"type": "string", "maxLength": 8}, "metric": {"type": "string"},
                           "value_ref": {"type": "number"}}}},
        "tradeoffs": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["axis", "text"],
            "properties": {"axis": {"enum": AXES}, "text": {"type": "string", "maxLength": 50}}}},
        "blind_spots": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False, "required": ["problem_id", "text"],
            "properties": {"problem_id": {"type": "string"}, "text": {"type": "string", "maxLength": 50}}}},
        "caveats": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 40}},
    },
}
PERSONA_SYSTEM = (
    "你根据协作画像为用户写一段自述式解读。headline ≤30 字，包含类型名；任一轴 letter 为 ? 时必须写「暂定」。"
    "traits ≤5 条，每条 ≤8 字，metric 写输入里数值字段的路径（如 axes.D.value、rates.planning_rate），value_ref 原样"
    "抄该值。tradeoffs 说明某一轴（D/P/M/V）的取舍；blind_spots 只能引用输入 problems 里的 problem_id。"
    "不要出现「性格」「人格测试」。所有数字原样来自输入。")


def metric_paths(value, prefix: str = "") -> dict[str, float]:
    """Numeric leaves of the profile as ``a.b.0.c`` paths."""
    out: dict[str, float] = {}
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for k, v in items:
        path = f"{prefix}{k}"
        if isinstance(v, (dict, list)):
            out.update(metric_paths(v, path + "."))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[path] = float(v)
    return out


def _tentative(src: dict) -> bool:
    return any(isinstance(a, dict) and a.get("letter") == "?" for a in (src.get("axes") or {}).values())


def persona_validate(output: dict, pack: dict) -> list[str]:
    src = _item(pack, "persona")
    paths = metric_paths({k: v for k, v in src.items() if k != "key"})
    errors = []
    for t in output.get("traits") or []:
        if t["metric"] not in paths:
            errors.append(f"指标不在输入中：{t['metric']}")
        elif abs(paths[t["metric"]] - t["value_ref"]) > 1e-6:
            errors.append(f"value_ref 与输入不符：{t['metric']}")
    problems = {p.get("problem_id") for p in src.get("problems") or []}
    errors += foreign_ids([b["problem_id"] for b in output.get("blind_spots") or []], problems)
    if _tentative(src) and "暂定" not in output.get("headline", ""):
        errors.append("有轴未定时 headline 必须写「暂定」")
    texts = [output.get("headline", "")] + [t["text"] for t in output.get("traits") or []] + \
            [t["text"] for t in output.get("tradeoffs") or []] + [b["text"] for b in output.get("blind_spots") or []] + \
            list(output.get("caveats") or [])
    return errors + prose_errors(texts, src, "profile", PERSONA_BANNED)


def persona_fallback(pack: dict, reason: str) -> dict:
    """Type-library template: headline from the type name, traits from the top observations."""
    src = _item(pack, "persona")
    name = src.get("type_name") or src.get("code") or "协作画像"
    headline = f"{name}（暂定）" if _tentative(src) else str(name)
    traits = [{"text": str(o.get("label") or "")[:8], "metric": f"observations.{i}.sessions",
               "value_ref": float(o["sessions"])}
              for i, o in enumerate(src.get("observations") or []) if isinstance(o.get("sessions"), (int, float))]
    blind = [{"problem_id": p["problem_id"], "text": f"「{p.get('key') or p.get('type') or '这个问题'}」反复出现。"[:50]}
             for p in (src.get("problems") or [])[:2] if p.get("problem_id")]
    return {"headline": headline[:30], "traits": traits[:5], "tradeoffs": [], "blind_spots": blind,
            "caveats": [TEMPLATE_NOTE[:40]]}


def persona_finalize(output: dict, pack: dict, source: str) -> dict:
    src = _item(pack, "persona")
    label = "AI 撰写 · 数字来自指标" if source not in ("fallback", "empty") else None
    return _result(PERSONA_TASK, pack, "persona", {**output, "code": src.get("code"), "label": label}, source)


PERSONA_TASK = _task(
    "narrate.persona", "L3", "persona", system=PERSONA_SYSTEM, schema=PERSONA_SCHEMA,
    validate=persona_validate, fallback=persona_fallback, finalize=persona_finalize,
    empty=lambda pack: not (_item(pack, "persona").get("axes") or _item(pack, "persona").get("observations")),
    budget=6_000, out=800, title="人格解读文案")

TASKS = {t["task_id"]: t for t in (FEEDBACK_TASK, FAILURE_TASK, TOPIC_TASK, CAUSE_TASK, REVIEW_TASK, WEEKLY_TASK,
                                   PERSONA_TASK)}

# kind for GET /v1/ai/narratives → task id
NARRATIVE_KINDS = {"overview": "narrate.overview", "session_review": "narrate.session_review",
                   "weekly": "narrate.weekly", "persona": "narrate.persona",
                   "failure_names": "cluster.failure_names", "topic_names": "cluster.topic_names",
                   "feedback": "classify.feedback", "failure_cause": "classify.failure_cause"}

__all__ = ["NARRATIVE_KINDS", "TASKS", "metric_paths"]
