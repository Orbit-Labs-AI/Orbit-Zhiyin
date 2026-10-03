"""Analysis-side AI tasks (C1 TaskSpec dicts): facet.session, narrate.overview, ask.question.

Every output passes a code gate before it is kept: ids must come from the pack,
numbers from the pack's number whitelist, prose through `evaluate_text`.
When a gate or the engine fails, the L0 fallback keeps the page populated.
"""

from __future__ import annotations

import re

import jsonschema

from orbit_backend.evaluation.readability import evaluate_text

from . import ask as L0
from . import queries
from .pack import content_hash
from .redact import compact, est_tokens

try:
    from orbit_backend.ai.errors import CallFailed
except ImportError:  # runtime (P1) not merged yet
    class CallFailed(Exception):  # noqa: N818 - must match the runtime's class name
        """Placeholder; failures are matched by class name."""


def _call_failed(error: BaseException) -> bool:
    return type(error).__name__ == "CallFailed"


S = "https://json-schema.org/draft/2020-12/schema"

# ---------------------------------------------------------------- numbers whitelist

_NUM = re.compile(r"(?<![A-Za-z0-9_.])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![A-Za-z0-9_])")


# A number followed by one of these is a claimed count/measure about the user's data and must
# come from the query results, however small ("3 个会话", "2 次"). Bare small integers without a
# unit (list ordinals, "第 1 步", "top 3") stay exempt.
_UNIT = re.compile(r"\s*(?:个|次|条|项|天|周|小时|分钟|秒|轮|份|处|倍|种|类|session|call|time)")


def numbers_ok(text: str, numbers) -> list[str]:
    """Numbers in `text` that are not in the whitelist (empty list = ok).

    Tolerance ±0.051; a percentage may match its fraction and vice versa; integers ≤10
    without a unit pass (ordinals, list positions), with a unit they must be whitelisted.
    """
    allowed = [float(n) for n in numbers or []]
    text = text or ""
    bad = []
    for m in _NUM.finditer(text):
        raw = m.group(0)
        v = float(raw.rstrip("%").replace(",", ""))
        if (v == int(v) and abs(v) <= 10 and not raw.endswith("%")
                and not _UNIT.match(text, m.end())):
            continue
        forms = (v, v / 100, v * 100)
        if not any(abs(f - a) <= 0.051 for f in forms for a in allowed):
            bad.append(raw)
    return bad


def _flat_refs(pack: dict) -> set[str]:
    return {i for ids in (pack.get("refs") or {}).values() for i in ids}


# ---------------------------------------------------------------- facet.session (AI-03)

TASK_TYPES = ["feature", "bugfix", "refactor", "review", "docs", "research", "ops_deploy", "data", "config",
              "chat", "other"]
OUTCOMES = ["fully_achieved", "mostly_achieved", "partially_achieved", "not_achieved", "unclear"]
FRICTIONS = ["wrong_approach", "misunderstood_request", "excessive_changes", "buggy_output", "tool_env_failure",
             "permission_friction", "process_overhead", "context_loss", "parallel_conflict", "quota_interrupt",
             "other"]
FEEDBACK = ["accept", "correct", "refine", "requirement_change", "new_task", "clarify", "other"]
DIMENSIONS = ["clarity", "brevity", "grounding", "actionability", "autonomy", "planning", "verification", "scope",
              "convention", "other"]

