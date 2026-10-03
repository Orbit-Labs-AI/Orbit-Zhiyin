"""v1 AI tasks (AI-04.1–04.4, AI-05.2–05.4): pack loaders, gates, L0 fallbacks, finalize."""

from __future__ import annotations

import pytest
from ai_analysis_fakectx import DAY, NOW, FakeCtx

from orbit_backend.ai import pack as P
from orbit_backend.ai.tasks_v1 import TASKS, metric_paths

SCOPE = {"start_ms": NOW - 30 * DAY, "end_ms": NOW + DAY}


def build(task_id, tdb=None, appdb=None, home=None, params=None, slots=None):
    if tdb is not None:
        tdb.commit()
    return P.build(TASKS[task_id], reads=tdb.reads if tdb else None, appdb=appdb, home=home, scope=SCOPE,
                   params=params, slots=slots)


def run(task_id, pack, *responses):
    ctx = FakeCtx(TASKS[task_id], pack, responses)
    return ctx, TASKS[task_id]["run"](ctx, pack)


def result_event(tdb, call_uid, session_uid, text):
    tdb.event(session_uid, "tool.result", "tool", text, NOW, f"{call_uid}-r")
    tdb.db.execute("UPDATE tool_call SET result_event_uid=? WHERE call_uid=?", (f"{call_uid}-r", call_uid))


# ---------------------------------------------------------------- classify.feedback

def feedback_db(tdb):
    tdb.session("s1")
    for i, (actor, text) in enumerate([("human", "请修复登录测试"), ("assistant", "我改了 UI 测试"),
                                       ("human", "不对，我说的是 API 测试"), ("human", "谢谢")]):
        kind = "message.user" if actor == "human" else "message.assistant"
        tdb.event("s1", kind, actor, text, NOW - DAY + i * 1000, f"s1-{'h' if actor == 'human' else 'a'}{i}")


def test_feedback_pack_and_ai_merge(tdb, appdb, orbit_home):
    feedback_db(tdb)
    pack = build("classify.feedback", tdb, appdb, orbit_home, params={"session_uids": ["s1"]})
    items = pack["content"]["feedback_items"]["items"]
    assert [i["event_uid"] for i in items] == ["s1-h2"]
    assert items[0]["prev_assistant"] == "我改了 UI 测试" and items[0]["context"] == "task"
    ai = {"items": [{"signal_id": "sig:s1-h2", "is_correction": True, "feedback_kind": "correct",
                     "friction_type": "misunderstood_request", "sentiment": "negative", "confidence": "high"}]}
    ctx, out = run("classify.feedback", pack, ai)
    assert out["status"] == "ok" and out["result"]["source"] == "ai"
    item = out["result"]["items"][0]
    assert item["type_source"] == "facet" and item["session_uid"] == "s1" and item["confidence"] == "high"
    assert "<input>" in ctx.calls[0]["prompt"] and "sig:s1-h2" in ctx.calls[0]["prompt"]


def test_feedback_foreign_id_falls_back_to_rule(tdb, appdb, orbit_home):
    feedback_db(tdb)
    pack = build("classify.feedback", tdb, appdb, orbit_home, params={"event_uids": ["s1-h2"]})
    bad = {"items": [{"signal_id": "sig:made-up", "is_correction": True, "feedback_kind": "correct",
                      "friction_type": "none", "sentiment": "neutral", "confidence": "low"}]}
    ctx, out = run("classify.feedback", pack, bad, bad)
    assert len(ctx.calls) == 2 and "引用不在输入中" in ctx.calls[1]["errors"][0]
    assert out["status"] == "fallback" and out["result"]["source"] == "template"
    item = out["result"]["items"][0]
    assert item["type_source"] == "rule" and item["rejudge"] and item["is_correction"]
    assert out["result"]["key"] == "s1-h2"


def test_feedback_empty_never_calls_engine(tdb, appdb, orbit_home):
    tdb.session("s1", humans=["好的", "继续"])
    pack = build("classify.feedback", tdb, appdb, orbit_home, params={"session_uids": ["s1"]})
    ctx, out = run("classify.feedback", pack)
    assert ctx.calls == [] and out["result"] == {"key": "default", "items": [], "source": "empty",
                                                 "prompt_version": "classify.feedback@1"}


# ---------------------------------------------------------------- cluster.failure_names

def failures_db(tdb):
    tdb.session("s1", tools=[("bash", "shell", "pytest", "failed", "test_failed"),
                             ("bash", "shell", "pytest", "failed", "test_failed"),
                             ("edit", "edit", None, "failed", "not_found")])
    result_event(tdb, "s1-c0", "s1", "FAILED tests/test_a.py::test_x - AssertionError")


