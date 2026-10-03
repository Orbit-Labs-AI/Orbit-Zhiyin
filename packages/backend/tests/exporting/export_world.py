"""Export test helpers: synthetic orbit.db from the real migrations, tmp app.db and a fake gateway for export."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orbit_backend.appdb import AppDB
from orbit_backend.services import routes_export
from orbit_backend.services.gateway import Revisions, install_error_handlers

MIGRATIONS = Path(__file__).parents[3] / "data" / "src" / "orbit_data" / "migrations"
T0 = 1_780_000_000_000
FAKE_SECRET = "sk-test0123456789abcdefXYZ"


def migration_columns() -> dict[str, set[str]]:
    db = sqlite3.connect(":memory:")
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9].sql")):
        db.executescript(path.read_text())
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {t: {r[1] for r in db.execute(f"PRAGMA table_info({t})")} for t in tables}


class World:
    def __init__(self, home: Path):
        from orbit_data.query import MAPPER_VERSION, REDUCER_VERSION

        self.home = home
        self.path = home / "orbit.db"
        from orbit_data.store import Store

        # The real Store applies every migration and stamps schema_version / user_version
        # (raw migration files alone leave the manifest at the last version a file stamps).
        Store(home).db.close()
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("INSERT INTO projection_run VALUES (1, 1, ?, ?, 0, 0, 0)",
                        (MAPPER_VERSION, REDUCER_VERSION))
        self.db.executemany("INSERT INTO source (source_id, agent, root_path, discovered_at) "
                            "VALUES (?, ?, ?, 0)", [("src-c", "claude_code", "/r/c"),
                                                    ("src-x", "codex", "/r/x")])
        self.seq = 0

    def session(self, uid, *, source="src-c", project=None, title=None, started_at=T0):
        self.db.execute("INSERT INTO session (session_uid, source_id, native_id, kind, root_uid,"
                        " project_id, title, started_at, ended_at, status) VALUES "
                        "(?, ?, ?, 'main', ?, ?, ?, ?, ?, 'completed')",
                        (uid, source, uid, uid, project, title, started_at, started_at + 60_000))

    def event(self, session, text) -> str:
        self.seq += 1
        uid = f"ev{self.seq}"
        self.db.execute("INSERT INTO event (event_uid, session_uid, record_uid, native_key, "
                        "event_path, kind, actor, seq, ts, text, attrs, contract_version, "
                        "mapper_version) VALUES (?, ?, 'r', '[]', '$', 'tool.call', 'assistant',"
                        " ?, NULL, ?, ?, 1, 'm')",
                        (uid, session, self.seq, text,
                         json.dumps({"time": {"quality": "missing"}})))
        return uid

    def tool_calls(self, session, rows):
        """rows: (call_uid, name, command_head, status, started_at, call_event_uid)."""
        self.db.executemany(
            "INSERT INTO tool_call (call_uid, session_uid, project_id, call_event_uid, name_raw,"
            " name, kind, command_head, status, pairing_quality, exit_code, started_at,"
            " duration_ms, duration_source, duration_quality) VALUES (?, ?, NULL, ?, ?, ?, "
            "'builtin', ?, ?, 'paired', NULL, ?, 5, 'reported', 'reported')",
            [(c, session, ev, n, n, cmd, st, ts) for c, n, cmd, st, ts, ev in rows])

    def model_call(self, uid, session, model, ts, tokens):
        self.db.execute("INSERT INTO model_call (call_uid, session_uid, usage_event_uid, "
                        "model_id, model_resolution, coverage, input_tokens, output_tokens, "
                        "cost_usd, ts) VALUES (?, ?, ?, ?, 'exact', 'full', ?, ?, 0.5, ?)",
                        (uid, session, f"u-{uid}", model, tokens, tokens // 2, ts))


def fake_gateway(home: Path, *, data_rev=None) -> SimpleNamespace:
    revisions = Revisions()
    revisions.update(data_rev=data_rev)
    return SimpleNamespace(home=home, appdb=AppDB(home / "app.db"), revisions=revisions,
                           reads=SimpleNamespace(path=home / "orbit.db"))


def client_for(gw) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_export.router(gw))
    return TestClient(app)
