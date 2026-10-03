"""Synthetic tandem.db + gateway under tmp_path; never touches the real HOME or agent dirs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tandem_data import MAPPER_VERSION, REDUCER_VERSION
from tandem_data.privacy import REDACTION_VERSION
from tandem_data.store import Store

from tandem_backend.services.gateway import Gateway
from tandem_backend.services.supervisor import SupervisorConfig
from tandem_backend.sessionops import exclusion

T0 = 1_760_000_000_000
TOKEN = "synthetic-test-token-0123456789abcdef"
WATERMARK = json.dumps({"projected_revision": 0, "revision": 0, "mapper_version": MAPPER_VERSION,
                        "reducer_version": REDUCER_VERSION, "redaction_version": REDACTION_VERSION})


class Tandem:
    """Raw INSERTs over the real tandem.db schema (foreign keys off), published projection."""

    def __init__(self, home: Path, roots: Path):
        Store(home).db.close()
        self.db = sqlite3.connect(home / "tandem.db", isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = OFF")
        self.roots = roots
        self.n = 0
        for agent in ("claude_code", "codex", "opencode", "pi", "hermes", "dsh", "kimi", "gemini"):
            root = roots / agent
            root.mkdir(parents=True, exist_ok=True)
            self.db.execute("INSERT INTO source VALUES (?, ?, ?, NULL, 1, 0)",
                            (f"src-{agent}", agent, str(root)))
        for project in ("p1", "p2"):
            self.db.execute("INSERT INTO project(project_id, key_type, key, name) "
                            "VALUES (?, 'path', ?, ?)", (project, f"/w/{project}", f"Proj {project}"))
        self.db.execute("INSERT INTO projection_run VALUES (1, 1, ?, ?, 0, 0, 0)",
                        (MAPPER_VERSION, REDUCER_VERSION))

    def session(self, uid, *, agent="claude_code", project="p1", cwd="/w/p1", started=T0,
                status="completed", ended=None, native_id=None):
        self.db.execute(
            "INSERT INTO session(session_uid, source_id, native_id, kind, root_uid, project_id, "
            "cwd, title, started_at, ended_at, status) VALUES (?, ?, ?, 'main', ?, ?, ?, ?, ?, ?, ?)",
            (uid, f"src-{agent}", native_id or f"native-{uid}", uid, project, cwd, f"Title {uid}",
             started, ended if ended is not None else started + 1000, status))

    def event(self, session_uid, *, ts, kind="message.user", attrs=None, text=None, record=None):
        self.n += 1
        uid = f"e{self.n}"
        attrs = {**(attrs or {}), "time": {"quality": "reported", "source_field": "ts"}}
        self.db.execute(
            "INSERT INTO event(event_uid, session_uid, record_uid, native_key, event_path, kind, "
            "actor, seq, ts, call_id, text, attrs, contract_version, mapper_version) "
            "VALUES (?, ?, ?, '[]', '$', ?, 'assistant', ?, ?, ?, ?, ?, 1, 'm')",
            (uid, session_uid, record or f"r-{uid}", kind, self.n, ts, uid, text,
             json.dumps(attrs)))
        return uid

    def call(self, session_uid, *, name="Bash", kind="shell", head=None, status="success",
             at=T0, input=None, files=(), project=None, uid=None):
        event = self.event(session_uid, ts=at, kind="tool.call",
                           attrs={"name": name, "input": input or {}}) if input else None
        self.n += 1
        call_uid = uid or f"c{self.n:06d}"
        self.db.execute(
            "INSERT INTO tool_call(call_uid, session_uid, project_id, call_event_uid, name_raw, "
            "name, kind, command_head, files, status, pairing_quality, started_at, "
            "duration_source, duration_quality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'paired', ?, "
            "'unknown', 'missing')",
            (call_uid, session_uid, project, event, name, name, kind, head,
             json.dumps(list(files)), status, at))
        return call_uid

    def raw_file(self, session_uid, agent, relative_path, *, content=None, ordinal=0):
        file_id = f"f-{agent}-{relative_path}"
        self.db.execute("INSERT OR IGNORE INTO source_file(file_id, source_id, relative_path, role, "
                        "format, watermark) VALUES (?, ?, ?, 'transcript', 'jsonl', ?)",
                        (file_id, f"src-{agent}", relative_path, WATERMARK))
        record = f"rec-{file_id}-{ordinal}"
        self.db.execute("INSERT INTO raw_record(record_uid, file_id, revision_uid, locator, version, "
                        "ordinal, byte_offset, byte_len, sha256, native_type, session_uid) "
                        "VALUES (?, ?, ?, '{}', 1, ?, 0, 1, 'x', 'line', ?)",
                        (record, file_id, f"rev-{file_id}", ordinal, session_uid))
        if content is not None:
            path = self.roots / agent / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return record


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def tandem(home, tmp_path):
    t = Tandem(home, tmp_path / "agents")
    yield t
    t.db.close()


@pytest.fixture
def gateway(home):
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, tick_s=0.05)
    gw = Gateway(home, config=config, discovery=lambda: [], prewarm_debounce_s=3600.0)
    yield gw
    exclusion.set_provider(None)
    gw.platform.close()
    gw.reads.close()
    gw.appdb.close()


@pytest.fixture
def client(gateway):
    # No lifespan: routes only, workers never start.
    return TestClient(gateway.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                      headers={"Authorization": f"Bearer {TOKEN}"})