def test_failure_names_groups_and_ai(tdb, appdb, orbit_home):
    failures_db(tdb)
    pack = build("cluster.failure_names", tdb, appdb, orbit_home)
    groups = pack["content"]["failures"]["groups"]
    assert [g["error_class"] for g in groups] == ["test_failed", "not_found"]
    assert groups[0]["members"][0]["text"].startswith("FAILED") or groups[0]["members"][1]["text"]
    ai = {"clusters": [{"error_class": "test_failed", "name": "测试断言失败", "member_ids": ["s1-c0"]}]}
    _, out = run("cluster.failure_names", pack, ai)
    clusters = {c["error_class"]: c for c in out["result"]["clusters"]}
    assert clusters["test_failed"] == {"error_class": "test_failed", "count": 2, "name": "测试断言失败",
                                       "member_ids": ["s1-c0"], "named_by": "ai"}
    assert clusters["not_found"]["name"] == "找不到文件或命令" and clusters["not_found"]["named_by"] == "rule"


def test_failure_names_gate(tdb, appdb, orbit_home):
    failures_db(tdb)
    pack = build("cluster.failure_names", tdb, appdb, orbit_home)
    validate = TASKS["cluster.failure_names"]["validate"]
    errors = validate({"clusters": [{"error_class": "test_failed", "name": "失败 3 次", "member_ids": ["s1-c2"]},
                                    {"error_class": "nope", "name": "x", "member_ids": []}]}, pack)
    assert any("引用不在输入中" in e for e in errors) and any("数字" in e for e in errors)
    assert any("nope" in e for e in errors)


# ---------------------------------------------------------------- cluster.topic_names

CLUSTERS = [{"cluster_id": 0, "size": 5, "top_terms": ["css", "布局"], "summaries": ["调整页面样式"]},
            {"cluster_id": 1, "size": 3, "top_terms": ["pytest"], "summaries": ["修测试"]}]


def test_topic_names_ai_and_fallback():
    pack = build("cluster.topic_names", params={"clusters": CLUSTERS, "key": "scan-1"})
    ai = {"clusters": [{"cluster_id": "0", "name": "前端样式调整", "kind": "task", "confidence": "high"}]}
    _, out = run("cluster.topic_names", pack, ai)
    res = out["result"]
    assert res["key"] == "scan-1" and res["display_only"]
    assert res["clusters"][0]["name"] == "前端样式调整" and res["clusters"][0]["label"] == "AI 命名"
    assert res["clusters"][1] == {"cluster_id": "1", "top_terms": ["pytest"], "name": "簇 #1", "kind": "other",
                                  "confidence": "low", "label": None}
    assert TASKS["cluster.topic_names"]["validate"](
        {"clusters": [{"cluster_id": "9", "name": "x", "kind": "other", "confidence": "low"}]}, pack)


def test_topic_names_single_cluster_is_skipped():
    pack = build("cluster.topic_names", params={"clusters": CLUSTERS[:1]})
    ctx, out = run("cluster.topic_names", pack)
    assert ctx.calls == [] and out["result"]["source"] == "empty"


# ---------------------------------------------------------------- classify.failure_cause

def test_failure_cause_only_unknown_and_rules(tdb, appdb, orbit_home):
    tdb.session("s1", tools=[("bash", "shell", "rm", "failed", None), ("bash", "shell", "ls", "failed", "timeout"),
                             ("bash", "shell", "curl", "error", "unknown")])
    result_event(tdb, "s1-c0", "s1", "rm: /x: Permission denied")
    pack = build("classify.failure_cause", tdb, appdb, orbit_home)
    items = pack["content"]["unknown_failures"]["items"]
    assert {i["call_uid"] for i in items} == {"s1-c0", "s1-c2"}
    fallback = TASKS["classify.failure_cause"]["fallback"](pack, "off")
    causes = {i["call_uid"]: i["cause"] for i in fallback["items"]}
    assert causes == {"s1-c0": "permission", "s1-c2": "unknown"}
    ai = {"items": [{"call_uid": "s1-c2", "cause": "network", "explanation": "连接被拒绝", "confidence": "medium"}]}
    _, out = run("classify.failure_cause", pack, ai)
    by = {i["call_uid"]: i for i in out["result"]["items"]}
    assert by["s1-c2"]["cause"] == "network" and by["s1-c2"]["classified_by"] == "ai"
    assert by["s1-c0"]["classified_by"] == "rule"
    errors = TASKS["classify.failure_cause"]["validate"](
        {"items": [{"call_uid": "s1-c2", "cause": "other", "explanation": "重试了 37 次", "confidence": "low"}]},
        pack)
    assert errors and "37" in errors[0]


