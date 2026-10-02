"""facet.session / narrate.overview / ask.question gates, retries and fallbacks (no real model)."""

from __future__ import annotations

import json

import pytest
from ai_analysis_fakectx import DAY, NOW, FakeCtx, run_task

from tandem_backend.ai import ask
from tandem_backend.ai import pack as P
from tandem_backend.ai.tasks_analysis import TASKS, CallFailed, numbers_ok

FACET, NARRATE, ASK = TASKS["facet.session"], TASKS["narrate.overview"], TASKS["ask.question"]
SCOPE = {"start_ms": NOW - 30 * DAY, "end_ms": NOW}


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)


def test_taskspecs_follow_contract():
    keys = {"task_id", "tier", "slot", "prompt_version", "schema_version", "input_budget", "out_budget",
            "max_budget_usd", "timeout_s", "engines", "pack_items", "requires_preview", "cache_ttl_s", "stages",
            "system", "schema", "build_prompt", "validate", "fallback", "finalize", "run"}
    for spec in TASKS.values():
        assert keys <= set(spec)
        assert set(spec["stages"]) <= {"pack", "analyse", "draft", "check", "replay", "review", "cross"}
    assert FACET["prompt_version"] == "facet@1.1" and FACET["pack_items"] == [("items", True)]
    assert dict(NARRATE["pack_items"]) == {"metrics": True, "friction": True, "candidates": True, "sessions": False}


def test_numbers_ok():
    nums = [0.125, 42.0, 3.5]
    assert numbers_ok("失败率 12.5%，共 42 次，3 个会话，平均 3.5 分钟", nums) == []
    assert numbers_ok("比例 0.125", [12.5]) == []
    assert numbers_ok("提升了 37%", nums) == ["37%"]
    assert numbers_ok("共 1,234 次", nums) == ["1,234"]
    assert numbers_ok("v2 版本与 A9 页面", []) == []


# ---------------------------------------------------------------- facet

def facet_pack(tdb, appdb, home, n=8):
    for i in range(n):
        tdb.session(f"s{i:02d}", humans=["做个功能", "不对，换种方式"], replies=["好"],
                    tools=[("Bash", "shell", "ls", "failed", "exit_nonzero")])
    tdb.commit()
    return P.build(FACET, reads=tdb.reads, appdb=appdb, home=home, scope=SCOPE)


def facet_for(uid, **over):
    return {"session_uid": uid, "goal": "做个功能", "task_type": "feature", "outcome": "mostly_achieved",
            "friction_types": ["wrong_approach"],
            "candidates": [{"signal_id": f"sig:{uid}-h1", "event_uid": f"{uid}-h1", "is_correction": True,
                            "feedback_kind": "correct", "friction_type": "wrong_approach", "confidence": "high"}],
            "repeated_instructions": [], "summary": "做功能，中途纠偏一次", "chunked": False, **over}


def test_facet_drops_foreign_events_and_saves(tdb, appdb, tandem_home):
    pack = facet_pack(tdb, appdb, tandem_home, 3)
    uids = list(pack["content"]["items"])
    out = {"items": [facet_for(u) for u in uids]}
    out["items"][0]["candidates"].append({"signal_id": "sig:other", "event_uid": "other-h9", "is_correction": True,
                                          "feedback_kind": "correct", "friction_type": "none",
                                          "confidence": "low"})
    ctx = FakeCtx(FACET, pack, [out])
    result = run_task(FACET, ctx)
    assert result["status"] == "ok" and len(result["facets"]) == 3
    first = next(f for f in result["facets"] if f["session_uid"] == uids[0])
    assert [c["event_uid"] for c in first["json"]["candidates"]] == [f"{uids[0]}-h1"]
    assert first["content_hash"] == P.content_hash(pack["content"]["items"][uids[0]])
    assert first["prompt_version"] == "facet@1.1" and ctx.progresses == [(1, 1)]
    assert '"ref_id":"' + uids[0] in ctx.calls[0]["prompt"]


def test_facet_missing_item_retried_then_failed(tdb, appdb, tandem_home):
    pack = facet_pack(tdb, appdb, tandem_home, 4)
    uids = list(pack["content"]["items"])
    first = {"items": [facet_for(u) for u in uids[:3]]}           # one missing
    retry = {"items": [facet_for(uids[3], friction_types=["context_loss"])]}  # ungrounded → still invalid
    ctx = FakeCtx(FACET, pack, [first, retry])
    result = run_task(FACET, ctx)
    statuses = {f["session_uid"]: f["status"] for f in result["facets"]}
    assert statuses[uids[3]] == "failed" and list(statuses.values()).count("ok") == 3
    assert result["status"] == "partial"
    assert len(ctx.calls) == 2 and uids[3] in ctx.calls[1]["prompt"] and uids[0] not in ctx.calls[1]["prompt"]


def test_facet_aborts_after_half_failed_batch(tdb, appdb, tandem_home):
    pack = facet_pack(tdb, appdb, tandem_home, 16)
    assert len(pack["batches"]) == 2
    ctx = FakeCtx(FACET, pack, [CallFailed("x")] * 8)
    result = run_task(FACET, ctx)
    assert result["status"] == "failed" and result["result"]["aborted"]
    assert len(result["facets"]) == 8 and all(f["status"] == "failed" for f in result["facets"])
    assert ctx.progresses == [(1, 2)]
    assert any("失败过半" in line for line in ctx.logs)


# ---------------------------------------------------------------- narrate

