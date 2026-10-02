"""Hand-built tandem.db slice for the SQL-fact problem path (no analytics labels, no real HOME).

Column names follow packages/data migrations (001.sql, 005.sql); constraints are dropped so each
row stays short. Five friction groups of six sessions each mirror the parity audit's synthetic
Codex logs: read-only approvals only in permission events, repeated test failures plus a missing
CLI, long unverified edits, compactions, and sessions that touch several top-level directories.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DAY = 86_400_000
T0 = 1_780_000_000_000
GROUP = 6
GROUPS = ("approval", "tests", "edits", "compaction", "mixed")

SCHEMA = """
CREATE TABLE project (project_id TEXT PRIMARY KEY, root_path TEXT);
CREATE TABLE source (source_id TEXT PRIMARY KEY, agent TEXT);
CREATE TABLE session (session_uid TEXT PRIMARY KEY, source_id TEXT, native_id TEXT, kind TEXT,
  root_uid TEXT, project_id TEXT, cwd TEXT, title TEXT, started_at INTEGER, status TEXT);
CREATE TABLE event (event_uid TEXT PRIMARY KEY, session_uid TEXT, kind TEXT, actor TEXT,
  seq INTEGER, ts INTEGER, call_id TEXT, text TEXT, attrs TEXT DEFAULT '{}', ext TEXT DEFAULT '{}');
CREATE TABLE tool_call (call_uid TEXT PRIMARY KEY, session_uid TEXT, call_event_uid TEXT,
  result_event_uid TEXT, name_raw TEXT, name TEXT, kind TEXT, mcp_server TEXT, mcp_tool TEXT,
  skill TEXT, command_head TEXT, files TEXT DEFAULT '[]', status TEXT, exit_code INTEGER,
  error_class TEXT, argument_digest TEXT, started_at INTEGER, approval TEXT);
CREATE TABLE model_call (call_uid TEXT PRIMARY KEY, session_uid TEXT, model_id TEXT,
  effort_raw TEXT, input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER);
CREATE TABLE inventory_scan (scan_id INTEGER PRIMARY KEY, source_key TEXT);
CREATE TABLE inventory_item (scan_id INTEGER, inv_id TEXT, type TEXT, name TEXT,
  config_path TEXT, locator TEXT, enabled INTEGER, evidence TEXT, config TEXT,
  content_hash TEXT);