# ---------------------------------------------------------------- narrate.session_review

def review_db(tdb):
    tdb.session("s1", minutes=12, humans=["修一下构建", "不对，别再改 package.json"], replies=["已修改"],
                tools=[("bash", "shell", "npm", "failed", "exit_nonzero"),
                       ("bash", "shell", "npm", "failed", "exit_nonzero")])


REVIEW_OK = {
    "summary": "构建修好了，但被纠正过一次。",
    "findings": [{"title": "做得好", "text": "12 分钟内完成了构建修复。", "scene": "good", "evidence_ids": ["s1"]},
                 {"title": "卡在哪", "text": "npm 连续失败后仍在重试。", "scene": "stuck",
                  "evidence_ids": ["sig:s1-h1"]}],
    "next_step": "开场说明不要改 package.json。", "caveats": [], "main_evidence_ids": ["s1"], "audience": "user",
    "lessons": [{"text": "禁止改 package.json 写进规则", "mechanism": "rule", "evidence_ids": ["s1-h1"]},
                {"text": "改做法：先读报错再重试", "mechanism": "workflow", "evidence_ids": []}]}


def test_session_review_pack_ai_and_handoff(tdb, appdb, orbit_home):
    review_db(tdb)
    pack = build("narrate.session_review", tdb, appdb, orbit_home, params={"session_uid": "s1"})
    src = pack["content"]["session_review"]
    assert src["key"] == "s1" and src["row"]["tool_errors"] == 2
    assert src["key_moments"][0]["kind"] == "failure_run" and src["signals"][0]["event_uid"] == "s1-h1"
    _, out = run("narrate.session_review", pack, REVIEW_OK)
    lessons = out["result"]["lessons"]
    assert out["status"] == "ok" and out["result"]["session_uid"] == "s1"
    assert lessons[0]["handoff"] == {"task_id": "generate.rule", "goal": "禁止改 package.json 写进规则",
                                     "goal_source": "ask", "refs": ["s1-h1"], "params": {"session_uids": ["s1"]}}
    assert "handoff" not in lessons[1]


def test_session_review_gate_and_fallback(tdb, appdb, orbit_home):
    review_db(tdb)
    pack = build("narrate.session_review", tdb, appdb, orbit_home, params={"session_uid": "s1"})
    bad = {**REVIEW_OK, "summary": "这次一定能提升 45 分钟", "main_evidence_ids": ["ghost"]}
    errors = TASKS["narrate.session_review"]["validate"](bad, pack)
    assert any("ghost" in e for e in errors) and any("45" in e for e in errors)
    assert any("可读性" in e for e in errors)
    _, out = run("narrate.session_review", pack, bad, bad)
    res = out["result"]
    assert out["status"] == "fallback" and res["source"] == "template"
    assert [lesson["mechanism"] for lesson in res["lessons"]] == ["hook", "rule"]
    assert res["lessons"][0]["handoff"]["task_id"] == "generate.hook"
    assert not TASKS["narrate.session_review"]["validate"](
        {k: v for k, v in res.items() if k in REVIEW_OK}, pack)


# ---------------------------------------------------------------- narrate.weekly

SNAPSHOT = {"key": "2026-W38", "window": {"start_ms": 1, "end_ms": 2},
            "metrics": {"sessions": 14, "hours": 9.5, "corrections": 6, "tool_failures": 21},
            "friction": {"problems": [{"problem_id": "pb_1", "key": "改错文件", "type": "wrong_approach"}],
                         "error_classes": []},
            "rec_outcomes": [{"outcome_id": "ro_1", "status": "ok"}, {"outcome_id": "ro_2", "status": "pending"}]}


def weekly_output(effects_ids=("ro_1",), effects_text="规则装上后纠偏从 6 条起在下降。"):
    return {"summary": "本周 14 个会话，纠偏 6 条。", "findings": [], "next_step": "先处理改错文件。",
            "caveats": [], "main_evidence_ids": ["sessions"], "audience": "user", "at_a_glance": "14 个会话、9.5 小时。",
            "sections": [{"id": "overview", "title": "概览", "text": "14 个会话、9.5 小时。", "evidence_ids": ["sessions"]},
                         {"id": "problems", "title": "问题", "text": "改错文件最常见。", "evidence_ids": ["pb_1"]},
                         {"id": "effects", "title": "效果", "text": effects_text, "evidence_ids": list(effects_ids)}]}


