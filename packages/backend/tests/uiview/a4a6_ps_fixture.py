"""Synthetic orbit.db / app.db builder for the A5/A6 uiview adapters (tmp_path only).

Raw INSERTs over the real migrated schema with foreign keys off; never touches a real HOME.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from orbit_data.store import Store

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_760_000_000_000  # 2025-10-09T08:53:20Z


class Orbit:
    def __init__(self, home: Path):
        Store(home).db.close()
        self.path = home / "orbit.db"
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = OFF")
        self.events = 0
        self.calls = 0
        self.seq: dict[str, int] = {}
        for agent in ("claude_code", "codex"):
            self.db.execute("INSERT OR IGNORE INTO source VALUES (?, ?, ?, NULL, 1, 0)",
                            (f"src-{agent}", agent, f"/tmp/{agent}"))

    def project(self, pid, *, name=None, key_type="path", key=None, git=None, paths=()):
        self.db.execute("INSERT OR REPLACE INTO project(project_id,key_type,key,name,git_remote,paths) "
                        "VALUES (?,?,?,?,?,?)", (pid, key_type, key or f"/w/{pid}", name or pid, git,
                                                 json.dumps(list(paths) or [key or f"/w/{pid}"])))

    def session(self, uid, *, project="p1", agent="claude_code", start=T0, minutes=30,
                ended=True, cwd=None, git=None, kind="main", root=None):
        end = start + minutes * MIN if ended else None
        self.db.execute(
            "INSERT OR REPLACE INTO session(session_uid, source_id, native_id, kind, root_uid, "
            "project_id, cwd, git_remote, started_at, ended_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, f"src-{agent}", uid, kind, root or uid, project,
             cwd if cwd is not None else f"/w/{project}", git, start, end))
        self.seq.setdefault(uid, 0)
        return uid

    def event(self, uid, kind, *, ts=None, text=None, actor="human", origin=None, attrs=None):
        self.events += 1
        seq = self.seq[uid]
        self.seq[uid] = seq + 1
        a = {"time": {"quality": "reported", "source_field": "ts"} if ts is not None
             else {"quality": "missing"}}
        if origin:
            a["origin"] = origin
        a.update(attrs or {})
        eid = f"e{self.events}"
        self.db.execute(
            "INSERT INTO event(event_uid, session_uid, record_uid, native_key, event_path, kind, actor, "
            "seq, ts, text, attrs, contract_version, mapper_version) "
            "VALUES (?,?,?,'[]','$',?,?,?,?,?,?,1,'t')",
            (eid, uid, f"r{self.events}", kind, actor, seq, ts, text, json.dumps(a)))
        project = self.db.execute("SELECT project_id, cwd FROM session WHERE session_uid=?",
                                  (uid,)).fetchone()
        self.db.execute("INSERT INTO event_context(event_uid, project_id, cwd) VALUES (?,?,?)",
                        (eid, project[0] if project else None, project[1] if project else None))
        return eid

    def human(self, uid, text, *, ts=None):
        return self.event(uid, "message.user", ts=ts, text=text, actor="human", origin="human")

    def call(self, uid, *, name="Bash", kind="shell", head=None, status="ok", files=(),
             approval=None, ts=None):
        eid = self.event(uid, "tool.call", ts=ts, actor="assistant")
        self.calls += 1
        self.db.execute(
            "INSERT INTO tool_call(call_uid, session_uid, call_event_uid, name_raw, name, kind, "
            "command_head, files, status, pairing_quality, started_at, duration_source, "
            "duration_quality, approval) VALUES (?,?,?,?,?,?,?,?,?,'paired',?,'unknown','missing',?)",
            (f"c{self.calls}", uid, eid, name, name.lower(), kind, head, json.dumps(list(files)),
             status, ts, approval))
        return eid

    def inventory(self, items, *, agent="claude_code", project=None, scope="project"):
        """items: [(type, name, config_path, config_dict)]."""
        cur = self.db.execute(
            "INSERT INTO inventory_scan(source_key,agent,root_path,scope,project_id,observed_at,"
            "scanner_version,coverage,diagnostics) VALUES (?,?,?,?,?,?, 't','{}','[]')",
            (f"{agent}:{project}", agent, "/tmp", scope, project, T0))
        for i, (kind, name, path, config) in enumerate(items):
            self.db.execute("INSERT INTO inventory_item VALUES (?,?,?,?,?,?,1,'file',?,?)",
                            (cur.lastrowid, f"inv{cur.lastrowid}-{i}", kind, name, path, name,
                             json.dumps(config), f"h{cur.lastrowid}-{i}"))

    def close(self):
        self.db.close()


def ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
