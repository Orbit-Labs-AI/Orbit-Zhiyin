"""Hot-path rewrites keep results identical; only constructed data is used."""

import copy
import json
import random
import subprocess
import sys

import numpy as np

from tandem_backend import privacy
from tandem_backend.analytics.common import quantile, timestamp
from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.cost_time.durations import summarize_durations
from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.respond.calls import normalize_tool_calls, pair_tool_calls
from tandem_backend.analytics.respond.features import tool_summary
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.analytics.task import representation as rep

PROMPTS = ["请修复测试失败的问题", "不对，我说的是只改 parser 模块", "好的，可以了，谢谢",
           "还是不行，重新跑一下测试", "Please add type hints and run the build"]
TOOLS = [("exec_command", "shell", "pnpm test"), ("apply_patch", "file.edit", None),
         ("read_file", "file.read", None)]


def synthetic(n_sessions=24, seed=3):
    """Fictional sessions with prompts, paired calls, model usage and a subagent."""
    rnd = random.Random(seed)
    sessions, events, calls, models = [], [], [], []
    for s in range(n_sessions):
        sid, t0 = f"s{s}", 1_790_000_000_000 + s * 3_600_000
        sessions.append({"session_uid": sid, "root_uid": sid, "kind": "main", "project_id": f"p{s % 3}",
                         "source_id": f"src{s % 2}", "started_at": t0, "timezone": "Asia/Shanghai"})
        if s % 5 == 0:
            sessions.append({"session_uid": f"{sid}-c", "root_uid": sid, "parent_uid": sid, "kind": "subagent",
                             "project_id": f"p{s % 3}", "started_at": t0 + 10})
            events.append({"event_uid": f"{sid}-c-e", "session_uid": f"{sid}-c", "turn_uid": f"{sid}-c-t", "seq": 0,
                           "ts": t0 + 20, "kind": "message.assistant", "actor": "assistant", "text": "子代理输出",
                           "attrs": {"origin": "agent"}})
        seq, ts = 0, t0
        for p in range(3):
            turn = f"{sid}-t{p}"
            events.append({"event_uid": f"{turn}-u", "session_uid": sid, "turn_uid": turn, "seq": seq, "ts": ts,
                           "kind": "message.user", "actor": "human", "text": rnd.choice(PROMPTS),
                           "attrs": {"origin": "human"}})
            seq, ts = seq + 1, ts + 1000
            models.append({"call_uid": f"{turn}-m", "session_uid": sid, "turn_uid": turn, "ts": ts,
                           "usage_scope": "call", "measurement": "delta", "boundary_reliable": True,
                           "coverage": "self", "input_tokens": rnd.randint(100, 900), "output_tokens": 50,
                           "cache_read_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0,
                           "model_id": "m-a", "provider": "synthetic", "model_raw": "m-a", "effort_raw": "low"})
            for c in range(3):
                name, kind, head = rnd.choice(TOOLS)
                cuid, dur = f"{turn}-c{c}", rnd.randint(10, 5000)
                status = "failed" if rnd.random() < .2 else "success"
                for suffix, kind_name, at in (("call", "tool.call", ts), ("res", "tool.result", ts + dur)):
                    events.append({"event_uid": f"{cuid}-{suffix}", "session_uid": sid, "turn_uid": turn,
                                   "seq": seq, "ts": at, "kind": kind_name, "call_id": cuid, "text": None,
                                   "actor": "assistant" if suffix == "call" else "tool",
                                   "attrs": {"origin": "agent" if suffix == "call" else "tool"}})
                    seq += 1
                calls.append({"call_uid": cuid, "session_uid": sid, "turn_uid": turn, "seq": seq - 2,
                              "call_event_uid": f"{cuid}-call", "result_event_uid": f"{cuid}-res",
                              "name_raw": name, "kind": kind, "command_head": head, "status": status,
                              "status_scope": "command", "exit_code": int(status == "failed"),
                              "started_at": ts, "ended_at": ts + dur, "duration_ms": dur,
                              "duration_source": "native_bounds", "interval_reliable": True,
                              "argument_digest": f"d{rnd.randrange(5)}", "argument_digest_kind": "literal",
                              "files": [f"/synthetic/f{rnd.randrange(4)}.py"] if kind == "file.edit" else None,
                              "validation_report": {"checks": [{"name": "unit", "ok": status == "success"}]}})
                ts += dur + 100
            events.append({"event_uid": f"{turn}-a", "session_uid": sid, "turn_uid": turn, "seq": seq, "ts": ts,
                           "kind": "message.assistant", "actor": "assistant", "text": "已完成修改。",
                           "attrs": {"origin": "agent"}})
            seq, ts = seq + 1, ts + 60_000
    cov = {k: {"status": "available"} for k in
           ("sessions", "events", "tool_calls", "model_calls", "projects", "turns", "lineage")}
    projects = [{"project_id": f"p{i}", "name": f"项目{i}"} for i in range(3)]
    return AnalysisInputBundle(sessions, events, calls, models, cov, projects=projects,
                               versions={"content_digest": "synthetic-hotspots"})


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def test_analysis_is_deterministic_and_never_mutates_its_input():
    bundle = synthetic()
    snapshot = copy.deepcopy((bundle.sessions, bundle.events, bundle.tool_calls, bundle.model_calls))
    first = dumps(analyze_bundle(bundle, Scope(), False, with_recommendations=False))
    # Shallow row copies must not let analysis write through into nested input fields.
    assert (bundle.sessions, bundle.events, bundle.tool_calls, bundle.model_calls) == snapshot
    assert dumps(analyze_bundle(bundle, Scope(), False, with_recommendations=False)) == first
    assert dumps(analyze_bundle(synthetic(), Scope(), False, with_recommendations=False)) == first