"""


class FakeStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()


class FakeMemo:
    """Analysis stub: session rows plus an empty bottleneck section (no labels, no signals)."""

    def __init__(self, result: dict):
        self.result = result

    def analysis(self, store, scope, with_text, revision):
        return self.result


class _Session:
    def __init__(self, conn, uid: str, started: int):
        self.conn, self.uid, self.t, self.seq, self.n = conn, uid, started, 0, 0

    def event(self, kind: str, *, text=None, ext=None, attrs=None, call_id=None) -> str:
        self.seq += 1
        self.t += 7_000
        uid = f"{self.uid}-e{self.seq}"
        self.conn.execute("INSERT INTO event (event_uid, session_uid, kind, actor, seq, ts, call_id, "
                          "text, attrs, ext) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (uid, self.uid, kind, "human" if kind == "message.user" else "tool",
                           self.seq, self.t, call_id, text, json.dumps(attrs or {}),
                           json.dumps(ext or {})))
        return uid

    def cmd(self, argv: list[str], *, ok=True, out="ok", approve=False, head=None):
        self.n += 1
        cid = f"{self.uid}-c{self.n}"
        if approve:
            self.event("permission.request", ext={"call_id": cid, "command": argv,
                                                  "type": "exec_approval_request"})
            self.event("permission.decision", ext={"call_id": cid, "decision": "approved",
                                                   "type": "exec_approval_response"})
        call = self.event("tool.call", call_id=cid)
        result = self.event("tool.result", call_id=cid, text=out)
        code = 0 if ok else (127 if "not found" in out else 1)
        self.conn.execute(
            "INSERT INTO tool_call (call_uid, session_uid, call_event_uid, result_event_uid, name_raw, "
            "name, kind, command_head, status, exit_code, argument_digest, started_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, self.uid, call, result, "exec_command", "exec_command", "shell",
             head or " ".join(argv[:2]), "completed" if ok else "failed", code,
             "arguments_" + "_".join(argv), self.t))

    def patch(self, path: str):
        self.n += 1
        cid = f"{self.uid}-p{self.n}"
        change = {path: {"type": "update", "unified_diff": "@@ -1 +1 @@\n-a\n+b\n"}}
        call = self.event("tool.call", call_id=cid, attrs={"input": change})
        result = self.event("tool.result", call_id=cid, ext={"changes": change})
        self.conn.execute(
            "INSERT INTO tool_call (call_uid, session_uid, call_event_uid, result_event_uid, name_raw, "
            "name, kind, status, exit_code, argument_digest, started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, self.uid, call, result, "apply_patch", "apply_patch", "file.edit", "completed", None,
             f"arguments_patch_{self.n}", self.t))


def _write_lines(path: Path, lines: int, line: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line} {k}\n" for k in range(lines)))
    return path


def build(tmp_path: Path) -> tuple[FakeStore, FakeMemo, dict]:
    """Return (store, memo, info) with 30 main sessions spread over 30 days."""
    path = tmp_path / "tandem.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO project VALUES ('p1', '/synthetic/webapp')")
    conn.execute("INSERT INTO source VALUES ('src-codex', 'codex')")
    roots, groups = [], {name: [] for name in GROUPS}
    for i in range(GROUP * len(GROUPS)):
        group = GROUPS[i % len(GROUPS)]
        uid = f"s{i:02d}"
        started = T0 + i * DAY
        conn.execute("INSERT INTO session (session_uid, source_id, native_id, kind, root_uid, "
                     "project_id, cwd, title, started_at, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (uid, "src-codex", uid, "main", uid, "p1", "/synthetic/webapp", group, started,
                      "completed"))
        s = _Session(conn, uid, started)
        s.event("message.user", text=f"{group} task")
        if group == "approval":
            for argv in (["git", "status"], ["ls", "-la"], ["gh", "pr", "view", "12"]):
                s.cmd(argv, approve=True, head=argv[0] if argv[0] == "gh" else None)
        elif group == "tests":
            for _ in range(4):
                s.cmd(["pytest", "tests/test_login.py"], ok=False,
                      out="FAILED tests/test_login.py::test_token - AssertionError", head="pytest")
            for _ in range(2):
                s.cmd(["wrangler", "deploy"], ok=False, out="zsh: command not found: wrangler",
                      head="wrangler")
        elif group == "edits":
            for k in range(12):
                s.patch(f"src/routes/handler_{k}.py")
        elif group == "compaction":
            s.patch("paper/sec3.tex")
            for _ in range(2):
                s.event("context.compaction")
                s.event("message.user", text="压缩之后你忘了约定，我再说一遍")
        else:
            for target in ("src/ui/login.css", "paper/abstract.tex", "infra/cron.yaml"):
                s.patch(target)
        conn.execute("INSERT INTO model_call VALUES (?,?,?,?,?,?,?)",
                     (f"{uid}-m", uid, "gpt-5-codex", "medium", 1000, 200, 0))
        groups[group].append(uid)
        roots.append({"session_uid": uid, "project_id": "p1", "started_at": started,
                      "included_session_uids": [uid]})
    skills = [_write_lines(tmp_path / "skills" / name / "SKILL.md", 400, "Use this skill carefully.")
              for name in ("pdf-tools", "old-helper")]
    agents_md = _write_lines(tmp_path / "AGENTS.md", 261, "- 规则：保持代码风格一致，提交前运行测试。")
    conn.execute("INSERT INTO inventory_scan VALUES (1, 'codex:global')")
    items = [("skill:pdf-tools", "skill", "pdf-tools", skills[0]),
             ("skill:old-helper", "skill", "old-helper", skills[1]),
             ("rule:agents-md", "rule", "AGENTS.md", agents_md),
             ("mcp:figma", "mcp", "figma", tmp_path / "config.toml")]
    for inv_id, type_, name, config_path in items:
        conn.execute("INSERT INTO inventory_item VALUES (1,?,?,?,?,?,NULL,'file','{}',?)",
                     (inv_id, type_, name, str(config_path), name, f"h-{inv_id}"))
    conn.commit()
    conn.close()
    result = {"analysis_digest": "fact-db", "sessions": roots, "tasks": {"records": None},
              "bottleneck_recommendations": {"signals": [], "assessments": [], "recommendations": []}}
    return FakeStore(path), FakeMemo(result), {"groups": groups}
