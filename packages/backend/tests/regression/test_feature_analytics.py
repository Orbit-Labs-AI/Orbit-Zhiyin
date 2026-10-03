import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbit_backend.analytics.features import correction_terms, ratio, tool_summary, usage, workflow
from orbit_backend.analytics.inputs import AnalysisInputBundle, Scope, legacy_bundle, select
from orbit_backend.analytics.service import analyze_bundle, analyze_store
from orbit_backend.analytics.text import representation, temporal_novelty
from orbit_backend.api import create_app
from orbit_backend.cli import main
from orbit_backend.models import Event, ParsedSession, Session
from orbit_backend.store import Store


def session(sid="s", kind="main", root="s"):
    return {"session_uid": sid, "kind": kind, "root_uid": root, "project_id": "p", "started_at": 0}


def event(uid="u", seq=0, kind="message.user", ts=100, sid="s", text="请修复测试，并解释修改原因。", **attrs):
    return {"event_uid": uid, "session_uid": sid, "seq": seq, "ts": ts, "kind": kind, "turn_uid": "t",
            "actor": "human" if kind == "message.user" else "assistant", "text": text,
            "attrs": {"origin": "human", **attrs}}


def call(uid="c", sid="s", **kw):
    return {"call_uid": uid, "session_uid": sid, "turn_uid": "t", "call_event_uid": uid,
            "result_event_uid": "r" + uid, "seq": 1, "name_raw": "shell", "kind": "shell",
            "status": "failed", "started_at": 100, "ended_at": None, **kw}


def bundle(events=None, calls=None, sessions=None, models=None):
    cov = {k: {"status": "available"} for k in ("events", "sessions", "tool_calls", "turns", "projects", "model_calls")}
    return AnalysisInputBundle(sessions or [session()], events if events is not None else [event()],
                               calls if calls is not None else [], models if models is not None else [], cov,
                               projects=[{"project_id": "p", "name": "fixture"}])


def request(uid="m", sid="s", **kw):
    return {"call_uid": uid, "session_uid": sid, "turn_uid": "t", "model_id": "model-a",
            "effort_raw": "high", "usage_scope": "call", "measurement": "delta", "boundary_reliable": True,
            "coverage": "self", "ts": 100, "input_tokens": 1200, "cache_read_tokens": 500,
            "cache_write_tokens": 0, "output_tokens": 300, "reasoning_tokens": 100, **kw}


def test_contract_section_eight_fixture():
    raw = json.loads((Path(__file__).parents[1] / "fixtures/analysis-input-v1.json").read_text())
    data = analyze_bundle(AnalysisInputBundle.from_dict(raw), Scope(**raw["scope"]), with_text=False)
    assert data["overview"]["counts"]["human_messages"] == 1
    tools = data["tools"]["totals"]
    assert tools["call_count"] == tools["paired_result_count"] == tools["known_failure_count"] == 1
    assert tools["median_duration_ms"] == 900
    assert tools["reliable_interval_union_ms"] is None
    assert data["sessions"][0]["tool_sequence"][0]["ended_at"] is None
    assert data["overview"]["usage"]["total_tokens"] is None
    assert data["overview"]["usage"]["request_count"] is None
    assert data["overview"]["usage"]["cost_usd"] is None
    assert data["sessions"][0]["subjective_outcome_candidates"] == []
    assert data["sessions"][0]["task_success"] is None
    assert data["workflow"]["transition_count"] == 2  # Unclocked linked result remains sequence context.


def test_unavailable_is_not_observed_zero():
    raw = {"input_contract": "analysis-input-v1", "sessions": [session()], "events": [event()],
           "tool_calls": [], "model_calls": [], "coverage": {"tool_calls": {"status": "unavailable"}, "model_calls": {"status": "unavailable"}}}
    b = AnalysisInputBundle.from_dict(raw)
    assert b.tool_calls is None and b.model_calls is None
    result = analyze_bundle(b, with_text=False)
    assert result["tools"]["by_tool"] is None and result["tools"]["totals"] is None
    assert result["sessions"][0]["features"]["tool_call_count"] is None
    assert ratio(0, 0) is None
    assert tool_summary([])["totals"]["call_count"] == 0
    assert tool_summary([], "partial")["totals"]["call_count"] is None