def test_main_ids_is_computed_once_and_immutable():
    context = AnalysisContext.select(synthetic(6), Scope())
    ids = context.main_ids
    assert isinstance(ids, frozenset) and context.main_ids is ids
    assert ids == {s["session_uid"] for s in context.sessions if s.get("kind") == "main"}


def test_normalized_calls_equal_a_deep_copy_and_stay_detached():
    calls = synthetic(4).tool_calls
    calls = calls + [dict(calls[0], status="failed")]  # a conflicting mirror row
    original = copy.deepcopy(calls)
    result = normalize_tool_calls(calls)
    assert result == normalize_tool_calls(copy.deepcopy(original))
    assert result["call_conflicts"]
    for row in result["calls"]:
        if row["validation_report"]:  # conflicting rows have their result fields cleared
            row["validation_report"]["extra"] = True
        if row["files"]:
            row["files"].append("/synthetic/added.py")
    assert calls == original


def test_paired_rows_do_not_share_mutable_attrs_with_events():
    events = [{"event_uid": "c", "session_uid": "s", "seq": 0, "ts": 1, "kind": "tool.call", "call_id": "x",
               "attrs": {"name": "bash", "validation": ["unit"]}},
              {"event_uid": "r", "session_uid": "s", "seq": 1, "ts": 2, "kind": "tool.result", "call_id": "x",
               "attrs": {"status": "success", "known_command_results": [{"exit": 0}]}}]
    original = copy.deepcopy(events)
    row = pair_tool_calls(events)["calls"][0]
    assert row["validation"] == ["unit"] and row["known_command_results"] == [{"exit": 0}]
    row["validation"].append("lint")
    row["known_command_results"].append({"exit": 1})
    assert events == original


def test_tool_summary_quantiles_match_unsorted_reference():
    calls = synthetic(6).tool_calls
    rnd = random.Random(1)
    rnd.shuffle(calls)
    totals = tool_summary(calls)["totals"]
    durations = [c["duration_ms"] for c in calls]
    for key, q in (("median_duration_ms", .5), ("p25_duration_ms", .25),
                   ("p75_duration_ms", .75), ("p90_duration_ms", .9)):
        assert totals[key] == quantile(durations, q)
    assert totals["duration_sum_ms"] == sum(durations)


