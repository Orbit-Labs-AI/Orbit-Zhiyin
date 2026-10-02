"""Minimal tandem.db / catalog.db / app.db built from native DDL; no real HOME is touched."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

DAY = 86_400_000
NOW = 1_800_000_000_000

TANDEM_DDL = """
CREATE TABLE project (project_id TEXT PRIMARY KEY, key_type TEXT NOT NULL, key TEXT NOT NULL,
  name TEXT NOT NULL, git_remote TEXT, paths TEXT NOT NULL DEFAULT '[]') STRICT;
CREATE TABLE source (source_id TEXT PRIMARY KEY, agent TEXT NOT NULL, root_path TEXT NOT NULL,
  label TEXT, enabled INTEGER NOT NULL DEFAULT 1, discovered_at INTEGER NOT NULL) STRICT;
CREATE TABLE session (session_uid TEXT PRIMARY KEY, source_id TEXT NOT NULL, native_id TEXT NOT NULL,
  project_id TEXT, title TEXT, started_at INTEGER, ended_at INTEGER) STRICT;
CREATE TABLE event (event_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL, kind TEXT NOT NULL,
  actor TEXT NOT NULL, seq INTEGER NOT NULL, ts INTEGER, text TEXT,
  attrs TEXT NOT NULL DEFAULT '{}', ext TEXT NOT NULL DEFAULT '{}') STRICT;
CREATE TABLE tool_call (call_uid TEXT PRIMARY KEY, session_uid TEXT NOT NULL, project_id TEXT,
  name TEXT NOT NULL, kind TEXT NOT NULL, mcp_server TEXT, skill TEXT, command_head TEXT,
  files TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL, error_class TEXT,
  started_at INTEGER) STRICT;
CREATE TABLE projection_run (run_id INTEGER PRIMARY KEY, completed_at INTEGER NOT NULL,
  event_count INTEGER NOT NULL) STRICT;
CREATE VIRTUAL TABLE event_fts USING fts5(text, content='event', content_rowid='rowid');
CREATE TRIGGER event_ai AFTER INSERT ON event BEGIN
  INSERT INTO event_fts(rowid,text) VALUES(new.rowid,new.text);
END;
CREATE TABLE inventory_scan (scan_id INTEGER PRIMARY KEY, source_key TEXT NOT NULL,
  agent TEXT NOT NULL, root_path TEXT NOT NULL, scope TEXT NOT NULL, project_id TEXT,
  observed_at INTEGER NOT NULL, scanner_version TEXT NOT NULL, coverage TEXT NOT NULL,
  diagnostics TEXT NOT NULL) STRICT;
CREATE TABLE inventory_item (scan_id INTEGER NOT NULL, inv_id TEXT NOT NULL, type TEXT NOT NULL,
  name TEXT NOT NULL, config_path TEXT NOT NULL, locator TEXT NOT NULL, enabled INTEGER,
  evidence TEXT NOT NULL, config TEXT NOT NULL, content_hash TEXT NOT NULL,
  PRIMARY KEY(scan_id, inv_id)) STRICT;
"""

CATALOG_DDL = """
CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
INSERT INTO catalog_meta VALUES ('generation', '1');
CREATE TABLE catalog_item (item_id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
  summary TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL, official INTEGER NOT NULL,
  content_hash TEXT NOT NULL, metadata TEXT NOT NULL) STRICT;
CREATE TABLE item_feature (item_id TEXT NOT NULL, feature TEXT NOT NULL, value TEXT NOT NULL,
  weight REAL NOT NULL, origin TEXT NOT NULL, evidence TEXT NOT NULL,
  PRIMARY KEY(item_id, feature, value, origin)) STRICT;
CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, item_id UNINDEXED, title, content);
"""

APP_DDL = """
CREATE TABLE inv_link (inv_id TEXT PRIMARY KEY, catalog_item_id TEXT NOT NULL, method TEXT NOT NULL,
  confidence REAL NOT NULL, catalog_rev TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0) STRICT;
CREATE TABLE inv_size (content_hash TEXT PRIMARY KEY, tokens_est INTEGER, basis TEXT,
  measured_at INTEGER) STRICT, WITHOUT ROWID;