def test_unavailable_events_do_not_turn_into_empty_observations():
    b = bundle()
    b.events = None
    b.coverage["events"] = {"status": "unavailable"}
    r = analyze_bundle(b, with_text=False)
    assert r["overview"]["counts"]["events"] is None
    assert r["sessions"][0]["features"]["assistant_message_count"] is None
    assert r["overview"]["activity_rhythm"] is None


def test_seq_not_clock_and_unclocked_sequence():
    es = [event("h", 1, ts=900), event("a", 2, "message.assistant", ts=100), event("c", 3, "tool.call", ts=None)]
    w = workflow(list(reversed(es)), [], {"s"})
    assert w["sequences"]["s"] == [("HUMAN_MESSAGE", "h"), ("ASSISTANT_MESSAGE", "a"), ("TOOL_CALL", "c")]
    assert w["transition_count"] == 2


@pytest.mark.parametrize("origin", ["injected", "system", "peer", "automation", "queued", "notification", "unknown"])
def test_nonhuman_origins_never_increase_denominator(origin):
    result = analyze_bundle(bundle([event(origin=origin)]), with_text=False)
    assert result["effective_samples"]["human_messages"] == 0
    assert result["overview"]["counts"]["human_messages"] in (0, None)
    assert result["sessions"][0]["correction_signals"] == []


def test_children_contribute_tools_not_human_and_are_not_sequenced_across_sessions():
    es = [event(), event("childprompt", 0, sid="child")]
    b = bundle(es, [call(sid="child")], [session(), session("child", "subagent")])
    r = analyze_bundle(b, with_text=False)
    assert r["overview"]["counts"]["human_messages"] == 1
    assert len(r["sessions"]) == 1
    assert r["sessions"][0]["features"]["tool_call_count"] == 1
    assert r["workflow"]["transition_count"] == 0
    no_children = analyze_bundle(b, Scope(include_children=False), with_text=False)
    assert no_children["tools"]["totals"]["call_count"] == 0
    excluded = analyze_bundle(b, Scope(excluded_session_uids=["s"]), with_text=False)
    assert excluded["overview"]["counts"]["sessions"] == 0


def test_explicit_replay_not_counted_twice_but_same_text_new_request_is_kept():
    es = [event("one", 0), event("copy", 1, replayed_from="one"), event("new", 2)]
    r = analyze_bundle(bundle(es), with_text=False)
    assert r["effective_samples"]["human_messages"] == 2
    assert r["selection"]["replayed_events_excluded"] == 1


def test_tool_pair_status_rates_and_no_invented_end():
    calls = [call(status="success", duration_ms=900, duration_source="reported", duration_quality="reported"),
             call("missing", result_event_uid=None, status=None), call("unknown", status=None),
             call("rejected", status="rejected"), call("failed"), call("interrupted", status="interrupted")]
    t = tool_summary(calls)["totals"]
    assert t["call_count"] == 6 and t["paired_result_count"] == 5 and t["unpaired_count"] == 1
    assert t["known_success_count"] == 1 and t["unknown_status_count"] == 2
    assert t["success_rate"] == .5 and t["failure_rate"] == .5
    assert t["duration_source"] == {"reported": 1} and t["duration_quality"] == {"reported": 1}
    assert calls[0]["ended_at"] is None and t["reliable_interval_union_ms"] is None


def test_wrapper_status_and_interval_union():
    t = tool_summary([call(status="success", unknown_return_values=1),
                      call("f", status="success", failed_command_results=1)])["totals"]
    assert t["known_success_count"] == 0 and t["unknown_status_count"] == t["known_failure_count"] == 1
    t = tool_summary([call(started_at=0, ended_at=5, duration_ms=5, duration_source="native_bounds"),
                      call("overlap", started_at=3, ended_at=8, duration_ms=5, duration_source="native_bounds")])["totals"]
    assert t["duration_sum_ms"] == 10 and t["reliable_interval_union_ms"] == 8