def test_session_spans_match_per_session_scan():
    bundle = synthetic(8)
    events = list(bundle.events)
    random.Random(2).shuffle(events)
    events.append({"event_uid": "untimed", "session_uid": "s1", "ts": None, "kind": "message.user"})
    spans = summarize_durations(bundle.tool_calls, events)["session_spans"]
    assert [s["session_uid"] for s in spans] == sorted({e["session_uid"] for e in events})
    for span in spans:
        es = [e for e in events if e["session_uid"] == span["session_uid"]]
        timed = [e for e in es if timestamp(e.get("ts"))]
        assert span["evidence_event_uids"] == sorted(e["event_uid"] for e in timed)
        assert span["unknown_n"] == len(es) - len(timed)
        assert span["first_observed_ts"] == min(e["ts"] for e in timed)
    assert summarize_durations(bundle.tool_calls, list(reversed(events)))["session_spans"] == spans


def test_direct_user_text_is_memoized_pure_function():
    privacy.direct_user_text.cache_clear()
    text = "请修复\n\n```\n不对，引用内容\n```\napi_key = 'abcdefghijklmnop'"
    first = privacy.direct_user_text(text)
    assert privacy.direct_user_text(text) == first and "abcdefghijklmnop" not in first
    info = privacy.direct_user_text.cache_info()
    assert info.hits == 1 and info.maxsize == 65536


def brute_novelty(entities):
    """Reference: compare each clocked entity with every strictly earlier one."""
    vectors = rep.novelty_vectors([e["text"] for e in entities])
    out = {}
    for i, e in enumerate(entities):
        if e.get("ts") is None:
            out[e["entity_id"]] = None
            continue
        earlier = [j for j, p in enumerate(entities) if p.get("ts") is not None and p["ts"] < e["ts"]]
        sims = (vectors[earlier] @ vectors[i].T).toarray().ravel() if earlier else []
        out[e["entity_id"]] = (1 - float(np.clip(max(sims), 0, 1)), len(earlier)) if earlier else None
    return out


def test_novelty_matches_brute_force_across_block_boundaries(monkeypatch):
    monkeypatch.setattr(rep, "NOVELTY_BLOCK", 7)
    rnd = random.Random(5)
    entities = [{"entity_id": f"e{i}", "text": rnd.choice(PROMPTS) + str(rnd.randrange(9)),
                 "ts": rnd.choice([None, *range(12)])} for i in range(40)]
    result = rep.temporal_novelty(entities)
    for entity_id, expected in brute_novelty(entities).items():
        got = result[entity_id]
        if expected is None:
            assert got["novelty"] is None and got["reason"] in ("missing_timestamp", "no_earlier_entity")
        else:
            assert got["novelty"] == expected[0] and got["earlier_n"] == expected[1]


def test_novelty_uses_only_strictly_earlier_text():
    base = [{"entity_id": "a", "text": "数学证明偏微分方程", "ts": 1},
            {"entity_id": "b", "text": "数学证明边界条件", "ts": 2},
            {"entity_id": "peer", "text": "完全不同的周报写作", "ts": 2},
            {"entity_id": "unclocked", "text": "数学证明边界条件", "ts": None}]
    before = rep.temporal_novelty(base)
    later = [{"entity_id": f"later{i}", "text": "数学证明边界条件", "ts": 3 + i} for i in range(5)]
    after = rep.temporal_novelty(later + base)
    for key in ("a", "b", "peer", "unclocked"):
        assert before[key] == after[key]
    assert before["unclocked"] == {"novelty": None, "earlier_n": 0, "reason": "missing_timestamp"}
    assert before["a"]["novelty"] is None and before["b"]["earlier_n"] == 1  # equal-time peer excluded
    assert after["later0"]["novelty"] == 0.0  # identical text appeared earlier
    assert rep.VECTOR_VERSION != "char-tfidf-svd-v1"


def test_importing_the_analysis_service_does_not_load_sklearn():
    code = ("import sys, tandem_backend.analytics.service\n"
            "assert not [m for m in sys.modules if m.split('.')[0] in ('sklearn', 'scipy')]")
    subprocess.run([sys.executable, "-c", code], check=True)
