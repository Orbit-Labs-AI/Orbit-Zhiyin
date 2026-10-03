"""AN-10 stats objects, AN-01 metrics with group_by / buckets, AN-01.2 drilldown, AN-11 facts."""

import pytest
from signal_fixtures import DAY, Session, analyze, bundle, retry_session

from tandem_backend.analytics.drilldown import tool_calls
from tandem_backend.analytics.metrics import GROUP_BY, metrics
from tandem_backend.analytics.signals import analyze_signals
from tandem_backend.analytics.signals.inventory import installed_unused
from tandem_backend.analytics.stats import INSUFFICIENT_N, count, median, proportion, wilson

# ---------------------------------------------------------------- stats


def test_wilson_and_metric_objects():
    lo, hi = wilson(3, 10)
    assert 0.10 < lo < 0.11 and 0.60 < hi < 0.61
    assert wilson(0, 0) == (None, None)
    with pytest.raises(ValueError):
        wilson(3, 2)
    small = proportion(1, INSUFFICIENT_N - 1)
    assert small["status"] == "insufficient" and small["value"] is None and small["n"] == 4
    ok = proportion(2, 8, basis="proxy")
    assert set(ok) >= {"value", "n", "lo", "hi", "basis"}
    assert ok["value"] == 0.25 and ok["basis"] == "proxy" and ok["show_n"] is True
    assert proportion(None, None)["status"] == "unknown"
    assert count(None)["value"] is None and count(None)["status"] == "unknown"
    assert median([1, 3, 2, 5, 4])["value"] == 3
    assert median([1, 2])["status"] == "insufficient"
    with pytest.raises(ValueError):
        proportion(1, 5, basis="guess")


# ---------------------------------------------------------------- metrics


def corpus():
    sessions = []
    for i in range(6):
        s = retry_session(f"r{i}", project="p1", source="src-a", ts=1_790_000_000_000 + i * DAY)
        sessions.append(s)
    for i in range(4):
        s = Session(f"c{i}", project="p2" if i < 3 else None, source="src-b",
                    ts=1_790_000_000_000 + i * DAY)
        s.user("请解释这个函数")
        s.reply()
        s.user("不对，我说的是另一个函数")
        s.reply()
        sessions.append(s)
    return sessions


def run_metrics(names, **kw):
    context, result, layer = analyze(bundle(corpus()))
    return metrics(context, result, names, layer=layer, **kw)


def test_proportions_return_metric_objects_with_insufficient_gate():
    out = run_metrics(["retry_loop_session_rate", "correction_rate"], group_by="project")["metrics"]
    overall = out["retry_loop_session_rate"]["overall"]
    assert overall["value"] == 1.0 and overall["n"] == 6 and overall["k"] == 6
    assert overall["lo"] is not None and overall["hi"] == 1.0 and overall["basis"] == "measured"
    groups = {g["key"]: g for g in out["correction_rate"]["groups"]}
    assert groups["p2"]["n"] == 6 and groups["p2"]["value"] == 0.5
    assert groups["unknown"]["n"] == 2 and groups["unknown"]["status"] == "insufficient"
    assert groups["unknown"]["value"] is None


@pytest.mark.parametrize("group_by", GROUP_BY)
def test_grouped_counts_add_up_to_overall(group_by):
    out = run_metrics(["sessions", "tool_calls", "human_messages"], group_by=group_by)["metrics"]
    for name in ("sessions", "tool_calls", "human_messages"):
        total = out[name]["overall"]["value"]
        assert sum(g["value"] or 0 for g in out[name]["groups"]) == total
    assert out["sessions"]["overall"]["value"] == 10


def test_project_groups_and_day_buckets():
    out = run_metrics(["sessions"], group_by="project", bucket="day")
    groups = {g["key"]: g["value"] for g in out["metrics"]["sessions"]["groups"]}
    assert groups == {"p1": 6, "p2": 3, "unknown": 1}
    series = out["metrics"]["sessions"]["series"]
    assert [s["bucket"] for s in series] == sorted(s["bucket"] for s in series)
    assert sum(s["value"] for s in series) == 10 and len(series) == 6