def narrate_pack(tdb, appdb, home):
    for i in range(5):
        tdb.session(f"s{i}", humans=["做", "不对"], tools=[("Bash", "shell", "pytest", "failed", "exit_nonzero"),
                                                         ("Read", "read")])
    tdb.commit()
    slots = {"candidates": [{"candidate_id": "cand-1", "title": "重复失败熔断", "kind": "hook", "priority": 5,
                             "reason": "pytest 连续失败", "evidence_counts": {"sessions": 5}}]}
    return P.build(NARRATE, reads=tdb.reads, appdb=appdb, home=home, scope=SCOPE, slots=slots)


def good_narrative():
    return {"summary": "本期 5 个会话，工具失败率 50%",
            "findings": [{"title": "做得好", "text": "5 个会话都完成了。", "scene": "good", "evidence_ids": ["sessions"]},
                         {"title": "卡在哪", "text": "pytest 失败 5 次。", "scene": "stuck",
                          "evidence_ids": ["tool_failures"]},
                         {"title": "立刻可做", "text": "装上重复失败熔断。", "scene": "next", "evidence_ids": ["cand-1"]}],
            "next_step": "先试重复失败熔断。", "caveats": [], "main_evidence_ids": ["cand-1"], "audience": "user"}


def test_narrate_ok(tdb, appdb, tandem_home):
    pack = narrate_pack(tdb, appdb, tandem_home)
    result = run_task(NARRATE, FakeCtx(NARRATE, pack, [good_narrative()]))
    assert result["status"] == "ok" and result["result"]["source"] == "ai"


@pytest.mark.parametrize("bad", [
    {"summary": "本期 37 个会话"},
    {"main_evidence_ids": ["made-up-id"]},
    {"summary": "装上就一定能提升效率"},
])
def test_narrate_fabrication_falls_back(tdb, appdb, tandem_home, bad):
    pack = narrate_pack(tdb, appdb, tandem_home)
    ctx = FakeCtx(NARRATE, pack, [{**good_narrative(), **bad}] * 2)
    result = run_task(NARRATE, ctx)
    assert len(ctx.calls) == 2 and ctx.calls[1]["errors"]
    assert result["status"] == "fallback" and result["result"]["source"] == "template"
    texts = [f["title"] for f in result["result"]["findings"]]
    assert texts == ["做得好", "卡在哪", "立刻可做"]
    assert NARRATE["validate"](result["result"], pack) == []  # template obeys its own gate


# ---------------------------------------------------------------- ask

@pytest.fixture
def ask_data(tdb):
    for i in range(3):
        tdb.session(f"s{i}", humans=["做", "不对"], tools=[("Bash", "shell", "pytest", "failed", "exit_nonzero")])
    tdb.commit()
    return tdb


def ask_pack(tdb, appdb, home, question):
    return P.build(ASK, reads=tdb.reads, appdb=appdb, home=home, scope=SCOPE, goal=question, goal_source="ask")


def test_ask_out_of_range_queries_dropped(ask_data, appdb, tandem_home):
    pack = ask_pack(ask_data, appdb, tandem_home, "哪个工具最差？")
    plan = {"intents": ["tool_worst"], "queries": [{"api": "tools", "params": {"limit": 99}},
                                                   {"api": "sessions", "params": {"sql": "x"}}]}
    ctx = FakeCtx(ASK, pack, [plan], reads=ask_data.reads, params={"context": "tools"})
    result = run_task(ASK, ctx)
    assert result["result"]["answer"] == ask.OUT_OF_SCOPE
    assert result["result"]["pages"][0]["page"] == "A4" and result["result"]["queries"] == []
    assert len(ctx.calls) == 1 and ctx.calls[0]["slot"] == "cheap"


def test_ask_other_intent(ask_data, appdb, tandem_home):
    pack = ask_pack(ask_data, appdb, tandem_home, "今天天气如何")
    ctx = FakeCtx(ASK, pack, [{"intents": ["other"], "queries": [{"api": "metrics", "params": {}}]}],
                  reads=ask_data.reads)
    assert run_task(ASK, ctx)["result"]["answer"] == ask.OUT_OF_SCOPE


def test_ask_answer_validated(ask_data, appdb, tandem_home, monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)
    pack = ask_pack(ask_data, appdb, tandem_home, "哪个工具最差？")
    plan = {"intents": ["tool_worst"], "queries": [{"api": "tools", "params": {"limit": 3}}]}
    fake = {"answer": "Bash 失败 99 次", "refs": [{"kind": "session", "id": "nope"}], "next": "tools"}
    ok = {"answer": "Bash 失败最多，共 3 次，错误率 100%。", "refs": [], "next": "tools"}
    ctx = FakeCtx(ASK, pack, [plan, fake, ok], reads=ask_data.reads)
    result = run_task(ASK, ctx)
    assert result["status"] == "ok" and result["result"]["source"] == "ai"
    assert result["result"]["answer"] == ok["answer"] and result["result"]["intents"] == ["tool_worst"]
    assert ctx.calls[1]["slot"] == "main" and ctx.calls[2]["errors"]
    rows = json.loads(ctx.calls[1]["prompt"])["results"][0]["rows"]
    assert rows[0]["tool"] == "Bash"


def test_ask_engine_failure_falls_back(ask_data, appdb, tandem_home):
    pack = ask_pack(ask_data, appdb, tandem_home, "哪个工具最差？")
    ctx = FakeCtx(ASK, pack, [CallFailed("down")], reads=ask_data.reads)
    result = run_task(ASK, ctx)
    assert result["status"] == "fallback" and result["result"]["source"] == "template"