def test_weekly_ai_and_gates():
    pack = build("narrate.weekly", slots={"snapshot": SNAPSHOT})
    _, out = run("narrate.weekly", pack, weekly_output())
    assert out["status"] == "ok" and out["result"]["key"] == "2026-W38" and out["result"]["window"]["end_ms"] == 2
    validate = TASKS["narrate.weekly"]["validate"]
    assert any("未测" in e for e in validate(weekly_output(("ro_2",)), pack))
    no_ok = build("narrate.weekly", slots={"snapshot": {**SNAPSHOT, "rec_outcomes": []}})
    assert any("未测" in e for e in validate(weekly_output((), "效果不错。"), no_ok))
    swapped = weekly_output()
    swapped["sections"].reverse()
    assert any("依次" in e for e in validate(swapped, pack))


def test_weekly_fallback_template():
    pack = build("narrate.weekly", slots={"snapshot": {**SNAPSHOT, "rec_outcomes": []}})
    _, out = run("narrate.weekly", pack, {"bad": 1}, {"bad": 1})
    res = out["result"]
    assert out["status"] == "fallback" and [s["id"] for s in res["sections"]] == ["overview", "problems", "effects"]
    assert "14" in res["sections"][0]["text"] and "改错文件" in res["sections"][1]["text"]
    assert "未测" in res["sections"][2]["text"]


def test_weekly_snapshot_loader(tdb, appdb, orbit_home):
    tdb.session("s1", humans=["a", "不对"], tools=[("bash", "shell", "ls", "failed", "x")])
    snap = build("narrate.weekly", tdb, appdb, orbit_home)["content"]["snapshot"]
    assert snap["metrics"]["sessions"] == 1 and snap["window"]["start_ms"] == SCOPE["start_ms"]


# ---------------------------------------------------------------- narrate.persona

PROFILE = {"code": "DPM?", "type_name": "规划型", "axes": {"D": {"value": 0.62, "letter": "D"},
                                                          "V": {"value": 0.5, "letter": "?"}},
           "observations": [{"dimension": "planning", "label": "先写计划", "sessions": 12, "denominator": 30}],
           "rates": {"planning_rate": 0.4}, "problems": [{"problem_id": "pb_1", "key": "改错文件"}]}


def persona_output(**kw):
    out = {"headline": "规划型（暂定）：先想清再动手", "traits": [{"text": "先计划", "metric": "rates.planning_rate",
                                                         "value_ref": 0.4}],
           "tradeoffs": [{"axis": "D", "text": "计划充分，但开工稍慢。"}],
           "blind_spots": [{"problem_id": "pb_1", "text": "改错文件反复出现。"}], "caveats": []}
    return {**out, **kw}


def test_persona_ai_and_gates():
    pack = build("narrate.persona", params={"profile": PROFILE})
    assert pack["content"]["persona"]["key"] == "DPM?"
    _, out = run("narrate.persona", pack, persona_output())
    assert out["status"] == "ok" and out["result"]["label"] == "AI 撰写 · 数字来自指标"
    validate = TASKS["narrate.persona"]["validate"]
    assert validate(persona_output(), pack) == []
    errors = validate(persona_output(headline="规划型性格", traits=[
        {"text": "x", "metric": "rates.planning_rate", "value_ref": 0.9},
        {"text": "y", "metric": "rates.nope", "value_ref": 1}], blind_spots=[{"problem_id": "pb_9", "text": "z"}]),
        pack)
    joined = "\n".join(errors)
    for needle in ("暂定", "value_ref", "rates.nope", "pb_9", "性格"):
        assert needle in joined


def test_persona_fallback_template():
    pack = build("narrate.persona", params={"profile": PROFILE})
    _, out = run("narrate.persona", pack, {}, {})
    res = out["result"]
    assert out["status"] == "fallback" and res["headline"] == "规划型（暂定）" and res["label"] is None
    assert res["traits"] == [{"text": "先写计划", "metric": "observations.0.sessions", "value_ref": 12.0}]
    assert TASKS["narrate.persona"]["validate"]({k: res[k] for k in persona_output()}, pack) == []


def test_metric_paths():
    assert metric_paths({"a": {"b": 1, "c": [2, {"d": 0.5}]}, "e": True}) == {"a.b": 1.0, "a.c.0": 2.0,
                                                                             "a.c.1.d": 0.5}


@pytest.mark.parametrize("task_id", sorted(TASKS))
def test_task_specs_complete(task_id):
    task = TASKS[task_id]
    for field in ("system", "schema", "validate", "fallback", "finalize", "run"):
        assert task[field]
    assert task["schema"]["additionalProperties"] is False and task["prompt_version"].endswith("@1")
