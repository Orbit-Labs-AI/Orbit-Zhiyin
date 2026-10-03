"""Minimal tandem.db / app.db stand-ins for the analysis AI package; temporary HOME only."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

# Loaded under a unique name: sibling test packages may ship their own `fakectx.py`.
_spec = importlib.util.spec_from_file_location("ai_analysis_fakectx", Path(__file__).parent / "fakectx.py")
fakectx = importlib.util.module_from_spec(_spec)
sys.modules["ai_analysis_fakectx"] = fakectx
_spec.loader.exec_module(fakectx)
DAY, NOW = fakectx.DAY, fakectx.NOW

SCHEMA = """
CREATE TABLE project(project_id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE session(session_uid TEXT PRIMARY KEY, kind TEXT, project_id TEXT, cwd TEXT, title TEXT, client TEXT,
  started_at INTEGER, ended_at INTEGER, status TEXT);
CREATE TABLE event(event_uid TEXT PRIMARY KEY, session_uid TEXT, kind TEXT, actor TEXT, seq INTEGER, ts INTEGER,
  text TEXT, origin TEXT);
CREATE UNIQUE INDEX event_seq ON event(session_uid, seq);
CREATE VIRTUAL TABLE event_fts USING fts5(text, content='event', content_rowid='rowid');
CREATE VIEW v_human_message AS SELECT * FROM event WHERE kind='message.user' AND origin='human';
CREATE TABLE tool_call(call_uid TEXT PRIMARY KEY, session_uid TEXT, project_id TEXT, call_event_uid TEXT,
  result_event_uid TEXT, name TEXT, kind TEXT, mcp_server TEXT, skill TEXT, command_head TEXT,
  files TEXT NOT NULL DEFAULT '[]', status TEXT, exit_code INTEGER, error_class TEXT, started_at INTEGER,
  approval TEXT);
CREATE INDEX tool_session ON tool_call(session_uid);
CREATE VIEW v_analysis_tool_call AS SELECT * FROM tool_call;
CREATE TABLE inventory_scan(scan_id INTEGER PRIMARY KEY, source_key TEXT, root_path TEXT, observed_at INTEGER);
CREATE TABLE inventory_item(scan_id INTEGER, inv_id TEXT, type TEXT, name TEXT, config_path TEXT, enabled INTEGER);
"""

FACET_DDL = """CREATE TABLE IF NOT EXISTS ai_facet (session_uid TEXT NOT NULL, prompt_version TEXT NOT NULL,
 schema_version TEXT NOT NULL, content_hash TEXT NOT NULL, model_id TEXT, status TEXT NOT NULL, json TEXT,
 job_id TEXT, created_at INTEGER NOT NULL, PRIMARY KEY(session_uid,prompt_version,schema_version))"""


class TandemDB:
    """Writable builder plus a read-only `reads()` factory like `gw.reads.read`."""

    def __init__(self, path: Path):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT INTO project VALUES ('p1','alpha'),('p2','beta')")
        self.seq: dict[str, int] = {}

    def session(self, uid, *, project="p1", title="task", start=None, minutes=10, cwd="/w", status="completed",
                kind="main", humans=(), replies=(), tools=()):
        start = NOW - DAY if start is None else start
        self.db.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
                        (uid, kind, project, cwd, title, "codex", start, start + minutes * 60_000, status))
        for i, text in enumerate(humans):
            self.event(uid, "message.user", "human", text, start + i * 1000, f"{uid}-h{i}")
        for i, text in enumerate(replies):
            self.event(uid, "message.assistant", "assistant", text, start + i * 1000 + 500, f"{uid}-a{i}")
        for i, t in enumerate(tools):
            name, kind_, head, status_, error = (list(t) + [None] * 5)[:5]
            self.db.execute("INSERT INTO tool_call(call_uid,session_uid,project_id,name,kind,command_head,status,"
                            "error_class,started_at,files,approval,mcp_server) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (f"{uid}-c{i}", uid, project, name, kind_ or "shell", head, status_ or "success",
                             error, start + i * 100, json.dumps(["src/a.py"]), None,
                             name[4:] if name and name.startswith("mcp:") else None))
        return uid

    def event(self, uid, kind, actor, text, ts, event_uid):
        seq = self.seq.get(uid, 0)
        self.seq[uid] = seq + 1
        self.db.execute("INSERT INTO event VALUES (?,?,?,?,?,?,?,?)",
                        (event_uid, uid, kind, actor, seq, ts, text, "human" if actor == "human" else None))

    def inventory(self, items, root="/r"):
        cur = self.db.execute("INSERT INTO inventory_scan(source_key,root_path,observed_at) VALUES ('k',?,?)",
                              (root, NOW))
        for i, (type_, name, path) in enumerate(items):
            self.db.execute("INSERT INTO inventory_item VALUES (?,?,?,?,?,1)", (cur.lastrowid, f"i{i}", type_, name,
                                                                                path))

    def commit(self):
        self.db.execute("INSERT INTO event_fts(event_fts) VALUES('rebuild')")
        self.db.commit()

    @contextmanager
    def reads(self):
        conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


class FakeAppDB:
    def __init__(self, path: Path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute(FACET_DDL)
            # Same table as appdb/schema/sessionops.sql; queries._excluded is fail-closed.
            db.execute("CREATE TABLE IF NOT EXISTS session_exclusion (session_uid TEXT PRIMARY KEY, "
                       "reason TEXT, note TEXT, excluded_at INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'user')")

    @contextmanager
    def read(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def put_facet(self, uid, pv, content_hash):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO ai_facet VALUES (?,?,?,?,?,?,?,?,?)",
                       (uid, pv, "1.1", content_hash, None, "ok", json.dumps({"task_type": "bugfix",
                                                                                "summary": "修好了"}), None, NOW))


@pytest.fixture
def user_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "alex"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USER", "alex")
    monkeypatch.setenv("LOGNAME", "alex")
    return home


@pytest.fixture
def tdb(tmp_path, user_home) -> TandemDB:
    return TandemDB(tmp_path / "tandem.db")


@pytest.fixture
def appdb(tmp_path) -> FakeAppDB:
    return FakeAppDB(tmp_path / "app.db")


@pytest.fixture
def tandem_home(tmp_path) -> Path:
    path = tmp_path / "tandem-home"
    path.mkdir()
    return path
