"""AN-06 problem upgrade: min_sessions, Wilson gate, opportunity denominators, stable ids, labels."""

import copy

from signal_fixtures import Session, analyze, bundle, retry_session

from tandem_backend.analytics.signals.problems import problem_id, upgrade_problems
from tandem_backend.analytics.stats import wilson_lo
from tandem_backend.models import stable_id


def tool_session(sid, **kw):
    s = Session(sid, **kw)
    s.user("跑一下测试")
    s.tool("pytest", status="success")
    s.reply()
    return s


def chat_session(sid, **kw):
    s = Session(sid, **kw)
    s.user("解释一下这个函数")
    s.reply()
    return s


def problems_of(sessions, **kw):
    layer = analyze(bundle(sessions))[2]
    return layer.problems(**kw)


def find(result, key="retry_loop:pytest", scope="all", pool="problems"):
    return [p for p in result[pool] if p["key"] == key and p["scope"] == scope]


def test_min_sessions_boundary():
    two = problems_of([retry_session("a"), retry_session("b")])
    assert find(two) == []
    [candidate] = find(two, pool="candidates")
    assert candidate["reason"] == "below_min_sessions" and candidate["min_sessions"] == 3
    three = problems_of([retry_session("a"), retry_session("b"), retry_session("c")])
    [problem] = find(three)
    assert problem["upgraded"] and problem["sessions"] == 3 and problem["denominator"] == 3
    assert problem["session_uids"] == ["a", "b", "c"]
    assert problem["type"] == "tool_env_failure" and problem["signal_kinds"] == ["retry_loop"]


def test_wilson_lower_bound_gate():
    sessions = [retry_session(f"r{i}") for i in range(3)] + [tool_session(f"t{i}") for i in range(57)]
    result = problems_of(sessions)
    [candidate] = find(result, pool="candidates")
    assert candidate["denominator"] == 60 and candidate["sessions"] == 3
    assert candidate["wilson_lo"] == wilson_lo(3, 60) < 0.05
    assert candidate["reason"] == "below_wilson_lo"
    assert candidate["rate"]["status"] == "ok" and candidate["rate"]["n"] == 60


def test_denominator_counts_only_sessions_with_the_opportunity():
    sessions = [retry_session(f"r{i}") for i in range(3)] + [chat_session(f"c{i}") for i in range(57)]
    [problem] = find(problems_of(sessions))
    # Chat-only sessions never had a tool call, so they are outside the retry_loop denominator.
    assert problem["denominator"] == 3 and problem["upgraded"]


def test_unknown_evidence_is_excluded_from_denominator():
    signals = [{"problem_type": "tool_env_failure", "key": "retry_loop:pytest", "kind": "retry_loop",
                "session_uid": sid, "value": 1, "signal_id": sid, "occurrences": [{"ts": 1}]}
               for sid in ("a", "b", "c")]
    def fact(sid, status):
        return {"session_uid": sid, "project_id": "p", "source_id": "s",
                "opportunities": {"tools": True, "human": True},
                "signals_summary": {"retry_loop": status}}
    facts = [fact("a", 1), fact("b", 1), fact("c", 1), fact("x", None), fact("y", 0)]
    [problem] = [p for p in upgrade_problems(signals, facts)["problems"] if p["scope"] == "all"]
    assert problem["denominator"] == 4  # x is unknown, not a zero


def test_problem_id_is_stable_and_scoped():
    sessions = [retry_session(f"r{i}", project="p1" if i < 3 else "p2") for i in range(4)]
    first, second = problems_of(sessions), problems_of(sessions)
    ids = lambda r: sorted(p["problem_id"] for p in r["problems"] + r["candidates"])  # noqa: E731
    assert ids(first) == ids(second)
    [allp] = find(first)
    assert allp["problem_id"] == stable_id("tool_env_failure", "retry_loop:pytest", "all", "all")
    [p1] = [p for p in find(first, scope="project") if p["scope_id"] == "p1"]
    assert p1["problem_id"] == problem_id("tool_env_failure", "retry_loop:pytest", "project", "p1")
    assert p1["sessions"] == 3 and p1["upgraded"]
    [p2] = [p for p in find(first, scope="project", pool="candidates") if p["scope_id"] == "p2"]
    assert p2["reason"] == "below_min_sessions"
    assert {p["scope_id"] for p in find(first, scope="source")} == {"src-a"}


def test_labels_are_read_only_and_never_overwritten():
    sessions = [retry_session(f"r{i}") for i in range(3)]
    pid = stable_id("tool_env_failure", "retry_loop:pytest", "all", "all")
    labels = [{"target_kind": "problem", "target_id": pid, "label": "resolved"},
              {"target_kind": "recommendation", "target_id": pid, "label": "dismissed"}]
    snapshot = copy.deepcopy(labels)
    layer = analyze(bundle(sessions))[2]
    [labelled] = find(layer.problems(labels))
    assert labelled["label"] == "resolved" and labelled["status"] == "resolved"
    assert labelled["upgraded"]  # the problem is still reported, only its status is read
    assert labels == snapshot
    [fresh] = find(layer.problems())
    assert fresh["label"] is None and fresh["status"] == "active"
    dismissed = [{"target_kind": "problem", "target_id": pid, "label": "dismissed"}]
    assert find(layer.problems(dismissed))[0]["status"] == "dismissed"


def test_unsafe_operation_upgrades_with_one_session():
    s = Session("a")
    s.user("清理")
    s.tool("rm -rf dist", status="success")
    result = problems_of([s, chat_session("b")])
    [problem] = find(result, key="risky_command:rm_recursive_force")
    assert problem["type"] == "unsafe_operation" and problem["min_sessions"] == 1
    assert problem["denominator"] == 2
