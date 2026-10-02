"""Thin SQL over ``app.db`` for install plans, the append-only ledger and install state.

Writes go through ``appdb.write()`` (one serialized writer), reads through ``appdb.read()``.
Functions taking ``db`` run inside a caller's transaction so several rows commit together.
"""

from __future__ import annotations

import itertools
import json
import secrets
import sqlite3
import time

ACTIVE_STATES = ("installed", "observing", "kept")
LEDGER_COLUMNS = ("entry_id", "ts", "actor", "action", "install_id", "candidate_id", "plan_id",
                  "target_idx", "target_agent", "path", "op", "before_hash", "after_hash",
                  "backup_path", "created_file", "applied", "blob_ref", "evidence_refs",
                  "tracking_id", "note")
STATE_COLUMNS = ("install_id", "plan_id", "candidate_id", "source_type", "source_id", "title",
                 "kind", "agents", "scope", "preview_digest", "state", "installed_at",
                 "observe_until", "last_triggered_at", "pinned", "archived_at", "reverted_at",
                 "tracking_id", "risk_level")
_SEQ = itertools.count()  # orders rows written within the same millisecond
_JSON = {"applied", "evidence_refs", "agents", "spec", "targets", "warnings"}


def now_ms() -> int:
    return int(time.time() * 1000)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key in _JSON & out.keys():
        if isinstance(out[key], str):
            try:
                out[key] = json.loads(out[key])
            except ValueError:
                pass
    return out


# ---- plans ------------------------------------------------------------------------------------

def save_plan(appdb, plan: dict) -> None:
    with appdb.write() as db:
        db.execute(
            "INSERT INTO install_plan (plan_id, source_type, source_id, spec, spec_hash, targets, agents, "
            "scope, project_path, status, warnings, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(plan_id) DO UPDATE SET spec=excluded.spec, targets=excluded.targets, "
            "status=excluded.status, warnings=excluded.warnings, created_at=excluded.created_at",
            (plan["plan_id"], plan["source_type"], plan.get("source_id"), dumps(plan["spec"]),
             plan["spec_hash"], dumps(plan["targets"]), dumps(plan["agents"]), plan["scope"],
             plan.get("project_path"), plan.get("status", "ready"), dumps(plan.get("warnings") or []),
             plan.get("created_at") or now_ms()))


def get_plan(appdb, plan_id: str) -> dict | None:
    with appdb.read() as db:
        return _row(db.execute("SELECT * FROM install_plan WHERE plan_id = ?", (plan_id,)).fetchone())


def sweep_plans(appdb, older_than_days: int = 30) -> int:
    """Drop old plans no install refers to; plans are cheap to rebuild."""
    cutoff = now_ms() - older_than_days * 86_400_000
    with appdb.write() as db:
        return db.execute("DELETE FROM install_plan WHERE created_at < ? AND plan_id NOT IN "
                          "(SELECT plan_id FROM install_state)", (cutoff,)).rowcount


# ---- ledger -----------------------------------------------------------------------------------

def entry_id(ts: int) -> str:
    return f"le_{ts:013d}_{next(_SEQ) % 10**8:08d}{secrets.token_hex(2)}"


def ledger_append(db: sqlite3.Connection, entries: list[dict]) -> list[str]:
    """Insert several ledger rows inside the caller's write transaction."""
    ids = []
    for entry in entries:
        row = dict(entry)
        row.setdefault("ts", now_ms())
        row.setdefault("entry_id", entry_id(row["ts"]))
        for key in ("applied", "evidence_refs"):
            if row.get(key) is not None and not isinstance(row[key], str):
                row[key] = dumps(row[key])
        if isinstance(row.get("created_file"), bool):
            row["created_file"] = int(row["created_file"])
        db.execute(f"INSERT INTO install_ledger ({','.join(LEDGER_COLUMNS)}) VALUES "
                   f"({','.join('?' * len(LEDGER_COLUMNS))})", [row.get(c) for c in LEDGER_COLUMNS])
        ids.append(row["entry_id"])
    return ids


def ledger_for(appdb, install_id: str) -> list[dict]:
    with appdb.read() as db:
        rows = db.execute("SELECT * FROM install_ledger WHERE install_id = ? ORDER BY ts, entry_id",
                          (install_id,)).fetchall()
    return [_row(r) for r in rows]


def ledger_page(appdb, install_id: str | None = None, limit: int = 50,
                before_ts: int | None = None) -> list[dict]:
    with appdb.read() as db:
        rows = db.execute(
            "SELECT * FROM install_ledger WHERE (?1 IS NULL OR install_id = ?1) AND (?2 IS NULL OR ts < ?2) "
            "ORDER BY ts DESC, entry_id DESC LIMIT ?3", (install_id, before_ts, limit)).fetchall()
    return [_row(r) for r in rows]


def open_begins(appdb) -> list[str]:
    """Install ids with ``install_begin`` but neither ``install`` nor ``install_failed``."""
    with appdb.read() as db:
        rows = db.execute(
            "SELECT DISTINCT install_id FROM install_ledger b WHERE action = 'install_begin' AND NOT EXISTS "
            "(SELECT 1 FROM install_ledger e WHERE e.install_id = b.install_id "
            "AND e.action IN ('install', 'install_failed'))").fetchall()
    return [r[0] for r in rows]


# ---- state ------------------------------------------------------------------------------------

def state_put(db: sqlite3.Connection, state: dict) -> None:
    row = dict(state)
    if not isinstance(row.get("agents"), str):
        row["agents"] = dumps(row.get("agents") or [])
    row.setdefault("pinned", 0)
    db.execute(f"INSERT OR REPLACE INTO install_state ({','.join(STATE_COLUMNS)}) VALUES "
               f"({','.join('?' * len(STATE_COLUMNS))})", [row.get(c) for c in STATE_COLUMNS])


def state_update(db: sqlite3.Connection, install_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE install_state SET {sets} WHERE install_id = ?", (*fields.values(), install_id))


def state_get(appdb, install_id: str) -> dict | None:
    with appdb.read() as db:
        return _row(db.execute("SELECT * FROM install_state WHERE install_id = ?", (install_id,)).fetchone())


def state_list(appdb, state: str | None = None, limit: int = 500) -> list[dict]:
    with appdb.read() as db:
        rows = db.execute("SELECT * FROM install_state WHERE (?1 IS NULL OR state = ?1) "
                          "ORDER BY installed_at DESC LIMIT ?2", (state, limit)).fetchall()
    return [_row(r) for r in rows]


def find_active(appdb, source_type: str, source_id: str | None) -> dict | None:
    if source_id is None:
        return None
    with appdb.read() as db:
        row = db.execute(
            f"SELECT * FROM install_state WHERE source_type = ? AND source_id = ? AND state IN "
            f"({','.join('?' * len(ACTIVE_STATES))}) ORDER BY installed_at DESC LIMIT 1",
            (source_type, source_id, *ACTIVE_STATES)).fetchone()
    return _row(row)


def find_by_digest(appdb, plan_id: str, digest: str) -> dict | None:
    with appdb.read() as db:
        row = db.execute("SELECT * FROM install_state WHERE plan_id = ? AND preview_digest = ? "
                         "AND state != 'reverted' ORDER BY installed_at DESC LIMIT 1",
                         (plan_id, digest)).fetchone()
    return _row(row)
