"""Constructed regressions for scope, temporal evidence and expert output gates."""

from copy import deepcopy

import pytest
from ai_analysis_fakectx import DAY, NOW

from orbit_backend.ai import ask, pack, queries, registry
from orbit_backend.ai.runner import schema_errors
from orbit_backend.ai.tasks_analysis import check_facet
from orbit_backend.ai.tasks_expert import TASKS, analysis_validate, expert_validate


@pytest.fixture
def scoped(tdb):
    tdb.session("included", project="p1", humans=["不对，执行检查", "继续检查"], replies=["完成"])
    tdb.session("foreign", project="p2", humans=["不对，执行检查", "继续检查"], replies=["完成"])
    tdb.commit()
    return tdb


def test_explicit_ids_cannot_bypass_project_scope(scoped, appdb, orbit_home):
    scope = {"start_ms": NOW - 30 * DAY, "end_ms": NOW, "project_id": "p1"}
    for api in ("sessions", "evidence"):
        result = queries.run(api, {"scope": scope, "session_uid": "foreign"},
                             reads=scoped.reads, appdb=appdb, home=orbit_home)
        assert result["rows"] == []
    built = pack.build(registry.get("facet.session"), reads=scoped.reads, appdb=appdb,
                       home=orbit_home, scope=scope, params={"session_uids": ["foreign", "included"]})
    assert set(built["content"]["items"]) == {"included"}
    feedback = pack.build(registry.get("classify.feedback"), reads=scoped.reads, appdb=appdb,
                          home=orbit_home, scope=scope, params={"event_uids": ["foreign-h0"]})
    assert feedback["content"]["feedback_items"]["items"] == []


def test_empty_sources_remain_empty_in_ask_and_pack(scoped, appdb, orbit_home):
    scoped.db.execute("ALTER TABLE session ADD COLUMN source_id TEXT")
    scoped.db.execute("UPDATE session SET source_id='source'")
    scoped.commit()
    scope = {"start_ms": NOW - 30 * DAY, "end_ms": NOW, "source_ids": []}
    q = ask._Q(scoped.reads, appdb, scope, orbit_home)
    assert q("sessions") == []
    assert q("search", q="检查") == []
    built = pack.build(registry.get("facet.session"), reads=scoped.reads, appdb=appdb,
                       home=orbit_home, scope=scope, params={"session_uids": ["included"]})
    assert built["content"]["items"] == {}


def test_latest_delivery_and_feedback_survive_long_sessions(tdb):
    tdb.session("long", humans=[f"request {i}" for i in range(220)],
                replies=[f"reply {i}" for i in range(220)])
    tdb.commit()
    with tdb.reads() as conn:
        result = pack.facet_payload(conn, "long")
    assert result["human_messages"][-1]["text"] == "request 219"
    assert result["assistant_replies"][-1]["text"] == "reply 219"
    assert result["chunked"] and result["coverage"]["human_messages"] == 220
    assert [m["seq"] for m in result["human_messages"]] == sorted(m["seq"] for m in result["human_messages"])


def test_facet_cannot_swap_signal_and_event_in_same_session():
    payload = {"human_messages": [{"event_uid": "a"}, {"event_uid": "b"}],
               "candidates": [{"signal_id": "sig:a", "event_uid": "a"}]}
    item = {"session_uid": "s", "goal": "检查", "task_type": "review", "outcome": "unclear",
            "friction_types": [], "candidates": [{"signal_id": "sig:a", "event_uid": "b",
            "is_correction": True, "feedback_kind": "correct", "friction_type": "none", "confidence": "low"}],
            "repeated_instructions": [], "summary": "检查", "chunked": False}
    cleaned, errors = check_facet(item, payload)
    assert not errors and cleaned["candidates"] == []