FACET_ITEM = {
    "type": "object", "additionalProperties": False,
    "required": ["session_uid", "goal", "task_type", "outcome", "friction_types", "candidates",
                 "repeated_instructions", "summary", "chunked"],
    "properties": {
        "session_uid": {"type": "string"},
        "goal": {"type": "string", "maxLength": 40},
        "task_type": {"enum": TASK_TYPES},
        "outcome": {"enum": OUTCOMES},
        "friction_types": {"type": "array", "items": {"enum": FRICTIONS}, "uniqueItems": True},
        "candidates": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["signal_id", "event_uid", "is_correction", "feedback_kind", "friction_type", "confidence"],
            "properties": {"signal_id": {"type": "string"}, "event_uid": {"type": "string"},
                           "is_correction": {"type": "boolean"}, "feedback_kind": {"enum": FEEDBACK},
                           "friction_type": {"enum": [*FRICTIONS, "none"]},
                           "confidence": {"enum": ["high", "medium", "low"]}}}},
        "repeated_instructions": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False, "required": ["text_redacted", "dimension"],
            "properties": {"text_redacted": {"type": "string", "maxLength": 80},
                           "dimension": {"enum": DIMENSIONS}}}},
        "summary": {"type": "string", "maxLength": 40},
        "chunked": {"type": "boolean"},
    },
}
FACET_SCHEMA = {"$schema": S, "type": "object", "additionalProperties": False, "required": ["items"],
                "properties": {"items": {"type": "array", "items": FACET_ITEM}}}
_FACET_V = jsonschema.Draft202012Validator(FACET_ITEM)

FACET_SYSTEM = (
    "你为编码 Agent 会话做结构化标注。每个输入项是一个会话（ref_id = session_uid），只依据输入内容作答。\n"
    "goal 只写用户明确提出的请求（≤40 字）；summary ≤40 字；极短或闲聊会话 task_type=chat。\n"
    "candidates 只能引用输入 candidates 里出现的 signal_id 与 event_uid；confidence 是闭集，不是概率。\n"
    "friction_types 只能来自你给 candidates 标的 friction_type，或输入 row.tool_errors>0 时的 tool_env_failure。\n"
    "repeated_instructions 记录用户多次重复的要求，text_redacted ≤80 字，不要包含姓名、路径或密钥。\n"
    "chunked 原样抄输入的 chunked（缺省 false）。每个输入会话输出一项，按 session_uid 对齐。")


def facet_prompt(items: dict) -> str:
    lines = [compact({"ref_id": uid, "chunked": bool(p.get("chunked")), **{k: v for k, v in p.items()
                                                                          if k != "chunked"}})
             for uid, p in items.items()]
    return "<sessions>\n" + "\n".join(lines) + "\n</sessions>\n为以上每个会话输出一项 session_facet。"


def check_facet(item: dict, payload: dict) -> tuple[dict, list[str]]:
    """Gate one facet against its own session input. Foreign candidates are dropped, not fatal."""
    errors = [e.message for e in _FACET_V.iter_errors(item)]
    if errors:
        return item, errors
    events = {m["event_uid"] for k in ("human_messages", "assistant_replies") for m in payload.get(k) or []}
    signals = {c["signal_id"]: c["event_uid"] for c in payload.get("candidates") or []}
    events |= set(signals.values())
    kept = [c for c in item["candidates"] if signals.get(c["signal_id"]) == c["event_uid"] and c["event_uid"] in events]
    grounded = {c["friction_type"] for c in kept if c["friction_type"] != "none"}
    if (payload.get("row") or {}).get("tool_errors"):
        grounded.add("tool_env_failure")
    loose = [f for f in item["friction_types"] if f not in grounded]
    if loose:
        return item, [f"friction_types 没有证据：{', '.join(loose)}"]
    return {**item, "candidates": kept, "chunked": bool(payload.get("chunked"))}, []


def _facet_call(ctx, uids: list[str], items: dict) -> dict:
    try:
        out = ctx.call(prompt=facet_prompt({u: items[u] for u in uids}), schema=FACET_SCHEMA,
                       validate=lambda output, pack: [])
    except Exception as error:  # noqa: BLE001 - CallFailed is matched by name
        if not _call_failed(error):
            raise
        ctx.log(f"{len(uids)} 个会话调用失败：{error}")
        return {}
    good = {}
    for item in (out or {}).get("items") or []:
        uid = item.get("session_uid") if isinstance(item, dict) else None
        if uid in uids and uid not in good:
            cleaned, errors = check_facet(item, items[uid])
            if errors:
                ctx.log(f"{uid[:12]} 未通过校验：{errors[0]}")
            else:
                good[uid] = cleaned
    return good


