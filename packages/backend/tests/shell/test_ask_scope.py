"""ASK-01: whitelisted queries follow the page scope (window, project, sources) and the
persisted exclusions."""

from __future__ import annotations

import pytest
from realtime_fixtures import NOW, Reads, Tandem

from tandem_backend.ai import queries
from tandem_backend.ai.ask import _Q
from tandem_backend.appdb import AppDB
from tandem_backend.sessionops import exclusion

H = 3_600_000
WINDOW = {"start_ms": NOW - 48 * H, "end_ms": NOW}


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    t = Tandem(home)
    t.db.execute("INSERT INTO project(project_id, key_type, key, name) "
                 "VALUES ('p2', 'path', '/w/p2', 'other')")
    for i, (agent, project) in enumerate([("claude_code", "p1"), ("claude_code", "p2"),
                                          ("codex", "p2"), ("codex", "p1")]):
        uid = f"s{i}"
        t.session(uid, agent=agent, status="completed", started=NOW - (i + 1) * H,
                  ended=NOW - (i + 1) * H + 600_000)
        t.db.execute("UPDATE session SET project_id = ? WHERE session_uid = ?", (project, uid))
        t.event(uid, NOW - (i + 1) * H, actor="human", kind="message.user", text="hi")
    t.session("old", status="completed", started=NOW - 100 * H, ended=NOW - 99 * H)
    t.db.close()
    appdb = AppDB(tmp_path / "app.db")
    yield Reads(home / "tandem.db"), appdb, home
    appdb.close()


def sessions(env, scope):
    reads, appdb, home = env
    rows = queries.run("metrics", {"scope": scope, "metric": "sessions"}, reads=reads.read,
                       appdb=appdb, home=home)["rows"]
    return rows[0]["value"]


def test_scope_schema_accepts_page_filters():
    queries.check("metrics", {"scope": {**WINDOW, "project_id": "p1", "source_ids": ["x"]}})
    with pytest.raises(ValueError):
        queries.check("metrics", {"scope": {"agent": "codex"}})


def test_window_project_and_sources(env):
    assert sessions(env, WINDOW) == 4  # "old" is outside the window
    assert sessions(env, {**WINDOW, "project_id": "p2"}) == 2
    assert sessions(env, {**WINDOW, "source_ids": ["src-codex"]}) == 2
    assert sessions(env, {**WINDOW, "project_id": "p1", "source_ids": ["src-codex"]}) == 1
    reads, appdb, home = env
    rows = queries.run("sessions", {"scope": {**WINDOW, "project_id": "p2"}}, reads=reads.read,
                       appdb=appdb, home=home)["rows"]
    assert {r["session_uid"] for r in rows} == {"s1", "s2"}


def test_persisted_exclusions_are_not_counted(env):
    reads, appdb, home = env
    exclusion.add(appdb, "s1", reason="test")
    assert sessions(env, {**WINDOW, "project_id": "p2"}) == 1
    rows = queries.run("sessions", {"scope": WINDOW}, reads=reads.read, appdb=appdb,
                       home=home)["rows"]
    assert "s1" not in {r["session_uid"] for r in rows}


def test_ask_forwards_scope_as_given(env):
    reads, appdb, home = env
    q = _Q(reads.read, appdb, {**WINDOW, "project_id": "p2"}, home)
    assert q.metrics()["sessions"]["value"] == 2
    exclusion.add(appdb, "s2")
    q = _Q(reads.read, appdb, {**WINDOW, "project_id": "p2"}, home)
    assert q.metrics()["sessions"]["value"] == 1