def test_expert_schema_and_bound_evidence():
    source = {"content": {"problems": [{"problem_id": "p", "weekly_count": 2}], "candidates": []}}
    result = {"suggestions": [{"kind": "workflow", "problem_id": "p", "title": "先检查环境",
                              "summary": "复现错误后缩小调用范围。", "steps": ["记录失败调用并核对参数。"],
                              "evidence_ids": ["p"], "limitations": ["尚未验证收益。"]}], "queries": []}
    spec = TASKS["recommend.expert"]
    assert not schema_errors(result, spec["schema"])
    assert not expert_validate(result, source)
    bad = deepcopy(result)
    bad["suggestions"][0]["evidence_ids"] = ["invented"]
    assert expert_validate(bad, source)
    bad = deepcopy(result)
    bad["suggestions"][0]["steps"] = [" "]
    assert expert_validate(bad, source)
    assert spec["fallback"](source, "timeout") == {"suggestions": [], "queries": []}


def test_professional_templates_enforce_metric_value_and_evidence():
    source = {"content": {"metrics": {"sessions": 2}}, "refs": {"metric": ["sessions"]}}
    output = {"summary": "会话已纳入分析。", "findings": [{"kind": "observation", "text": "观察到 2 个会话。",
              "evidence_ids": ["sessions"], "metrics": [{"path": "metrics.sessions", "value": 2}]}],
              "next_steps": [], "limitations": []}
    assert not analysis_validate(output, source)
    output["findings"][0]["metrics"][0]["value"] = 3
    assert analysis_validate(output, source)
    for lens in ("collaboration", "quality", "workflow", "cost"):
        spec = registry.get("analyze." + lens)
        fallback = spec["fallback"](source, "timeout")
        assert not schema_errors(fallback, spec["schema"])
        assert spec["finalize"](fallback, source, "fallback")["status"] == "fallback"


def test_professional_session_scope_applies_to_every_pack_item(scoped, appdb, orbit_home):
    built = pack.build(registry.get("analyze.collaboration"), reads=scoped.reads, appdb=appdb,
                       home=orbit_home, scope={"start_ms": NOW - 30 * DAY, "end_ms": NOW},
                       params={"session_uid": "included"}, goal="检查")
    assert built["content"]["metrics"]["sessions"] == 1
    assert [s["session_uid"] for s in built["content"]["sessions"]] == ["included"]
    assert all(e["session_uid"] == "included" for e in built["content"]["evidence"])
    assert built["scope"]["session_uids"] == ["included"]


def test_running_and_interrupted_calls_are_not_successes(tdb, orbit_home):
    tdb.session("status", humans=["检查"], tools=[("Bash", "shell", "ls", status, None)
                for status in ("success", "failed", "running", "interrupted", "rejected", "unknown")])
    tdb.commit()
    with tdb.reads() as conn:
        current, _ = pack.metrics_pair(conn, NOW - 30 * DAY, NOW, home=orbit_home)
    assert current["tool_known_results"] == 2
    assert current["tool_failure_rate"] == 0.5
    assert current["tool_unknown_share"] == pytest.approx(4 / 6, abs=0.001)


def test_ask_model_plan_cannot_widen_selected_scope(scoped, appdb, orbit_home):
    from ai_analysis_fakectx import FakeCtx

    from orbit_backend.ai.tasks_analysis import ASK_TASK, ask_run

    source = {"content": {"goal": {"text": "有多少会话"}},
              "scope": {"start_ms": NOW - 30 * DAY, "end_ms": NOW, "project_id": "p1"}}
    plan = {"intents": ["explain_metric"], "queries": [{"api": "sessions", "params": {"scope": {"project_id": "p2"}}}]}
    answer = {"answer": "本次仅查看选定会话。", "refs": [{"kind": "session", "id": "included"}], "next": "none"}
    ctx = FakeCtx(ASK_TASK, source, [plan, answer], reads=scoped.reads)
    ctx.home = orbit_home
    result = ask_run(ctx, source)
    assert result["status"] == "ok"
    assert result["result"]["queries"][0]["params"]["scope"]["project_id"] == "p1"
    assert '"foreign"' not in ctx.calls[-1]["prompt"]
