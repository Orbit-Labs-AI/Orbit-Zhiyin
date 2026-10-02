"""DT-18 suite and reader over a synthetic home and a tiny tandem.db (no real home)."""

import json
import sqlite3

import pytest

from tandem_backend.evalrun.contract import EvalContext
from tandem_backend.evalrun.insights_reader import FIELDS, read_session_meta
from tandem_backend.evalrun.suites import insights as suite

SESSIONS = {f"uuid-{i}": {"tools": 10 + i, "users": 4, "minutes": 20.0, "tokens": (1000, 200)}
            for i in range(5)}


def _home(tmp_path, tweak=None):
    home = tmp_path / "home"
    meta = home / ".claude/usage-data/session-meta"
    facets = home / ".claude/usage-data/facets"
    meta.mkdir(parents=True)
    facets.mkdir(parents=True)
    for sid, s in SESSIONS.items():
        tools = s["tools"] if tweak is None else tweak
        body = {"session_id": sid, "project_path": "/Users/example/p", "start_time": "2026-09-01T10:00:00Z",
                "duration_minutes": s["minutes"], "user_message_count": s["users"],
                "assistant_message_count": 9, "tool_counts": {"Bash": tools - 3, "Edit": 3},
                "input_tokens": s["tokens"][0], "output_tokens": s["tokens"][1], "languages": {"py": 2}}
        (meta / f"{sid}.json").write_text(json.dumps(body))
        (facets / f"{sid}.json").write_text(json.dumps({"session_id": sid, "outcome": "achieved"}))
    (meta / "only-in-insights.json").write_text(json.dumps({"session_id": "x", "user_message_count": 1}))
    (meta / "broken.json").write_text("{not json")
    return home


def _tandem(tmp_path):
    path = tmp_path / "tandem.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE session(session_uid TEXT PRIMARY KEY, native_id TEXT, started_at INTEGER, ended_at INTEGER);
        CREATE TABLE tool_call(call_uid TEXT, session_uid TEXT);
        CREATE TABLE event(event_uid TEXT, session_uid TEXT, kind TEXT);
        CREATE VIEW v_human_message AS SELECT * FROM event WHERE kind = 'message.user';
        CREATE TABLE model_call(session_uid TEXT, input_tokens INTEGER, output_tokens INTEGER);
    """)
    for n, (sid, s) in enumerate(SESSIONS.items()):
        uid = f"s{n}"
        db.execute("INSERT INTO session VALUES (?,?,?,?)", (uid, sid, 0, int(s["minutes"] * 60000)))
        db.executemany("INSERT INTO tool_call VALUES (?,?)", [(f"{uid}c{i}", uid) for i in range(s["tools"])])
        db.executemany("INSERT INTO event VALUES (?,?,?)",
                       [(f"{uid}e{i}", uid, "message.user") for i in range(s["users"])])
        db.execute("INSERT INTO model_call VALUES (?,?,?)", (uid, *s["tokens"]))
    db.execute("INSERT INTO session VALUES ('codex-1', 'not-claude', 0, 1)")
    db.commit()
    db.close()
    return path


def test_reader_normalizes_and_counts_warnings(tmp_path):
    warnings = []
    rows = read_session_meta(_home(tmp_path), warnings)
    assert len(rows) == 6 and warnings == ["broken.json: JSONDecodeError"]
    row = next(r for r in rows if r["session_id"] == "uuid-0")
    assert row["tool_counts"] == {"Bash": 7, "Edit": 3} and row["facet"]["outcome"] == "achieved"
    assert set(row) == {*FIELDS, "facet"}


def test_clean_comparison(tmp_path):
    ctx = EvalContext(tmp=tmp_path, home=_home(tmp_path), params={"tandem_db": str(_tandem(tmp_path))})
    result = suite.run(ctx)
    assert result.skipped is None
    assert {c.id: c.passed for c in result.checks} == {
        f"insights.{m}.agree_within_10pct": True for m in ("tool_calls", "user_messages", "duration_minutes",
                                                           "tokens")}
    assert result.metrics["matched"] == 5
    assert result.metrics["unmatched_insights"] == 1 and result.metrics["unmatched_tandem"] == 1
    assert result.metrics["warnings"] == 1


def test_disagreeing_tool_counts_fail(tmp_path):
    ctx = EvalContext(tmp=tmp_path, home=_home(tmp_path, tweak=40), params={"tandem_db": str(_tandem(tmp_path))})
    failed = {c.id for c in suite.run(ctx).checks if not c.passed}
    assert failed == {"insights.tool_calls.agree_within_10pct"}


@pytest.mark.parametrize("make", [
    lambda t: EvalContext(tmp=t),
    lambda t: EvalContext(tmp=t, home=t / "empty"),
    lambda t: EvalContext(tmp=t, home=_home(t), params={"tandem_db": str(t / "missing.db")}),
])
def test_skips_without_inputs(tmp_path, make):
    assert suite.run(make(tmp_path)).skipped