def facet_run(ctx, pack: dict) -> dict:
    items = pack["content"].get("items") or {}
    ids = list(items)
    batches = pack.get("batches") or [ids[i:i + 8] for i in range(0, len(ids), 8)]
    task = ctx.task or FACET_TASK
    ctx.stage("pack", "ok", f"{len(ids)} 个会话 · {len(batches)} 批")
    ctx.stage("draft", "running")
    facets, failed, aborted = [], 0, False
    for n, batch in enumerate(batches, 1):
        if ctx.cancelled():
            aborted = True
            break
        good = _facet_call(ctx, batch, items)
        missing = [u for u in batch if u not in good]
        if missing:
            ctx.log(f"第 {n} 批缺 {len(missing)} 项，单独重试")
            good.update(_facet_call(ctx, missing, items))
        bad = [u for u in batch if u not in good]
        failed += len(bad)
        for uid in batch:
            facets.append({"session_uid": uid, "content_hash": content_hash(items[uid]),
                           "prompt_version": task["prompt_version"], "schema_version": task["schema_version"],
                           "status": "ok" if uid in good else "failed",
                           "json": good.get(uid)})
        ctx.progress(n, len(batches))
        if len(bad) * 2 > len(batch):
            aborted = n < len(batches)
            ctx.log(f"第 {n} 批失败过半，停止后续批次")
            break
    ok = len(facets) - failed
    ctx.stage("draft", "ok" if not failed and not aborted else "failed")
    ctx.stage("review", "ok", f"{ok} 个通过 · {failed} 个失败")
    status = "ok" if not failed and not aborted else ("failed" if ok == 0 and ids else "partial")
    if not ids:
        status = "ok"
    return {"status": status, "result": {"sessions": len(ids), "ok": ok, "failed": failed, "aborted": aborted,
                                         "skipped": len(ids) - len(facets)},
            "artifact": None, "facets": facets}


FACET_TASK = {
    "task_id": "facet.session", "tier": "L2", "slot": "cheap", "prompt_version": "facet@1.1",
    "schema_version": "1.1", "input_budget": 40_000, "out_budget": 4_000, "max_budget_usd": 0.1,
    "timeout_s": 120, "engines": ("claude_code", "codex", "api_key", "fake"),
    "pack_items": [("items", True)], "requires_preview": False, "cache_ttl_s": None,
    "stages": ["pack", "draft", "review"], "system": FACET_SYSTEM, "schema": FACET_SCHEMA,
    "build_prompt": lambda pack: facet_prompt(pack["content"].get("items") or {}),
    "validate": None, "fallback": None, "finalize": None, "run": facet_run,
}

# ---------------------------------------------------------------- narrate.overview (AI-05.1)

SCENES = ["good", "stuck", "next"]
NARRATE_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False,
    "required": ["summary", "findings", "next_step", "caveats", "main_evidence_ids", "audience"],
    "properties": {
        "summary": {"type": "string", "maxLength": 40},
        "findings": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "text", "scene", "evidence_ids"],
            "properties": {"title": {"type": "string", "maxLength": 20}, "text": {"type": "string", "maxLength": 60},
                           "scene": {"enum": SCENES}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}}},
        "next_step": {"type": "string", "maxLength": 80},
        "caveats": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 80}},
        "main_evidence_ids": {"type": "array", "items": {"type": "string"}},
        "audience": {"enum": ["user", "developer"]},
    },
}
NARRATE_SYSTEM = (
    "你根据给定指标为用户写一段周期概览，先给结论。findings 依次写三段：做得好(scene=good)、卡在哪(scene=stuck)、"
    "立刻可做(scene=next)，每段 ≤60 字。所有数字必须原样来自输入；evidence_ids 只能用输入里出现的 "
    "session_uid / event_uid / problem_id / candidate_id / 指标名。不要使用「保证」「一定」「证明有效」。"
    "卡在哪必须引用 problem_id 或错误类别；立刻可做只能引用输入里的 candidate_id。audience 固定 user。"
    "<scope> 给出时，数据只覆盖其中的 Agent（agent_ids）与项目（project_id），不要推及其他 Agent 或项目。")


