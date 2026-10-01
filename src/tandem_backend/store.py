"""One local SQLite ledger. Reimporting a file replaces it atomically."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .importers.codex import metadata_index, parse_rollout
from .models import Event, ImportSummary, ParsedSession, stable_id

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, project TEXT NOT NULL,
    model TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL,
    timestamp TEXT, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, ordinal);
CREATE TABLE IF NOT EXISTS imports (
    source_file TEXT PRIMARY KEY, signature TEXT NOT NULL, session_id TEXT,
    warnings TEXT NOT NULL, policy TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def remove_source(self, source_file: str) -> None:
        """Fail closed when an import policy excludes previously admitted evidence."""
        with self.connect() as conn:
            row = conn.execute("SELECT session_id FROM imports WHERE source_file=?", (source_file,)).fetchone()
            if row and row[0]:
                conn.execute("DELETE FROM sessions WHERE id=? AND json_extract(data,'$.source_file')=?",
                             (row[0], source_file))
            conn.execute("DELETE FROM imports WHERE source_file=?", (source_file,))

    def save(self, parsed: ParsedSession, signature: str, policy: str) -> None:
        session = parsed.session
        if not session:
            return
        with self.connect() as conn:
            previous = conn.execute("SELECT session_id FROM imports WHERE source_file=?", (session.source_file,)).fetchone()
            if previous and previous[0] != session.id:
                conn.execute("DELETE FROM sessions WHERE id=? AND json_extract(data,'$.source_file')=?",
                             (previous[0], session.source_file))
            conn.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)",
                         (session.id, session.project_id, session.project, session.model,
                          json.dumps(asdict(session), ensure_ascii=False)))
            # SQLite REPLACE deletes the old row and cascades old events; the transaction is atomic.
            conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", [
                (e.id, e.session_id, e.ordinal, e.kind, e.model, e.timestamp,
                 json.dumps(e.to_dict(), ensure_ascii=False)) for e in parsed.events
            ])
            conn.execute("INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?)",
                         (session.source_file, signature, session.id,
                          json.dumps(parsed.warnings), policy))
            # Archiving/restoring is a move, not another independent source owner.
            conn.execute("DELETE FROM imports WHERE session_id=? AND source_file<>?",
                         (session.id, session.source_file))

    def sessions(self, project_id: str | None = None) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT data FROM sessions" + (" WHERE project_id=?" if project_id else ""),
                                (project_id,) if project_id else ()).fetchall()
        return [json.loads(row[0]) for row in rows]

    def events(self, project_id: str | None = None, model: str | None = None,
               session_id: str | None = None) -> list[Event]:
        clauses, params = [], []
        for column, value in (("s.project_id", project_id), ("e.model", model), ("e.session_id", session_id)):
            if value:
                clauses.append(column + "=?")
                params.append(value)
        query = "SELECT e.data FROM events e JOIN sessions s ON s.id=e.session_id"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY e.session_id,e.ordinal"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Event(**json.loads(row[0])) for row in rows]

    def counts(self) -> dict:
        with self.connect() as conn:
            return {"sessions": conn.execute("SELECT count(*) FROM sessions").fetchone()[0],
                    "events": conn.execute("SELECT count(*) FROM events").fetchone()[0],
                    "projects": conn.execute("SELECT count(distinct project_id) FROM sessions").fetchone()[0]}


def import_codex(store: Store, codex_home: Path, before: str | None = None,
                 exclude_sessions: set[str] | None = None) -> ImportSummary:
    if not codex_home.is_dir():
        raise ValueError("Codex 数据目录不存在")
    summary = ImportSummary()
    metadata = metadata_index(codex_home)
    policy = json.dumps({"before": before, "exclude": sorted(exclude_sessions or []), "parser": 7})
    paths = sorted({p.resolve() for folder in ("sessions", "archived_sessions")
                    for p in (codex_home / folder).rglob("*.jsonl")})
    for path in paths:
        summary.files_seen += 1
        stat = path.stat()
        file_signature = f"{stat.st_size}:{stat.st_mtime_ns}"
        with store.connect() as conn:
            old = conn.execute("SELECT i.signature,i.policy,json_extract(s.data,'$.source_file'),i.session_id "
                               "FROM imports i LEFT JOIN sessions s ON s.id=i.session_id WHERE i.source_file=?",
                               (str(path),)).fetchone()
        md = metadata.get(old[3], {}) if old else {}
        signature = file_signature + ":" + stable_id(json.dumps(md, sort_keys=True))
        if old and old[0] == signature and old[1] == policy and old[2] == str(path):
            summary.unchanged += 1
            continue
        parsed = parse_rollout(path, metadata, before, exclude_sessions)
        summary.warning_count += len(parsed.warnings)
        if parsed.skipped_reason:
            store.remove_source(str(path))
            summary.skipped += 1
            reason = parsed.skipped_reason
            summary.skip_reasons[reason] = summary.skip_reasons.get(reason, 0) + 1
            continue
        signature = file_signature + ":" + stable_id(json.dumps(metadata.get(parsed.session.id, {}), sort_keys=True))
        store.save(parsed, signature, policy)
        summary.imported += 1
        summary.events += len(parsed.events)
    # Remove vanished sources only within the explicitly imported home. A moved
    # file's old mapping was cleared by save(), so it cannot erase the new owner.
    with store.connect() as conn:
        known_sources = [row[0] for row in conn.execute("SELECT source_file FROM imports")]
    source_roots = [(codex_home / folder).resolve() for folder in ("sessions", "archived_sessions")]
    for known in known_sources:
        candidate = Path(known)
        if any(candidate.is_relative_to(root) for root in source_roots) and candidate not in paths:
            store.remove_source(known)
    return summary