def test_retry_requires_digest_identity_and_status_scope():
    cs = [call("a", seq=1), call("b", seq=2)]
    w = workflow([], cs, set())
    assert w["consecutive_failed_calls"] == 1 and w["confirmed_same_argument_failed_retries"] is None
    for c in cs:
        c.update(argument_digest="literal", status_scope="command_return")
    assert workflow([], cs, set())["confirmed_same_argument_failed_retries"] == 1
    cs[1]["status_scope"] = "wrapper"
    assert workflow([], cs, set())["confirmed_same_argument_failed_retries"] is None


def test_canonical_tool_sequence_and_supplements_come_from_l2_not_uid_or_clock():
    es = [event("z", 0, "tool.call", ts=900, argument_digest="same"),
          event("rz", 1, "tool.result", ts=901, status_scope="command_return"),
          event("a", 2, "tool.call", ts=100, argument_digest="same"),
          event("ra", 3, "tool.result", ts=101, status_scope="command_return")]
    cs = [call("a"), call("z")]
    for c in cs:
        del c["seq"]
    r = analyze_bundle(bundle(es, cs), with_text=False)
    assert r["workflow"]["confirmed_same_argument_failed_retries"] == 1
    selected = sorted(r["sessions"][0]["tool_sequence"], key=lambda c: c["seq"])
    assert [c["call_uid"] for c in selected] == ["z", "a"]


def test_half_open_time_filter_and_calendar_unknowns():
    b = bundle([event("a", 0, ts=100), event("b", 1, ts=200), event("c", 2, ts=300), event("d", 3, ts=None)])
    r = analyze_bundle(b, Scope(from_ts=100, until_ts=300, display_timezone="Asia/Shanghai"), with_text=False)
    assert r["effective_samples"]["human_messages"] == 2
    assert r["selection"]["time_unknown_excluded_from_bounded_counts"] == 1
    assert r["overview"]["activity_rhythm"]["human_messages"]["by_hour"] == {"8": 2}
    r = analyze_bundle(b, with_text=False)
    assert r["overview"]["activity_rhythm"]["human_messages"]["time_unknown_n"] == 1


def test_future_tool_result_does_not_leak_into_snapshot():
    b = bundle([event("c", 0, "tool.call", ts=100), event("rc", 1, "tool.result", ts=400)],
               [call(started_at=100, ended_at=400, duration_ms=300)])
    r = analyze_bundle(b, Scope(until_ts=300), with_text=False)
    assert r["tools"]["totals"]["paired_result_count"] == 0
    assert r["tools"]["totals"]["known_failure_count"] == 0
    b.tool_calls[0]["failed_command_results"] = 1
    r = analyze_bundle(b, Scope(until_ts=300), with_text=False)
    assert r["tools"]["totals"]["known_failure_count"] == 0


def test_tokens_cache_buckets_reasoning_and_invalid_requests():
    u = usage([request()], [], [session()], Scope())
    assert u["total_tokens"] == 2000 and u["request_count"] == 1
    assert u["cost_usd"] is None and u["median_latency_ms"] is None
    missing = request(cache_write_tokens=None)
    assert usage([missing], [], [session()], Scope())["total_tokens"] is None
    for mutation in ({"usage_scope": "session_snapshot"}, {"measurement": "cumulative"}, {"boundary_reliable": False}):
        u = usage([request(**mutation)], [], [session()], Scope())
        assert u["total_tokens"] is None and u["request_count"] is None
    partial = usage([request()], [], [session()], Scope(), records_complete=False)
    # Incomplete records no longer erase the total: the known row is a lower bound.
    assert (partial["total_tokens"], partial["total_basis"], partial["total_complete"]) == (
        2000, "call_delta_known_rows", False)
    assert partial["total_unknown"]["records_incomplete"] is True
    assert usage([request(cost_usd=1, cost_source="estimate")], [], [session()], Scope())["cost_usd"] is None


def test_cumulative_latest_not_summed_and_tree_does_not_add_children():
    def snapshot(uid, seq, total):
        return event(uid, seq, "model.usage", snapshot_key="cycle", usage_scope="session_snapshot", measurement="cumulative",
                     coverage="root_tree", input_tokens=total, cache_read_tokens=0, cache_write_tokens=0, output_tokens=0)
    es = [snapshot("a", 0, 5000), snapshot("b", 1, 8000)]
    u = usage(None, es, [session()], Scope())
    assert u["total_tokens"] == 8000 and u["request_count"] is None
    u = usage([request(sid="child")], es, [session(), session("child", "subagent")], Scope())
    assert u["total_tokens"] == 8000 and u["total_basis"] == "cumulative_snapshot"
    assert usage(None, es, [session()], Scope(from_ts=0))["total_tokens"] is None
    es.append(snapshot("regressed", 2, 100))
    u = usage(None, es, [session()], Scope())
    assert u["total_tokens"] is None and u["cumulative_regressed_keys"] == ["cycle"]


