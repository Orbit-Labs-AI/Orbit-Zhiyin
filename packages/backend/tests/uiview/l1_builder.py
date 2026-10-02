"""Synthetic tandem.db for uiview session tests: raw INSERTs over the real schema (foreign keys
off) under tmp_path. Never reads a real HOME, agent directory or app data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tandem_data import MAPPER_VERSION, REDUCER_VERSION
from tandem_data.store import Store

from tandem_backend.services.gateway import Gateway, install_error_handlers
from tandem_backend.services.supervisor import SupervisorConfig
from tandem_backend.sessionops import exclusion
from tandem_backend.uiview import routes_sessions

# Star-imported by the test modules (fixtures only); helpers are imported by name.
__all__ = ["client", "gateway", "home", "l1"]

T0 = 1_760_000_000_000  # 2025-10-09T08:53:20Z
MIN = 60_000
DAY = 86_400_000


class L1:
    def __init__(self, home: Path):
        Store(home).db.close()
        self.db = sqlite3.connect(home / "tandem.db", isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = OFF")
        self.seq: dict[str, int] = {}
        self.n = 0
        for agent in ("claude_code", "codex"):
            self.db.execute("INSERT INTO source VALUES (?, ?, ?, NULL, 1, 0)",
                            (f"src-{agent}", agent, f"/synthetic/{agent}"))
        for project in ("p1", "p2"):
            self.db.execute("INSERT INTO project(project_id, key_type, key, name) "
                            "VALUES (?, 'path', ?, ?)", (project, f"/w/{project}", f"Proj {project}"))
        self.db.execute("INSERT INTO projection_run VALUES (1, 1, ?, ?, 0, 0, 0)",
                        (MAPPER_VERSION, REDUCER_VERSION))

    def session(self, uid, *, agent="claude_code", project="p1", started=T0, title=None,
                status="completed", kind="main", root=None, parent=None, ended=None):
        self.db.execute(
            "INSERT INTO session(session_uid, source_id, native_id, kind, parent_uid, root_uid, "
            "project_id, cwd, title, started_at, ended_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, f"src-{agent}", f"native-{uid}", kind, parent, root or uid, project,
             f"/w/{project}", title, started, ended, status))

    def event(self, session_uid, ts, kind, actor="assistant", text=None, attrs=None):
        self.n += 1
        seq = self.seq.get(session_uid, -1) + 1
        self.seq[session_uid] = seq
        uid = f"{session_uid}-e{seq}"
        attrs = {**(attrs or {}), "time": {"quality": "reported", "source_field": "ts"}}
        self.db.execute(
            "INSERT INTO event(event_uid, session_uid, record_uid, native_key, event_path, kind, "
            "actor, seq, ts, text, attrs, contract_version, mapper_version) "
            "VALUES (?, ?, ?, '[]', '$', ?, ?, ?, ?, ?, ?, 1, 'm')",
            (uid, session_uid, f"r-{uid}", kind, actor, seq, ts, text, json.dumps(attrs)))
        return uid

    def user(self, session_uid, ts, text):
        return self.event(session_uid, ts, "message.user", "human", text, {"origin": "human"})

    def reply(self, session_uid, ts, final=False):
        return self.event(session_uid, ts, "message.assistant",
                          attrs={"phase": "final"} if final else {})

    def compaction(self, session_uid, ts):
        return self.event(session_uid, ts, "context.compaction", "harness")

    def call(self, session_uid, ts, *, name="Bash", kind="shell", head=None, status="success",
             exit_code=None, error_class=None, duration_ms=None):
        event = self.event(session_uid, ts, "tool.call", attrs={"name": name})
        uid = f"call-{event}"
        self.db.execute(
            "INSERT INTO tool_call(call_uid, session_uid, call_event_uid, name_raw, name, kind, "
            "command_head, status, pairing_quality, exit_code, error_class, started_at, "
            "duration_ms, duration_source, duration_quality) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'paired', ?, ?, ?, ?, ?, ?)",
            (uid, session_uid, event, name, name, kind, head, status, exit_code, error_class, ts,
             duration_ms, "reported" if duration_ms is not None else "unknown",
             "reported" if duration_ms is not None else "missing"))
        return uid

    def model(self, session_uid, ts, model="claude-opus-4-5", inp=1000, cread=0, cwrite=0,
              out=100, effort=None):
        event = self.event(session_uid, ts, "model.usage", attrs={
            "usage_scope": "call", "measurement": "delta", "request_key": [ts]})
        self.db.execute(
            "INSERT INTO model_call(call_uid, session_uid, usage_event_uid, provider, model_raw, "
            "model_id, model_resolution, effort_raw, coverage, input_tokens, cache_read_tokens, "
            "cache_write_tokens, output_tokens, ts) "
            "VALUES (?, ?, ?, 'p', ?, ?, 'resolved', ?, 'full', ?, ?, ?, ?, ?)",
            (f"m-{event}", session_uid, event, model, model, effort, inp, cread, cwrite, out, ts))

    def turn(self, session_uid, idx, status, first_event):
        self.db.execute(
            "INSERT INTO turn(turn_uid, session_uid, idx, trigger, boundary_source, status, "
            "first_event_uid, last_event_uid) VALUES (?, ?, ?, 'human', 'derived', ?, ?, ?)",
            (f"{session_uid}-t{idx}", session_uid, idx, status, first_event, first_event))


def handwritten_cc(l1: L1, uid="cc-fix", started=T0, project="p1"):
    """Claude Code session: 3 human messages (2 lexical corrections), 7 tool calls with a
    3x identical failure streak, 1 compaction, a passing test command and two model calls."""
    t = lambda m: started + int(m * MIN)  # noqa: E731
    l1.session(uid, started=started, project=project, title="部署站点到 Cloudflare")
    first = l1.user(uid, t(0), "把站点部署到 Cloudflare，并验证 HTTPS")
    l1.reply(uid, t(0.5))
    l1.model(uid, t(0.6), inp=50_000, cread=10_000, cwrite=0, out=800, effort="high")
    l1.call(uid, t(1), name="Read", kind="file.read", duration_ms=2000)
    l1.call(uid, t(1.5), name="Grep", kind="search")
    l1.call(uid, t(3), name="Edit", kind="file.edit")
    l1.user(uid, t(5), "不对，用 Cloudflare 不要用 Vercel")
    for m in (6, 6.5, 7):
        l1.call(uid, t(m), head="wrangler deploy", status="failed", exit_code=1,
                error_class="auth_error")
    l1.compaction(uid, t(8))
    l1.user(uid, t(9), "请重新登录后再部署 /Users/alice/secret-proj/x.txt")
    l1.call(uid, t(10), head="wrangler deploy", status="success", exit_code=0)
    l1.model(uid, t(10.5), inp=150_000, cread=0, cwrite=0, out=900, effort="high")
    l1.call(uid, t(11), head="pnpm test", status="success", exit_code=0)
    l1.reply(uid, t(12), final=True)
    l1.turn(uid, 0, "completed", first)
    return uid


def codex_unknown(l1: L1, uid="cx-1", started=T0 - DAY, project="p2"):
    """Codex session whose tool statuses are unknown and with no usage rows."""
    l1.session(uid, agent="codex", started=started, project=project, title=None,
               status="unknown")
    l1.user(uid, started, "重构 data loader 模块")
    l1.call(uid, started + MIN, head="ls", status="unknown")
    l1.call(uid, started + 2 * MIN, head="cat x", status="unknown")
    l1.reply(uid, started + 3 * MIN, final=True)
    return uid


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def l1(home):
    builder = L1(home)
    yield builder
    builder.db.close()


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
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_sessions.router(gateway))
    return TestClient(app)
