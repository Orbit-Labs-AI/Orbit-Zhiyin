"""Synthetic tandem.db helpers for realtime tests (tmp dirs only; never a real HOME).

A uniquely named module rather than conftest imports, so whole-suite runs do not pick up
another directory's conftest."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from tandem_data.store import Store

NOW = 1_800_000_000_000
ATTRS = json.dumps({"time": {"quality": "reported", "source_field": "timestamp"}})


class Tandem:
    """Raw INSERT helper over the real tandem.db schema (foreign keys off)."""

    def __init__(self, home: Path):
        Store(home).db.close()
        self.path = home / "tandem.db"
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = OFF")
        self.n = 0
        for agent in ("claude_code", "codex"):
            self.db.execute("INSERT OR IGNORE INTO source VALUES (?, ?, ?, NULL, 1, 0)",
                            (f"src-{agent}", agent, f"/tmp/{agent}"))
        self.db.execute("INSERT OR IGNORE INTO project(project_id, key_type, key, name) "
                        "VALUES ('p1', 'path', '/w/p1', 'demo')")

    def session(self, uid, *, agent="claude_code", status="active", started=None, ended=None,
                title=None):
        self.db.execute(
            "INSERT OR REPLACE INTO session(session_uid, source_id, native_id, kind, root_uid, "
            "project_id, title, started_at, ended_at, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, f"src-{agent}", uid, "main", uid, "p1", title or uid, started, ended, status))

    def event(self, uid, ts, kind="message", actor="assistant", *, text=None, attrs=None):
        self.n += 1
        merged = {**json.loads(ATTRS), **(attrs or {})}
        self.db.execute(
            "INSERT INTO event(event_uid, session_uid, record_uid, native_key, event_path, kind, "
            "actor, seq, ts, text, attrs, contract_version, mapper_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,'t')",
            (f"e{self.n}", uid, f"r{self.n}", "[]", "$", kind, actor, self.n, ts, text,
             json.dumps(merged)))

    def call(self, uid, ts, *, head="ls", status="ok", error_class=None, digest="d",
             ended=True, name="Bash"):
        self.n += 1
        self.db.execute(
            "INSERT INTO tool_call(call_uid, session_uid, name_raw, name, kind, command_head, "
            "status, pairing_quality, error_class, argument_digest, started_at, ended_at, "
            "duration_source, duration_quality) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"c{self.n}", uid, name, name.lower(), "shell", head, status, "paired",
             error_class, digest, ts, ts + 10 if ended else None, "unknown", "missing"))

    def usage(self, uid, ts, input_tokens, cache_read=0, model="claude-sonnet-4-5"):
        self.n += 1
        self.db.execute(
            "INSERT INTO model_call(call_uid, session_uid, usage_event_uid, model_raw, model_id, "
            "model_resolution, coverage, input_tokens, cache_read_tokens, ts) "
            "VALUES (?,?,?,?,?,'exact','full',?,?,?)",
            (f"m{self.n}", uid, f"u{self.n}", model, model, input_tokens, cache_read, ts))


class Reads:
    """Stands in for gw.reads: ``read(check=...)`` yields a Row connection."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def read(self, check: bool = True):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()