SCOPE_KEYS = ("days", "start_ms", "end_ms", "project_id", "agent_ids")


def narrate_scope(pack: dict) -> dict:
    """The view an overview describes (window, project, agent subset). It is part of the
    prompt, so the cache key and the input fingerprint differ per filter, and the model knows
    the numbers cover only those agents / that project."""
    scope = pack.get("scope") or {}
    return {k: scope[k] for k in SCOPE_KEYS if scope.get(k) not in (None, "", [])}


def narrate_prompt(pack: dict) -> str:
    scope = narrate_scope(pack)
    head = "<scope>\n" + compact(scope) + "\n</scope>\n" if scope else ""
    return head + "<input>\n" + compact(pack["content"]) + "\n</input>"


def _texts(output: dict) -> list[str]:
    out = [output.get("summary", ""), output.get("next_step", "")] + list(output.get("caveats") or [])
    for f in output.get("findings") or []:
        out += [f.get("title", ""), f.get("text", "")]
    return [t for t in out if t]


def narrate_validate(output: dict, pack: dict) -> list[str]:
    errors = []
    refs = _flat_refs(pack)
    ids = list(output.get("main_evidence_ids") or []) + [i for f in output.get("findings") or []
                                                         for i in f.get("evidence_ids") or []]
    foreign = [i for i in ids if i not in refs]
    if foreign:
        errors.append(f"evidence_ids 不在输入中：{', '.join(foreign[:5])}")
    text = "\n".join(_texts(output))
    bad = numbers_ok(text, pack.get("numbers"))
    if bad:
        errors.append(f"数字不在输入中：{', '.join(bad[:5])}")
    issues = evaluate_text(text, "status_update")["issues"]
    errors += [f"可读性：{i['code']}" for i in issues if i["severity"] == "error"]
    return errors


def _pct(x) -> str:
    return f"{round((x or 0) * 100, 1):g}%"


def narrate_fallback(pack: dict, reason: str) -> dict:
    """L0 template: 做得好 / 卡在哪 / 立刻可做 from metrics, friction and candidates."""
    c = pack.get("content") or {}
    m, fr, cands = c.get("metrics") or {}, c.get("friction") or {}, c.get("candidates") or []
    prev = m.get("prev") or {}
    findings = []
    if m.get("sessions"):
        good = f"本期 {m['sessions']} 个会话、{m.get('hours', 0)} 小时，工具失败率 {_pct(m.get('tool_failure_rate'))}"
        if prev and prev.get("tool_failure_rate") is not None:
            good += f"（上期 {_pct(prev['tool_failure_rate'])}）"
        findings.append({"title": "做得好", "text": good + "。", "scene": "good", "evidence_ids": ["sessions"]})
    problems, classes = fr.get("problems") or [], fr.get("error_classes") or []
    if problems:
        p = problems[0]
        findings.append({"title": "卡在哪", "text": f"最常见的问题是「{p.get('key') or p.get('type')}」。",
                         "scene": "stuck", "evidence_ids": [p["problem_id"]] if p.get("problem_id") else []})
    elif classes:
        findings.append({"title": "卡在哪", "text": f"失败最多的是「{classes[0]['error_class']}」，"
                         f"共 {classes[0]['count']} 次。", "scene": "stuck", "evidence_ids": ["tool_failures"]})
    elif m.get("corrections"):
        findings.append({"title": "卡在哪", "text": f"纠偏消息 {m['corrections']} 条，纠偏率 "
                         f"{_pct(m.get('correction_rate'))}。", "scene": "stuck", "evidence_ids": ["corrections"]})
    if cands:
        top = cands[0]
        findings.append({"title": "立刻可做", "text": f"先试「{top.get('title')}」。", "scene": "next",
                         "evidence_ids": [top["candidate_id"]] if top.get("candidate_id") else []})
    else:
        findings.append({"title": "立刻可做", "text": "把最常见的卡点写成一条规则，下周再对比。", "scene": "next",
                         "evidence_ids": []})
    summary = findings[0]["text"][:40] if findings else "这段时间还没有可分析的会话。"
    return {"summary": summary, "findings": findings[:3], "next_step": findings[-1]["text"],
            "caveats": ["这是模板生成的概览，未经过模型个性化。"],
            "main_evidence_ids": [i for f in findings for i in f["evidence_ids"]][:3], "audience": "user"}


