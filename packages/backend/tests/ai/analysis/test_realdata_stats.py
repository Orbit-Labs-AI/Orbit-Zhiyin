"""Real-data regressions for pack metrics and ask statistics (synthetic data only).

B7 hours as interval union, B8 correction heuristic, B9 one-pass metrics, B10 scoped error class,
a4a6-B10 minimum sample / unattributed bucket / known-only denominators.
"""

from __future__ import annotations

import pytest
from ai_analysis_fakectx import DAY, NOW

from tandem_backend.ai import ask, queries
from tandem_backend.ai import pack as P

HOUR = 3_600_000


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(P, "now_ms", lambda: NOW)
    P._METRICS_CACHE.clear()


def _metrics(tdb, home, days):
    rows = queries.run("metrics", {"scope": {"days": days}}, reads=tdb.reads, home=home)["rows"]
    return {r["metric"]: r for r in rows}


def test_hours_are_the_union_of_overlapping_sessions(tdb, tandem_home):
    # Three sessions opened within the same hour and left open for 24 h.
    for i in range(3):
        tdb.session(f"s{i}", start=NOW - DAY + i * 600_000, minutes=24 * 60, humans=["做个功能"])
    tdb.commit()
    m = _metrics(tdb, tandem_home, 2)
    assert m["hours"]["value"] == 24.0  # clipped at the window end, overlap counted once
    projects = queries.run("projects", {"scope": {"days": 2}}, reads=tdb.reads, home=tandem_home)["rows"]
    assert projects[0]["hours"] == 24.0 and projects[0]["sessions"] == 3


def test_union_ms_merges_and_clips():
    assert P.union_ms([(0, 10), (5, 20), (30, 40)]) == 30
    assert P.union_ms([(0, 10), (5, 20)], 8, 15) == 7
    assert P.union_ms([(5, None), (None, 9), (7, 3)]) == 0


@pytest.mark.parametrize("text, verdict", [
    ("不对，不是这样", True),
    ("不是将 A 改为 B，而是保留 A", True),
    ("你说的不对，换一种做法", True),
    ("No, use the other file", True),
    ("that's not what I asked", True),
    ("this is still wrong", True),
    ("Try again", False),
    ("again please run the tests", False),
    ("我们需要的是一个服务，而不是一个脚本，请你实现它", False),
    ("请检查计数为什么不对应", False),
    ("我这句话对不对", False),
    ("不对" + "，请重新整理需求" * 40, False),  # long prompts are requests, not pushback
])
def test_correction_heuristic(text, verdict):
    assert P.is_correction(text) is verdict


def test_correction_rate_ignores_copula_and_retries(tdb, tandem_home):
    long_prompt = "请你实现这个功能，" + "注意这不是一个简单的任务，" * 40
    tdb.session("s1", humans=["做个功能", long_prompt, "Try again", "不对，回到上一版"])
    tdb.commit()
    m = _metrics(tdb, tandem_home, 7)
    assert m["human_messages"]["value"] == 4 and m["corrections"]["value"] == 1


def test_metrics_pair_matches_two_single_windows(tdb, tandem_home):
    for i in range(4):
        tdb.session(f"c{i}", start=NOW - (i + 1) * DAY, humans=["做", "不对，重来"],
                    tools=[("Bash", "shell", "pytest", "failed", "exit"), ("Read", "read")])
        tdb.session(f"p{i}", start=NOW - (10 + i) * DAY, humans=["做"], tools=[("Read", "read")])
    tdb.commit()
    with tdb.reads() as conn:
        start, end = NOW - 7 * DAY, NOW
        cur, prev = P.metrics_pair(conn, start, end)
        P._METRICS_CACHE.clear()
        assert cur == P.metrics(conn, start, end)
        P._METRICS_CACHE.clear()
        assert prev == P.metrics(conn, start - 7 * DAY, start)
    assert cur["sessions"] == 4 and cur["corrections"] == 4 and cur["tool_failure_rate"] == 0.5
    assert prev["sessions"] == 4 and prev["corrections"] == 0


