"""Synthetic orbit.db / catalog.db / app.db under tmp_path; never touches the real HOME."""

from __future__ import annotations

import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest
from orbit_data.store import Store

from orbit_backend.appdb import AppDB
from orbit_backend.features.service import FeatureService

DAY = 86_400_000
T0 = 1_760_000_000_000


class Orbit:
    """Raw INSERT helper over a real orbit.db schema (foreign keys off)."""

    def __init__(self, home: Path):
        Store(home).db.close()
        self.db = sqlite3.connect(home / "orbit.db", isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = OFF")
        self.calls = 0
        for agent in ("claude_code", "codex"):
            self.db.execute("INSERT OR IGNORE INTO source VALUES (?, ?, ?, NULL, 1, 0)",
                            (f"src-{agent}", agent, f"/tmp/{agent}"))
        for project in ("p1", "p2"):
            self.db.execute("INSERT OR IGNORE INTO project(project_id, key_type, key, name) "
                            "VALUES (?, 'path', ?, ?)", (project, f"/w/{project}", project))

    def session(self, uid, *, project="p1", agent="claude_code", day=0, kind="main",
                features=(), calls=()):
        started = T0 + day * DAY
        self.db.execute(
            "INSERT OR REPLACE INTO session(session_uid, source_id, native_id, kind, root_uid, "
            "project_id, title, started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, f"src-{agent}", uid, kind, uid, project, uid, started, started + 1000))
        self.db.execute("DELETE FROM session_feature WHERE session_uid = ?", (uid,))
        self.db.executemany("INSERT INTO session_feature VALUES (?, ?, ?, ?)",
                            [(uid, f, v, n) for f, v, n in features])
        for call in calls:
            self.call(uid, **call)

    def call(self, uid, *, name="Bash", kind="shell", head=None, status="ok", exit_code=None,
             error_class=None, files=(), approval_wait_ms=None, duration_ms=None, at=None):
        self.calls += 1
        self.db.execute(
            "INSERT INTO tool_call(call_uid, session_uid, name_raw, name, kind, command_head, "
            "files, status, pairing_quality, exit_code, error_class, started_at, duration_ms, "
            "duration_source, duration_quality, approval_wait_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'paired', ?, ?, ?, ?, ?, ?, ?)",
            (f"c{self.calls}", uid, name, name.lower(), kind, head, json.dumps(list(files)),
             status, exit_code, error_class, at if at is not None else T0 + self.calls,
             duration_ms, "reported" if duration_ms is not None else "unknown",
             "reported" if duration_ms is not None else "missing", approval_wait_ms))

    def touch(self, uid):
        self.db.execute("UPDATE session SET ended_at = ended_at + 1 WHERE session_uid = ?", (uid,))

    def delete(self, uid):
        for table in ("tool_call", "session_feature", "session"):
            self.db.execute(f"DELETE FROM {table} WHERE session_uid = ?", (uid,))


def make_catalog(home: Path, items) -> sqlite3.Connection:
    """items: [(item_id, type, agents, status, [(feature, value, weight), …])]."""
    db = sqlite3.connect(home / "catalog.db", isolation_level=None)
    schema = files("orbit_data").joinpath("migrations/catalog/schema.sql").read_text()
    db.executescript(schema)
    for item_id, kind, agents, status, feats in items:
        db.execute("INSERT INTO catalog_item(item_id,type,name,name_key,summary,url,status,agents,language,"
                   "difficulty,official,updated_at,body_policy,latest_version,content_hash,metadata,first_seen,last_seen) "
                   "VALUES (?, ?, ?, ?, '', '', ?, ?, 'en', 1, 0, 0, 'licensed', '1', 'h', '{}', 0, 0)",
                   (item_id, kind, item_id, item_id, status, json.dumps(agents)))
        db.executemany("INSERT INTO item_feature(item_id,feature,value,weight,origin,evidence) "
                       "VALUES (?, ?, ?, ?, 'curated', '')",
                       [(item_id, f, v, w) for f, v, w in feats])
    return db


class Revs:
    def __init__(self):
        self.value = {"data_rev": 1, "inventory_rev": 1}

    def __call__(self):
        return dict(self.value)


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def orbit(home) -> Orbit:
    t = Orbit(home)
    yield t
    t.db.close()


@pytest.fixture
def revs() -> Revs:
    return Revs()


@pytest.fixture
def make_service(home, revs):
    made = []

    def make():
        appdb = AppDB(home / "app.db")
        svc = FeatureService(home, appdb, revs)
        made.append((svc, appdb))
        return svc

    yield make
    for svc, appdb in made:
        svc.close()
        appdb.close()


def seed_basic(t: Orbit) -> None:
    t.session("s1", project="p1", day=0,
              features=[("tool_category", "shell", 3), ("command_head", "git status", 2),
                        ("file_extension", ".py", 4), ("mcp_server", "playwright", 1)],
              calls=[{"head": "git status", "approval_wait_ms": 500},
                     {"head": "rm", "status": "error", "error_class": "Permission Denied"},
                     {"head": "rm", "status": "error"},
                     {"name": "Edit", "kind": "file.edit", "files": ["/w/p1/pyproject.toml"],
                      "duration_ms": 70_000}])
    t.session("s2", project="p1", day=1, agent="codex",
              features=[("tool_category", "shell", 1), ("file_extension", ".ts", 2)],
              calls=[{"head": "pnpm install"}])
    t.session("s3", project="p2", day=2,
              features=[("tool_category", "file.edit", 5), ("skill", "pdf", 2)])


@pytest.fixture
def seeded(orbit) -> Orbit:
    seed_basic(orbit)
    return orbit


@pytest.fixture
def catalog(home):
    made = []

    def make(items):
        db = make_catalog(home, items)
        made.append(db)
        return db

    yield make
    for db in made:
        db.close()