def narrate_finalize(output: dict, pack: dict, source: str) -> dict:
    src = "template" if source == "fallback" else source
    return {"status": "fallback" if source == "fallback" else "ok",
            "result": {**output, "source": src, "prompt_version": NARRATE_TASK["prompt_version"]},
            "artifact": None, "facets": None}


NARRATE_TASK = {
    "task_id": "narrate.overview", "tier": "L3", "slot": "main", "prompt_version": "narrate.overview@1",
    "schema_version": "1", "input_budget": 10_000, "out_budget": 800, "max_budget_usd": 0.5, "timeout_s": 180,
    "engines": ("claude_code", "codex", "api_key", "fake"),
    "pack_items": [("metrics", True), ("friction", True), ("candidates", True), ("sessions", False)],
    "requires_preview": False, "cache_ttl_s": None, "stages": ["pack", "draft", "check"],
    "system": NARRATE_SYSTEM, "schema": NARRATE_SCHEMA, "build_prompt": narrate_prompt,
    "validate": narrate_validate, "fallback": narrate_fallback, "finalize": narrate_finalize, "run": None,
}

# ---------------------------------------------------------------- ask.question (AI-09)

INTENTS = ["compare_previous", "top_action", "explain_metric", "persona_why", "persona_tradeoff", "blind_spot",
           "rank_recs", "pair_recs", "session_stuck", "session_opening", "write_rule", "tool_worst", "approvals",
           "mcp_unused", "project_habits", "phrases", "catalog_fit", "other"]
PLAN_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False, "required": ["intents", "queries"],
    "properties": {
        "intents": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"enum": INTENTS}},
        "queries": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False, "required": ["api", "params"],
            "properties": {"api": {"enum": list(queries.APIS)}, "params": {"type": "object"}}}},
    },
}
ANSWER_SCHEMA = {
    "$schema": S, "type": "object", "additionalProperties": False, "required": ["answer", "refs", "next"],
    "properties": {
        "answer": {"type": "string", "maxLength": 300},
        "refs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "id"],
            "properties": {"kind": {"enum": ["session", "event", "problem", "candidate", "metric"]},
                           "id": {"type": "string"}}}},
        "next": {"enum": ["studio", "recs", "sessions", "tools", "none"]},
    },
}
PLAN_SYSTEM = (
    "把用户关于自己 Agent 使用数据的问题分类成意图，并规划 ≤3 个只读查询。可用查询与参数：\n"
    + "\n".join(f"- {api}: {sorted(s['properties'])}" for api, s in queries.SCHEMAS.items())
    + "\nscope 形如 {\"days\": 30}（≤365）；limit ≤20；q ≤80 字。与数据无关的问题 intents=[\"other\"]、queries=[]。")
ANSWER_SYSTEM = (
    "根据查询结果回答用户的问题，≤300 字，先给结论。数字必须原样来自查询结果；refs 只能引用查询结果里的 id。"
    "next：需要生成规则/Hook 时 studio，看建议 recs，看会话 sessions，看工具 tools，否则 none。")
