"""Tool-call ``seq`` comes from covering indexes, never from a per-call ``event`` row read.

Real store (2164 sessions, 145k tool calls, 7 GB orbit.db): ``LEFT JOIN event`` for ``e.seq``
made /v1/uiview/projects and /v1/uiview/sentiment 1.3–2.4 s on every request and the first
/v1/uiview/tools 2–5 s; the covering-index path reads the same values in a fraction.
"""

from __future__ import annotations

import re
import sqlite3

from orbit_backend.analytics.inputs import Scope
from orbit_backend.uiview import a4a6_common as common
from orbit_backend.uiview import a4a6_sentiment as S
from orbit_backend.uiview import a4a6_tools as tools

from .a4a6_ps_fixture import MIN, T0, Orbit, ro

# Plan lines reading the event table, by name or through one of its indexes (aliases hide it).
EVENT_ACCESS = re.compile(r"(SCAN|SEARCH) event\b|sqlite_autoindex_event_|INDEX (event_by|fk_event_)")


def _store(tmp_path):
    t = Orbit(tmp_path)
    t.project("p1")
    t.session("m1")
    t.session("sub1", kind="subagent", root="m1", start=T0 + MIN)
    t.session("m2", start=T0 + 2 * MIN)
    t.human("m1", "先跑测试", ts=T0)
    # Insert seq 5 before seq 1 so rowid order differs from seq order.
    t.seq["m1"] = 5
    t.call("m1", head="pytest -q", ts=T0 + 10)
    t.seq["m1"] = 1
    t.call("m1", head="ls", ts=T0 + 20)
    t.call("sub1", head="cat a.py", ts=T0 + MIN)
    t.call("m2", head="git status", ts=T0 + 2 * MIN)
    # A call whose event lives in another session, and one with no call event at all.
    t.db.execute("INSERT INTO tool_call(call_uid, session_uid, call_event_uid, name_raw, name, "
                 "kind, files, status, pairing_quality, started_at, duration_source, "
                 "duration_quality) VALUES ('cross','m1',?,'Bash','bash','shell','[]','ok',"
                 "'paired',?, 'unknown','missing')",
                 (t.db.execute("SELECT event_uid FROM event WHERE session_uid='m2' AND "
                               "kind='tool.call'").fetchone()[0], T0 + 30))
    t.db.execute("INSERT INTO tool_call(call_uid, session_uid, call_event_uid, name_raw, name, "
                 "kind, files, status, pairing_quality, started_at, duration_source, "
                 "duration_quality) VALUES ('orphan','m1',NULL,'Bash','bash','shell','[]','ok',"
                 "'paired',?, 'unknown','missing')", (T0 + 40,))
    t.close()
    return tmp_path / "orbit.db"


def _reference(conn) -> dict:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT t.call_uid, e.seq FROM tool_call t LEFT JOIN event e ON e.event_uid=t.call_event_uid")}


def _event_plans(conn, run):
    """EXPLAIN QUERY PLAN lines touching ``event`` for every statement ``run`` executes."""
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        run()
    finally:
        conn.set_trace_callback(None)
    plans = []
    for sql in statements:
        if not sql.lstrip().upper().startswith("SELECT"):
            continue
        plans += [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql)
                  if EVENT_ACCESS.search(row[3])]
    return plans


def _assert_index_only(plans):
    assert plans, "expected event lookups"
    for line in plans:
        assert "COVERING INDEX" in line or "INTEGER PRIMARY KEY" in line, line


def test_sentiment_calls_seq_matches_event_rows(tmp_path):
    conn = ro(_store(tmp_path))
    ref = _reference(conn)
    calls = S.fetch_calls(conn, ["m1", "m2"])
    assert {c["call_uid"]: c["seq"] for c in calls} == ref
    assert ref["orphan"] is None and ref["cross"] is not None
    assert "call_event_rowid" not in calls[0]
    # seq, not rowid, orders the root session: ls (seq 1) before pytest (seq 5).
    heads = [c["command_head"] for c in calls if c["root_uid"] == "m1"
             and c["session_uid"] == "m1" and c["command_head"]]
    assert heads == ["ls", "pytest -q"]


def test_tools_calls_seq_matches_event_rows(tmp_path):
    conn = ro(_store(tmp_path))
    ref = _reference(conn)
    rows = tools.fetch_calls(conn, Scope())
    assert {r["call_uid"]: r["seq"] for r in rows} == ref
    assert all("call_event_rowid" not in r for r in rows)


def test_seq_reads_never_touch_event_rows(tmp_path):
    conn = ro(_store(tmp_path))
    _assert_index_only(_event_plans(conn, lambda: S.fetch_calls(conn, ["m1", "m2"])))
    _assert_index_only(_event_plans(conn, lambda: tools.fetch_calls(conn, Scope())))


def test_attach_event_seq_handles_empty_and_missing(tmp_path):
    conn = ro(_store(tmp_path))
    assert common.attach_event_seq(conn, []) == []
    rows = [{"session_uid": "m1", "call_event_rowid": None},
            {"session_uid": "nope", "call_event_rowid": 10_000}]
    common.attach_event_seq(conn, rows)
    assert [r["seq"] for r in rows] == [None, None]
    assert isinstance(conn, sqlite3.Connection)


def test_command_only_for_approval_gated_calls(tmp_path):
    t = Orbit(tmp_path)
    t.project("p1")
    t.session("m1")
    asked = t.call("m1", head="find", approval="approved", ts=T0)
    t.call("m1", head="find", ts=T0 + 1)
    t.db.execute("UPDATE event SET attrs=json_set(attrs, '$.input.command', ?) WHERE event_uid=?",
                 ("find . -name '*.py' -delete", asked))
    t.close()
    conn = ro(tmp_path / "orbit.db")
    for rows in (S.fetch_calls(conn, ["m1"]), tools.fetch_calls(conn, Scope())):
        by = {r["call_uid"]: r for r in rows}
        assert by["c1"]["command"] == "find . -name '*.py' -delete"  # argv decides: a write
        assert "command" not in by["c2"]  # never consumed: no event row read for it
