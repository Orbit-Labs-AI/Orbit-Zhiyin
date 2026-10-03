"""Synthetic orbit.db + gateway for the A4–A6 adapters; tmp HOME only, never real agent dirs.

``Orbit`` follows tests/sessionops/conftest.Orbit (raw INSERTs, foreign keys off) and adds
the tool_call columns the adapters read: error_class, approval, approval_wait_ms,
argument_digest, duration, mcp_server, sub-agent sessions and tool.result text.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orbit_data import MAPPER_VERSION, REDUCER_VERSION
from orbit_data.store import Store

from orbit_backend.services import routes_sessionops, routes_uiview_a4a6
from orbit_backend.services.gateway import Gateway, install_error_handlers
from orbit_backend.services.supervisor import SupervisorConfig
from orbit_backend.sessionops import exclusion
from orbit_backend.uiview import a4a6_common

T0 = 1_760_000_000_000
HOUR = 3_600_000
DAY = 86_400_000


class Orbit:
    def __init__(self, home: Path):
        Store(home).db.close()
        self.db = sqlite3.connect(home / "orbit.db", isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = OFF")
        self.n = 0
        for agent in ("claude_code", "codex"):
            self.db.execute("INSERT INTO source VALUES (?, ?, ?, NULL, 1, 0)",
                            (f"src-{agent}", agent, f"/agents/{agent}"))
        for project in ("p1", "p2"):
            self.db.execute("INSERT INTO project(project_id, key_type, key, name) "
                            "VALUES (?, 'path', ?, ?)", (project, f"/w/{project}", f"Proj {project}"))
        self.db.execute("INSERT INTO projection_run VALUES (1, 1, ?, ?, 0, 0, 0)",
                        (MAPPER_VERSION, REDUCER_VERSION))

    def session(self, uid, *, agent="claude_code", project="p1", started=T0, status="completed",
                ended=None, kind="main", parent=None):
        root = parent if kind != "main" and parent else uid
        self.db.execute(
            "INSERT INTO session(session_uid, source_id, native_id, kind, parent_uid, root_uid, "
            "project_id, cwd, title, started_at, ended_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, f"src-{agent}", f"native-{uid}", kind, parent, root, project, f"/w/{project}",
             f"Title {uid}", started, ended if ended is not None else started + 60_000, status))

    def event(self, session_uid, *, ts, kind, attrs=None, text=None, seq=None):
        self.n += 1
        uid = f"e{self.n}"
        attrs = {**(attrs or {}), "time": {"quality": "reported", "source_field": "ts"}}
        self.db.execute(
            "INSERT INTO event(event_uid, session_uid, record_uid, native_key, event_path, kind, "
            "actor, seq, ts, call_id, text, attrs, contract_version, mapper_version) "
            "VALUES (?, ?, ?, '[]', '$', ?, 'assistant', ?, ?, ?, ?, ?, 1, 'm')",
            (uid, session_uid, f"r-{uid}", kind, self.n if seq is None else seq, ts, uid, text,
             json.dumps(attrs)))
        return uid

    def call(self, session_uid, *, name="Bash", kind="shell", head=None, status="success",
             at=T0, project=None, uid=None, mcp_server=None, error_class=None, approval=None,
             wait=None, digest=None, duration=None, quality="reported", result=None,
             command=None, seq=None, no_event=False, event_uid=None):
        # Two calls sharing one event (one message with parallel calls) share its seq.
        event = event_uid if no_event or event_uid else self.event(
            session_uid, ts=at, kind="tool.call", seq=seq,
            attrs={"name": name, "input": {"command": command} if command else {}})
        result_uid = self.event(session_uid, ts=at + 1, kind="tool.result", text=result) \
            if result is not None else None
        self.n += 1
        call_uid = uid or f"c{self.n:06d}"
        self.db.execute(
            "INSERT INTO tool_call(call_uid, session_uid, project_id, call_event_uid, "
            "result_event_uid, name_raw, name, kind, mcp_server, command_head, status, "
            "pairing_quality, error_class, argument_digest, started_at, duration_ms, "
            "duration_source, duration_quality, approval, approval_wait_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'paired', ?, ?, ?, ?, ?, ?, ?, ?)",
            (call_uid, session_uid, project, event, result_uid, name, name, kind, mcp_server,
             head, status, error_class, digest, at, duration,
             "reported" if duration is not None else "unknown",
             quality if duration is not None else "missing", approval, wait))
        return call_uid


CYCLE = (("Read", "file.read", None), ("Grep", "search", None), ("Edit", "file.edit", None),
         ("Bash", "shell", "npm"), ("mcp__pw__click", "mcp", None), ("Bash", "shell", "ls"),
         ("Task", "subagent", None))


def build_standard(t: Orbit) -> dict:
    """40 main sessions / 566 calls: 30 claude_code (ok/failed), 10 codex (unknown status,
    approvals on shell), one MCP server ``pw``; three sub-agents of s00, one interrupted."""
    calls = 0
    for i in range(40):
        uid = f"s{i:02d}"
        agent = "claude_code" if i < 30 else "codex"
        start = T0 + i * HOUR
        t.session(uid, agent=agent, project="p1" if i % 2 == 0 else "p2", started=start)
        for j in range(15 if i < 6 else 14):
            name, kind, head = CYCLE[(i + j) % len(CYCLE)]
            if agent == "codex":
                status = "unknown"
            else:
                status = "failed" if (i + j) % 9 == 0 else "success"
            shell = kind == "shell"
            t.call(uid, name=name, kind=kind, head=head, status=status, at=start + j * 1000,
                   mcp_server="pw" if kind == "mcp" else None, duration=100 + j * 10,
                   approval="approved" if agent == "codex" and shell else None,
                   wait=2000 + 1000 * j if agent == "codex" and shell else None,
                   result="bash: npm: command not found" if status == "failed" else None)
            calls += 1
    for k in range(3):
        t.session(f"sub{k}", kind="subagent", parent="s00", started=T0 + 1000 * k,
                  status="interrupted" if k == 0 else "completed")
    return {"sessions": 40, "calls": calls}


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def orbit(home):
    t = Orbit(home)
    yield t
    t.db.close()


@pytest.fixture
def conn(orbit):
    orbit.db.row_factory = sqlite3.Row
    return orbit.db


@pytest.fixture
def gateway(home, orbit):
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, tick_s=0.05)
    gw = Gateway(home, config=config, discovery=lambda: [], prewarm_debounce_s=3600.0)
    a4a6_common.CACHE.items.clear()
    yield gw
    exclusion.set_provider(None)
    gw.platform.close()
    gw.reads.close()
    gw.appdb.close()


@pytest.fixture
def client(gateway):
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_sessionops.router(gateway))
    app.include_router(routes_uiview_a4a6.router(gateway))
    return TestClient(app, base_url="http://127.0.0.1:8765")