ANSWER_BUDGET = 12_000


# Data class each whitelisted query's rows belong to (consent.DATA_CLASSES). corrections /
# evidence / search return (redacted) user or agent wording -> snippets; the rest are counts,
# session rows and tool sequences -> summary. Unlisted APIs default to snippets (fail closed).
API_DATA_CLASS = {"corrections": "snippets", "evidence": "snippets", "search": "snippets",
                  "metrics": "summary", "sessions": "summary", "problems": "summary",
                  "projects": "summary", "tools": "summary", "inventory": "summary"}


def _granted(ctx, data_class: str) -> bool:
    check = getattr(ctx, "granted", None)
    return bool(check(data_class)) if check is not None else data_class == "summary"


def _ask_question(ctx, pack: dict) -> str:
    goal = (pack["content"].get("goal") or {}).get("text") or pack.get("goal") or ""
    return goal or (ctx.params or {}).get("question", "")


def ask_run(ctx, pack: dict) -> dict:
    question = _ask_question(ctx, pack)
    context = (ctx.params or {}).get("context", "overview")
    ctx.stage("pack", "ok")
    ctx.stage("analyse", "running", "规划查询")
    try:
        plan = ctx.call(slot="cheap", task_id="ask.plan", system=PLAN_SYSTEM, schema=PLAN_SCHEMA,
                        prompt=compact({"question": question, "page": context}), validate=lambda o, p: [])
    except Exception as error:  # noqa: BLE001
        if not _call_failed(error):
            raise
        return _ask_fallback(question, context, getattr(error, "reason", None) or str(error))
    intents = list(plan.get("intents") or [])
    kept = []
    for q in plan.get("queries") or []:
        try:
            params = queries.check(q.get("api"), q.get("params"))
            # Model planning cannot widen the selection confirmed by the user.
            if "scope" in queries.SCHEMAS[q["api"]]["properties"] and pack.get("scope"):
                params = {**params, "scope": {k: v for k, v in pack["scope"].items()
                                             if k in queries._FIELDS["scope"]["properties"]}}
            if "session_uid" in queries.SCHEMAS[q["api"]]["properties"] and ctx.params.get("session_uid"):
                params = {**params, "session_uid": ctx.params["session_uid"]}
            kept.append({"api": q["api"], "params": queries.check(q["api"], params)})
        except (ValueError, KeyError, TypeError) as error:
            ctx.log(f"丢弃越界查询：{error}")
    planned, kept, withheld = kept, [], set()
    for q in planned:
        data_class = API_DATA_CLASS.get(q["api"], "snippets")
        if _granted(ctx, data_class):
            kept.append(q)
        else:
            withheld.add(data_class)
            ctx.log(f"未授权 {data_class}，跳过查询 {q['api']}")
    if planned and not kept and intents != ["other"]:
        ctx.stage("analyse", "skipped", "需要授权")
        return _ask_fallback(question, context, "consent_required", missing=sorted(withheld))
    if not kept or intents == ["other"]:
        ctx.stage("analyse", "skipped", "超出范围")
        return {"status": "ok", "result": {**L0.out_of_scope(question), "intents": intents, "queries": kept,
                                           "source": "ai"}, "artifact": None, "facets": None}
    results, refs, numbers = [], set(), set()
    home = getattr(ctx, "home", None) or (ctx.params or {}).get("home")
    for q in kept:
        appdb = getattr(getattr(getattr(ctx, "runner", None), "svc", None), "appdb", None)
        r = queries.run(q["api"], q["params"], reads=ctx.reads, appdb=appdb, home=home)
        results.append(r)
        refs |= {(x["kind"], x["id"]) for x in r["refs"]}
        numbers |= set(r["numbers"])
    while est_tokens(results) > ANSWER_BUDGET and any(len(r["rows"]) > 1 for r in results):
        biggest = max(results, key=lambda r: len(r["rows"]))
        biggest["rows"] = biggest["rows"][:len(biggest["rows"]) // 2]
    ctx.stage("analyse", "ok", f"{len(kept)} 个查询")
    ctx.stage("draft", "running")

    def validate(output, _pack):
        errors = [f"引用不在查询结果中：{r['kind']}:{r['id']}" for r in output.get("refs") or []
                  if (r.get("kind"), r.get("id")) not in refs]
        bad = numbers_ok(output.get("answer", ""), numbers)
        return errors + ([f"数字不在查询结果中：{', '.join(bad[:5])}"] if bad else [])

    try:
        answer = ctx.call(slot="main", task_id="ask.answer", system=ANSWER_SYSTEM, schema=ANSWER_SCHEMA,
                          prompt=compact({"question": question, "results": results}), validate=validate)
    except Exception as error:  # noqa: BLE001
        if not _call_failed(error):
            raise
        return _ask_fallback(question, context, getattr(error, "reason", None) or str(error))
    ctx.stage("draft", "ok")
    return {"status": "ok", "result": {"answer": answer["answer"], "refs": answer["refs"], "next": answer["next"],
                                       "intents": intents, "queries": kept, "source": "ai"},
            "artifact": None, "facets": None}


# Why a free-form question got no AI answer. The UI shows ``message`` and can act on
# ``error_code`` (open the consent dialog, the engine settings, retry) instead of telling the
# user the question was out of scope.
ASK_ERRORS = {
    "consent_required": "回答这个问题需要读取脱敏片段，当前引擎还没有这类数据的授权。",
    "engine_unavailable": "本地 Agent 引擎不可用（未安装、未登录或调用出错）。",
    "timeout": "本地 Agent 响应超时，请稍后重试。",
    "budget_exceeded": "这次调用超出了单次花费上限。",
    "truncated": "模型输出被截断，没有得到完整答案。",
    "refused": "模型拒绝回答这个问题。",
    "invalid_output": "模型给出的答案未通过校验（数字或引用与查询结果不一致）。",
}
_ENGINE_CODES = {"not_logged_in": "engine_unavailable", "engine_error": "engine_unavailable",
                 "timeout": "timeout", "budget_exceeded": "budget_exceeded", "truncated": "truncated",
                 "refused": "refused"}


def _error_code(reason: str) -> str:
    head = str(reason or "").split(":", 1)[0].strip()
    if head in ASK_ERRORS:
        return head
    return _ENGINE_CODES.get(head, "invalid_output")


def _ask_fallback(question: str, context: str, reason: str, missing: list[str] | None = None) -> dict:
    code = _error_code(reason)
    result = {"answer": ASK_ERRORS[code], "refs": [], "next": "none", "pages": L0.route_pages(question),
              "intents": [], "queries": [], "source": "template", "error_code": code, "reason": str(reason)}
    if missing:
        result["missing"] = missing
    return {"status": "fallback", "result": result, "artifact": None, "facets": None}


ASK_TASK = {
    "task_id": "ask.question", "tier": "L3", "slot": "main", "prompt_version": "ask@1", "schema_version": "1",
    "input_budget": 14_000, "out_budget": 1_200, "max_budget_usd": 0.5, "timeout_s": 180,
    "engines": ("claude_code", "codex", "api_key", "fake"), "pack_items": [("goal", True)],
    "requires_preview": False, "cache_ttl_s": 3600, "stages": ["pack", "analyse", "draft"],
    "system": ANSWER_SYSTEM, "schema": ANSWER_SCHEMA,
    "build_prompt": lambda pack: compact({"question": (pack["content"].get("goal") or {}).get("text")}),
    "validate": None, "fallback": None, "finalize": None, "run": ask_run,
}

TASKS = {t["task_id"]: t for t in (FACET_TASK, NARRATE_TASK, ASK_TASK)}

__all__ = ["TASKS", "CallFailed", "numbers_ok", "check_facet"]