def test_metric_validation_errors():
    context, result, layer = analyze(bundle(corpus()))
    for kw in ({"metric": ["nope"]}, {"bucket": "month"}, {"group_by": "hour"}):
        with pytest.raises(ValueError):
            metrics(context, result, layer=layer, **kw)


def test_unknown_evidence_is_not_zero():
    context, result, layer = analyze(bundle(corpus(), tool_calls=False, events=False))
    out = metrics(context, result, ["tool_failure_rate", "tool_calls"], layer=layer)["metrics"]
    assert out["tool_failure_rate"]["overall"]["status"] == "unknown"
    assert out["tool_calls"]["overall"]["value"] is None
    assert out["tool_calls"]["overall"]["unknown_n"] == 10


# ---------------------------------------------------------------- drilldown


def secret_session():
    s = Session("a")
    s.user("部署")
    s.tool("curl", status="success", arguments={
        "command": "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz' https://user:pw@host/x"})
    s.tool("pytest", status="failed", arguments={"command": "pytest -k api_key=sk-ABCDEFGHIJKLMNOPQRSTUV"})
    for _ in range(60):
        s.tool("ls", status="success")
    return s


def test_drilldown_redacts_and_orders_recent_first():
    context, result, _ = analyze(bundle([secret_session()]))
    out = tool_calls(context, "Bash", limit=50, result=result)
    assert out["total"] == 62 and len(out["items"]) == 50
    assert out["items"][0]["started_at"] >= out["items"][-1]["started_at"]
    first = out["items"][0]
    assert {"session_uid", "event_uid", "exit_code", "duration_ms", "argument_summary"} <= set(first)
    curl = tool_calls(context, "Bash", command_head="curl", result=result)["items"][0]
    assert "abcdefghijklmnop" not in curl["argument_summary"]
    assert "user:pw" not in curl["argument_summary"] and "[认证已隐藏]" in curl["argument_summary"]
    pytest_call = tool_calls(context, "Bash", command_head="pytest", result=result)["items"][0]
    assert "sk-ABCDEFGH" not in pytest_call["argument_summary"]
    assert pytest_call["status"] == "failed" and pytest_call["exit_code"] == 1


def test_drilldown_limit_bounds_and_unknown_tool():
    context, result, _ = analyze(bundle([secret_session()]))
    for bad in (0, 51, True):
        with pytest.raises(ValueError):
            tool_calls(context, "Bash", limit=bad, result=result)
    assert tool_calls(context, "Nope", result=result)["total"] == 0


# ---------------------------------------------------------------- AN-11


def test_installed_unused_and_resident_tokens():
    s = Session("a")
    s.user("查文档")
    s.tool(None, kind="skill", name="Skill", status="success", skill="pdf")
    s.tool(None, kind="other", name="mcp__github__search", status="success", mcp_server="github")
    inventory = [{"inv_id": "1", "type": "skill", "name": "pdf"},
                 {"inv_id": "2", "type": "skill", "name": "docx"},
                 {"inv_id": "3", "type": "mcp", "name": "github"},
                 {"inv_id": "4", "type": "hook", "name": "pre-commit"},
                 {"inv_id": "5", "type": "skill", "name": "off", "enabled": 0}]
    # (uncached input, cache_read, cache_write): input side = sum of the three buckets.
    buckets = [("a", (40, 8000, 960)), ("a", (50, 0, 0)), ("b", (7000, 0, 0)), ("c", (8, 0, 7992)),
               ("d", (100, 5900, 0)), ("e", (10000, 0, 0))]
    model_calls = [{"call_uid": f"m{i}", "session_uid": sid, "ts": 1_790_000_000_000 + i,
                    "input_tokens": i_, "cache_read_tokens": r, "cache_write_tokens": w,
                    "output_tokens": 999}
                   for i, (sid, (i_, r, w)) in enumerate(buckets)]
    others = [Session(sid) for sid in "bcde"]
    for o in others:
        o.user("你好")
    context, result, _ = analyze(bundle([s, *others], inventory=inventory, model_calls=model_calls))
    facts = analyze_signals(context, result)["inventory"]
    unused = facts["installed_unused"]
    assert [i["name"] for i in unused["installed_unused"]] == ["docx"]
    assert {i["name"]: i["status"] for i in unused["items"]} == {
        "pdf": "used", "docx": "unused", "github": "used", "pre-commit": "not_matchable"}
    resident = facts["resident_tokens_median"]
    assert resident["value"] == 8000 and resident["n"] == 5 and resident["basis"] == "estimated"
    assert installed_unused(None, [])["installed_unused"] is None


