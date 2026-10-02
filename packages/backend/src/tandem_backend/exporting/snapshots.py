"""report_snapshot in app.db: frozen report / share-card payloads (AN-14 v1)."""

from __future__ import annotations

import json
import time
import uuid

KINDS = ("report", "share_card", "persona_fixed", "rec_top")
KEEP = 50


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def save(appdb, kind: str, scope: dict, scope_hash: str, payload: dict,
         rules_digest: str | None = None, *, now_ms: int | None = None) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown snapshot kind {kind}")
    snapshot_id = uuid.uuid4().hex
    created = now_ms if now_ms is not None else int(time.time() * 1000)
    with appdb.write() as db:
        db.execute("INSERT INTO report_snapshot VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (snapshot_id, kind, scope_hash, _json(scope), created, rules_digest,
                    _json(payload)))
        db.execute("DELETE FROM report_snapshot WHERE kind = ? AND snapshot_id NOT IN ("
                   "SELECT snapshot_id FROM report_snapshot WHERE kind = ? "
                   "ORDER BY created_at DESC, rowid DESC LIMIT ?)", (kind, kind, KEEP))
    return snapshot_id


def summary(kind: str, payload: dict) -> str:
    if kind == "report":
        ready = sum(s.get("status") == "ok" for s in payload.get("sections") or [])
        return f"{len(payload.get('sections') or [])} 个章节，{ready} 个可用"
    if kind == "share_card":
        return f"{payload.get('code') or '—'} {payload.get('type_name') or ''}".strip()
    return kind


def list_(appdb, kind: str | None = None, limit: int = 20) -> list[dict]:
    sql = "SELECT snapshot_id, kind, scope_hash, created_at, payload FROM report_snapshot"
    params: list = []
    if kind:
        sql += " WHERE kind = ?"
        params.append(kind)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    with appdb.read() as db:
        rows = db.execute(sql, [*params, limit]).fetchall()
    return [{"snapshot_id": r[0], "kind": r[1], "scope_hash": r[2], "created_at": r[3],
             "summary": summary(r[1], json.loads(r[4]))} for r in rows]


def get(appdb, snapshot_id: str) -> dict | None:
    with appdb.read() as db:
        row = db.execute("SELECT snapshot_id, kind, scope_hash, scope, created_at, rules_digest,"
                         " payload FROM report_snapshot WHERE snapshot_id = ?",
                         (snapshot_id,)).fetchone()
    if row is None:
        return None
    return {"snapshot_id": row[0], "kind": row[1], "scope_hash": row[2],
            "scope": json.loads(row[3]), "created_at": row[4], "rules_digest": row[5],
            "payload": json.loads(row[6])}


def delete(appdb, snapshot_id: str) -> bool:
    with appdb.write() as db:
        return db.execute("DELETE FROM report_snapshot WHERE snapshot_id = ?",
                          (snapshot_id,)).rowcount > 0