def test_mixed_model_turn_does_not_attribute_all_tools_to_either_model():
    b = bundle(calls=[call()], models=[request(), request("other", model_id="model-b")])
    r = analyze_bundle(b, Scope(model_ids=["model-a"]), with_text=False)
    assert r["overview"]["usage"]["request_count"] == 1
    assert r["tools"]["totals"]["call_count"] == 0
    assert r["selection"]["model_ambiguous_turns_excluded"] == 1


def test_legacy_import_does_not_upgrade_user_role_or_override_explicit_nonhuman(tmp_path):
    from orbit_backend.importers.codex import parse_rollout
    path = tmp_path / "native.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "s", "source": "vscode", "thread_source": "user"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "请修复测试"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "origin": "peer", "content": "请修改报告"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "请修改报告"}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    p = parse_rollout(path)
    assert p.session.analytics_metadata["kind"] == "main"
    assert p.events[0].details["origin"] == "unknown"
    assert p.events[1].details["origin"] == "peer"


def test_scope_does_not_mutate_bundle_and_digest_changes_with_source_and_scope():
    b = bundle()
    original = copy.deepcopy(b)
    a = analyze_bundle(b, with_text=False)
    limited = analyze_bundle(b, Scope(project_ids=[]), with_text=False)
    assert b == original
    assert a["analysis_digest"] != limited["analysis_digest"]


def test_text_json_is_serializable_with_real_clustering():
    es = [{"entity_id": str(i), "text": "测试程序", "ts": i} for i in range(4)]
    json.dumps(representation(es), allow_nan=False)


@pytest.mark.parametrize("text", ["不对，请重新来", "这个方向错了，先回滚再说", "wrong, try again", "你理解错了。", "改成两段"])
def test_correction_positive(text):
    assert correction_terms(text)


@pytest.mark.parametrize("text", ["这个函数不对称", "不是看不懂，请继续", "还是不行", "不要输出错误答案", "请解释 wrong 的含义", "如果不对就重试", "> 不对\n请继续", '示例里写着“还是不行”'])
def test_correction_negation_and_quotes(text):
    assert not correction_terms(text)


def test_subjective_outcome_needs_delivery_same_task_and_feedback():
    b = bundle([event("a", 0, "message.assistant", text="完成", phase="final", task_id="task", task_id_source="native")])
    assert analyze_bundle(b, with_text=False)["sessions"][0]["subjective_outcome_candidates"] == []
    b.events.append(event("u", 1, text="可以了", task_id="task", task_id_source="native"))
    assert analyze_bundle(b, with_text=False)["sessions"][0]["subjective_outcome_candidates"][0]["signal"] == "positive"


def test_scope_projects_models_exclusions_and_explicit_empty():
    b = bundle(models=[request()])
    assert len(select(b, Scope(project_ids=["p"], model_ids=["model-a"], effort_raw=["high"]))[1]) == 1
    assert not select(b, Scope(project_ids=[]))[0]
    assert not select(b, Scope(model_ids=[]))[1]
    assert not select(b, Scope(excluded_session_uids=["s"]))[0]
    b.model_calls = None
    with pytest.raises(ValueError, match="model_call"):
        select(b, Scope(model_ids=["model-a"]))


@pytest.mark.parametrize("options", [{"display_timezone": "Invalid/Zone"}, {"from_ts": 2, "until_ts": 1}, {"from_ts": True}, {"scene": "madeup"}])
def test_invalid_scope(options):
    with pytest.raises(ValueError):
        Scope(**options)