"""


class World:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.tandem = self.home / "tandem.db"
        self.catalog = self.home / "catalog.db"
        self.app = self.home / "app.db"
        self.t = sqlite3.connect(self.tandem, isolation_level=None)
        self.t.executescript(TANDEM_DDL)
        self.t.execute("INSERT INTO projection_run VALUES (1, 0, 0)")
        self.c = sqlite3.connect(self.catalog, isolation_level=None)
        self.c.executescript(CATALOG_DDL)
        self.a = sqlite3.connect(self.app, isolation_level=None)
        self.a.executescript(APP_DDL)
        self.seq = 0
        self.scan = 0

    # tandem.db
    def project(self, pid, name, paths=()):
        self.t.execute("INSERT INTO project VALUES (?,?,?,?,NULL,?)",
                       (pid, "path", f"/p/{pid}", name, json.dumps(list(paths))))

    def source(self, sid, agent):
        self.t.execute("INSERT INTO source VALUES (?,?,?,NULL,1,0)", (sid, agent, f"/r/{sid}"))

    def session(self, uid, source="s-claude", project=None, title=None, started=NOW - DAY,
                ended=None):
        self.t.execute("INSERT OR REPLACE INTO session VALUES (?,?,?,?,?,?,?)",
                       (uid, source, uid, project, title, started, ended))

    def message(self, session, text, ts=NOW - DAY, kind="message.user", actor="human", attrs=None):
        self.seq += 1
        self.t.execute("INSERT INTO event(event_uid,session_uid,kind,actor,seq,ts,text,attrs) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (f"e{self.seq}", session, kind, actor, self.seq, ts, text,
                        json.dumps(attrs or {})))
        return f"e{self.seq}"

    def call(self, session, *, skill=None, mcp=None, command=None, files=(), status="ok",
             started=NOW - DAY, project=None):
        self.seq += 1
        self.t.execute("INSERT INTO tool_call VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)",
                       (f"c{self.seq}", session, project, "tool", "other", mcp, skill, command,
                        json.dumps(list(files)), status, started))

    def inventory(self, agent, items, scope="global", project=None, source_key=None):
        self.scan += 1
        self.t.execute("INSERT INTO inventory_scan VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (self.scan, source_key or agent, agent, f"/r/{agent}", scope, project,
                        NOW - DAY, "1", "{}", "{}"))
        for item in items:
            row = {"enabled": 1, "evidence": "file", "config": {}, "content_hash": "h-" +
                   item["inv_id"], "config_path": f"/cfg/{item['inv_id']}", **item}
            self.t.execute("INSERT INTO inventory_item VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (self.scan, row["inv_id"], row["type"], row["name"],
                            row["config_path"], "", row["enabled"], row["evidence"],
                            json.dumps(row["config"]), row["content_hash"]))

    # catalog.db
    def item(self, item_id, type_, name, summary="", official=0, body_sha256=None, url=""):
        meta = {"body_sha256": body_sha256} if body_sha256 else {}
        self.c.execute("INSERT INTO catalog_item VALUES (?,?,?,?,?,?,?,?,?)",
                       (item_id, type_, name, summary, url or f"https://x/{item_id}", "active",
                        official, "digest-" + item_id, json.dumps(meta)))

    def connection(self, catalog=True) -> sqlite3.Connection:
        conn = sqlite3.connect(self.app.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("ATTACH DATABASE ? AS t", (self.tandem.as_uri() + "?mode=ro",))
        if catalog:
            conn.execute("ATTACH DATABASE ? AS c", (self.catalog.as_uri() + "?mode=ro",))
        return conn

    def write(self, fn):
        self.a.execute("BEGIN IMMEDIATE")
        try:
            fn(self.a)
        except BaseException:
            self.a.execute("ROLLBACK")
            raise
        self.a.execute("COMMIT")


@pytest.fixture
def world(tmp_path):
    from tandem_backend.features import linked

    linked.clear_cache()
    w = World(tmp_path)
    w.source("s-claude", "claude_code")
    w.source("s-codex", "codex")
    yield w
    for conn in (w.t, w.c, w.a):
        conn.close()