def test_metrics_cache_sees_new_data(tdb, tandem_home):
    tdb.session("a", humans=["做"])
    tdb.commit()
    assert _metrics(tdb, tandem_home, 7)["sessions"]["value"] == 1
    tdb.session("b", humans=["做"])
    tdb.commit()
    assert _metrics(tdb, tandem_home, 7)["sessions"]["value"] == 2


def test_failure_rate_uses_known_statuses(tdb, tandem_home):
    tools = [("Edit", "edit", None, "failed", "x")] + [("Edit", "edit", None, "unknown")] * 9 + \
        [("Edit", "edit", None, "success")]
    tdb.session("s1", tools=tools)
    tdb.commit()
    row = queries.run("tools", {}, reads=tdb.reads, home=tandem_home)["rows"][0]
    assert row["calls"] == 11 and row["known_calls"] == 2 and row["failure_rate"] == 0.5
    assert _metrics(tdb, tandem_home, 7)["tool_failure_rate"]["value"] == 0.5


def test_top_error_class_is_scoped_to_the_window(tdb, tandem_home):
    tdb.session("old", start=NOW - 90 * DAY, tools=[("Bash", "shell", "x", "failed", "old_err")] * 5)
    tdb.session("new", tools=[("Bash", "shell", "x", "failed", "new_err")] * 2)
    tdb.commit()
    row = queries.run("tools", {"scope": {"days": 7}}, reads=tdb.reads, home=tandem_home)["rows"][0]
    assert row["tool"] == "Bash" and row["failures"] == 2 and row["top_error_class"] == "new_err"


def test_approvals_exclude_denied(tdb, tandem_home):
    tdb.session("s1", tools=[("Bash", "shell", "rm")] * 3)
    tdb.db.execute("UPDATE tool_call SET approval='allowed-once' WHERE call_uid='s1-c0'")
    tdb.db.execute("UPDATE tool_call SET approval='denied' WHERE call_uid IN ('s1-c1','s1-c2')")
    tdb.commit()
    row = queries.run("tools", {}, reads=tdb.reads, home=tandem_home)["rows"][0]
    assert row["approvals"] == 1 and row["denied"] == 2
    answer = ask.preset_answer("tools", 1, reads=tdb.reads, home=tandem_home)["answer"]
    assert "1 次经你批准后执行，2 次被你拒绝" in answer


def test_projects_report_unattributed_sessions_and_scope_tools(tdb, tandem_home):
    tdb.session("a", project="p1", tools=[("Read", "read")] * 3)
    tdb.session("b", project=None, tools=[("Read", "read")] * 2)
    tdb.session("old", project="p1", start=NOW - 90 * DAY, tools=[("Read", "read")] * 50)
    tdb.commit()
    rows = {r["name"]: r for r in queries.run("projects", {"scope": {"days": 30}}, reads=tdb.reads,
                                               home=tandem_home)["rows"]}
    assert rows["alpha"]["tool_calls"] == 3  # the 90-day-old session is outside the window
    assert rows["未归类"]["unattributed"] and rows["未归类"]["sessions"] == 1


def test_project_friction_needs_a_real_sample(tdb, tandem_home):
    small = [("Bash", "shell", "x", "failed", "e")] * 4 + [("Bash", "shell", "x")] * 31
    big = [("Bash", "shell", "x", "failed", "e")] * 70 + [("Bash", "shell", "x")] * 930
    tdb.session("small", project="p1", tools=small)
    tdb.session("big", project="p2", tools=big)
    tdb.commit()
    answer = ask.preset_answer("projects", 1, reads=tdb.reads, home=tandem_home)["answer"]
    assert answer.startswith("「beta」")
    assert ask.wilson_lower(4, 35) < ask.wilson_lower(70, 1000)


def test_correction_phrases_skip_retries(tdb, tandem_home):
    tdb.session("s1", humans=["Try again", "again", "不对，换个方法"])
    tdb.commit()
    answer = ask.preset_answer("sentiment", 0, reads=tdb.reads, home=tandem_home)["answer"]
    assert "Try again" not in answer and "不对，换个方法" in answer