def _resident(model_calls):
    sessions = [Session(sid) for sid in sorted({m["session_uid"] for m in model_calls})]
    for o in sessions:
        o.user("你好")
    context, result, _ = analyze(bundle(sessions, model_calls=model_calls))
    return analyze_signals(context, result)["inventory"]["resident_tokens_median"]


def test_resident_tokens_count_cache_buckets_for_claude_shape():
    # Claude Code: first request is ~all cache_creation; uncached input is single digits.
    calls = [{"call_uid": f"m{i}", "session_uid": f"s{i}", "ts": 1_790_000_000_000 + i,
              "input_tokens": 5, "cache_read_tokens": 0, "cache_write_tokens": 20000,
              "output_tokens": 300} for i in range(5)]
    resident = _resident(calls)
    assert resident["value"] == 20005 and resident["n"] == 5


def test_resident_tokens_honour_includes_cache_and_unknown_buckets():
    # includes_cache: reported input already contains cache read/write -> input side = input.
    calls = [{"call_uid": f"m{i}", "session_uid": f"s{i}", "ts": 1_790_000_000_000 + i,
              "input_tokens": 12000 + i, "cache_read_tokens": 10000, "cache_write_tokens": 1000,
              "output_tokens": 50, "input_tokens_semantics": "includes_cache"} for i in range(5)]
    # an unknown cache bucket makes that session unknown instead of undercounting it
    calls.append({"call_uid": "mx", "session_uid": "sx", "ts": 1_790_000_000_000,
                  "input_tokens": 5, "cache_read_tokens": None, "cache_write_tokens": 20000})
    resident = _resident(calls)
    assert resident["value"] == 12002 and resident["n"] == 5


def _status_session(sid, failed, success, unknown):
    s = Session(sid)
    s.user("跑一下")
    for i, status in enumerate(["failed"] * failed + ["success"] * success + [None] * unknown):
        s.tool(f"cmd{i}", status=status, digest=f"d{i}")
    return s


@pytest.mark.parametrize("failed,success,unknown,expected", [
    (3, 5, 2, 3 / 8),   # coverage 8/10 = 80% >= 50%: 3 failed of 8 known
    (2, 1, 7, None),    # coverage 3/10 = 30% < 50%: the known subset is not representative
])
def test_tool_failure_rate_uses_status_coverage_gate(failed, success, unknown, expected):
    from tandem_backend.analytics.respond.features import tool_summary

    context, result, layer = analyze(bundle([_status_session("a", failed, success, unknown)]))
    overall = metrics(context, result, ["tool_failure_rate"], layer=layer)["metrics"]["tool_failure_rate"]["overall"]
    summary = tool_summary(layer.views[0].calls)["totals"]
    assert summary["failure_rate"] == expected
    if expected is None:
        assert overall["value"] is None and overall["unknown_n"] == 1
    else:
        assert overall["value"] == pytest.approx(expected) and overall["n"] == failed + success
        assert overall["unknown_n"] == 0