def test_representation_insufficient_identical_separated_noise_and_deterministic():
    es = [{"entity_id": str(i), "text": "数学证明偏微分方程", "ts": i} for i in range(4)]
    assert representation(es[:2])["clustering"]["status"] == "insufficient_samples"
    same = representation(copy.deepcopy(es))
    assert same["clustering"]["cluster_count"] == 1
    assert all(p["embedding_x"] == p["embedding_y"] == 0 for p in same["coordinates"])
    es += [{"entity_id": str(i), "text": "typescript frontend component styles", "ts": i} for i in range(4, 7)]
    es.append({"entity_id": "outlier", "text": "zebra submarine chemistry", "ts": 10})
    r = representation(copy.deepcopy(es))
    assert r["clustering"]["cluster_count"] == 2 and r["clustering"]["noise_count"] == 1
    assert r == representation(copy.deepcopy(es))


def test_novelty_no_future_in_fit_or_neighbors_equal_time_or_missing_time():
    es = [{"entity_id": "a", "text": "数学证明偏微分方程", "ts": 1},
          {"entity_id": "b", "text": "数学证明边界条件", "ts": 2}]
    before = temporal_novelty(es)
    after = temporal_novelty(es + [{"entity_id": "future", "text": "数学证明边界条件", "ts": 3}])
    assert before["b"] == after["b"] and before["a"]["novelty"] is None
    assert temporal_novelty([{**es[0], "ts": None}])["a"]["novelty"] is None
    assert temporal_novelty([es[0], {**es[1], "ts": 1}])["b"]["novelty"] is None


def legacy_store(tmp_path, origin=None):
    store = Store(tmp_path / "history.sqlite")
    s = Session("s", "legacy", "sample", "/fixture", "fixture", analytics_metadata={"kind": "main", "root_uid": "s"})
    es = [Event("u", "s", 0, "user_message", "2026-01-01T00:00:00+00:00", text="请修复测试", details={"origin": origin} if origin else {})]
    store.save(ParsedSession(s, es), "fixture", json.dumps({"parser": 26, "before": None, "exclude": []}))
    return store


def test_legacy_fields_are_not_upgraded_to_contract_fields(tmp_path):
    store = legacy_store(tmp_path)
    b = legacy_bundle(store)
    assert b.sessions[0]["project_id"] is None and b.model_calls is None
    r = analyze_store(store, with_text=False)
    assert r["overview"]["counts"]["human_messages"] is None
    assert r["overview"]["usage"]["request_count"] is None
    with pytest.raises(ValueError, match="规范"):
        analyze_store(store, Scope(project_ids=["legacy"]), with_text=False)


def test_api_all_surfaces_validation_scope_and_cli_json(tmp_path, capsys):
    store = legacy_store(tmp_path, "human")
    with TestClient(create_app(store.path)) as client:
        for path in ("overview", "sessions", "sessions/s", "tools", "projects", "text"):
            r = client.get("/v1/analytics/" + path, params={"display_timezone": "Asia/Shanghai"})
            assert r.status_code == 200, r.text
            assert r.json()["scope"]["display_timezone"] == "Asia/Shanghai"
            assert "coverage" in r.json() and "effective_samples" in r.json()
        assert client.get("/v1/analytics/overview?model_ids=fake").status_code == 422
        assert client.get("/v1/analytics/overview?display_timezone=bogus").status_code == 422
        assert client.get("/v1/analytics/sessions/s?excluded_session_uids=s").status_code == 404
        assert client.get("/v1/analytics/sessions?project_ids=").json()["total"] == 0
    output = tmp_path / "analytics.json"
    main(["--db", str(store.path), "analytics", "--output", str(output), "--display-timezone", "Asia/Shanghai"])
    r = json.loads(output.read_text())
    assert r["overview"]["counts"]["human_messages"] == 1
    assert "主会话" in capsys.readouterr().out


def test_partial_tool_coverage_session_without_calls_counts_zero():
    """a1a3-B9: a session with no tool calls under partial pairing coverage has 0, not null."""
    raw = {"input_contract": "analysis-input-v1", "sessions": [session()], "events": [event()],
           "tool_calls": [], "model_calls": [], "coverage": {"tool_calls": {"status": "partial"}}}
    result = analyze_bundle(AnalysisInputBundle.from_dict(raw), with_text=False)
    row = result["sessions"][0]
    assert row["features"]["tool_call_count"] == 0
    assert row["tools"]["totals"]["call_count"] == 0
