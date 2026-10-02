"""Disposable trigram index for global search (DT-23): ``home/cache/search.sqlite``.

The canonical ``event_fts`` uses unicode61, which cannot match Chinese substrings. Indexing
every event with trigrams would be too large, so this derived index holds only what people
search for: session titles, human messages (<=2000 chars), command heads and file names.
It is rebuilt from tandem.db (read-only) and can be deleted at any time.
"""

from __future__ import annotations

import os
import posixpath
import sqlite3
import threading
from pathlib import Path

MESSAGE_CHARS = 2000
BATCH = 5000
MAX_LINES = 400
VERSION = "1"

DDL = """
CREATE TABLE IF NOT EXISTS doc_meta (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref TEXT,
  session_uid TEXT, project_id TEXT, agent TEXT, ts INTEGER, title TEXT);
CREATE INDEX IF NOT EXISTS doc_meta_session ON doc_meta(session_uid, kind);
CREATE INDEX IF NOT EXISTS doc_meta_kind_ts ON doc_meta(kind, ts);
CREATE VIRTUAL TABLE IF NOT EXISTS doc USING fts5(text, tokenize='trigram');
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS session_sig (session_uid TEXT PRIMARY KEY, sig TEXT NOT NULL)
  WITHOUT ROWID;
"""

SESSIONS_SQL = """
SELECT s.session_uid, s.title, p.name AS project, s.project_id, src.agent, s.started_at,
  coalesce(s.ended_at,'') || '|' || coalesce(s.title,'') || '|' ||
  (SELECT COUNT(*) FROM tool_call tc WHERE tc.session_uid=s.session_uid) AS sig
FROM session s LEFT JOIN project p ON p.project_id=s.project_id
LEFT JOIN source src ON src.source_id=s.source_id
"""

MESSAGES_SQL = """
SELECT e.rowid, e.event_uid, e.session_uid, substr(e.text,1,2000) AS text, e.ts,
  s.project_id, src.agent, s.title
FROM event e LEFT JOIN session s ON s.session_uid=e.session_uid
LEFT JOIN source src ON src.source_id=s.source_id
WHERE e.kind='message.user' AND e.actor='human' AND e.text IS NOT NULL AND e.text<>''
  AND e.rowid>? ORDER BY e.rowid
"""


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True,
                           isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _file_line(path: str) -> str:
    """``parent/base`` keeps the name searchable without indexing the full private path."""
    path = path.replace("\\", "/").rstrip("/")
    parent = posixpath.basename(posixpath.dirname(path))
    return f"{parent}/{posixpath.basename(path)}" if parent else posixpath.basename(path)


class SearchIndex:
    def __init__(self, home: Path):
        self.path = Path(home) / "cache" / "search.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fresh = not self.path.exists()
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        if fresh:
            os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = NORMAL")
        self.db.execute("PRAGMA cache_size = -65536")
        self.db.executescript(DDL)
        self.lock = threading.Lock()  # single flight for sync()
        self.building = False
        self.local = threading.local()

    # -- reads ---------------------------------------------------------------------------
    def reader(self) -> sqlite3.Connection:
        conn = getattr(self.local, "conn", None)
        if conn is None:
            conn = _open_ro(self.path)
            self.local.conn = conn
        return conn

    def _state(self, db=None) -> dict:
        return dict((db or self.db).execute("SELECT key, value FROM state").fetchall())

    def status(self) -> dict:
        state = self._state(self.reader())
        docs = int(state.get("docs", 0))
        if self.building:
            label = "building"
        else:
            label = "ready" if state.get("run_id") is not None else "empty"
        data_rev = state.get("data_rev")
        return {"state": label, "docs": docs, "data_rev": data_rev}

    # -- writes --------------------------------------------------------------------------
    def sync(self, tandem_db: Path, data_rev=None, *, wait: bool = True) -> dict:
        """Bring the index up to tandem.db; full rebuild when the projection run changed."""
        if not self.lock.acquire(blocking=wait):
            return {"mode": "busy"}
        self.building = True
        try:
            source = _open_ro(tandem_db)
            try:
                return self._sync(source, data_rev)
            finally:
                source.close()
        finally:
            self.building = False
            self.lock.release()

    def _sync(self, t: sqlite3.Connection, data_rev) -> dict:
        state = self._state()
        run = t.execute("SELECT MAX(run_id) FROM projection_run").fetchone()[0]
        max_rowid = t.execute("SELECT MAX(rowid) FROM event").fetchone()[0] or 0
        full = (state.get("version") != VERSION or state.get("run_id") != str(run)
                or max_rowid < int(state.get("max_rowid", 0)))
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            next_id = 1 if full else (db.execute("SELECT MAX(id) FROM doc_meta").fetchone()[0]
                                      or 0) + 1
            if full:
                for table in ("doc_meta", "doc", "session_sig"):
                    db.execute(f"DELETE FROM {table}")
                msg_mark, known = 0, {}
            else:
                msg_mark = int(state.get("msg_rowid", 0))
                known = dict(db.execute("SELECT session_uid, sig FROM session_sig").fetchall())
            sessions = {r["session_uid"]: r for r in t.execute(SESSIONS_SQL)}
            changed = [uid for uid, r in sessions.items() if known.get(uid) != r["sig"]]
            gone = [uid for uid in known if uid not in sessions]
            for uid in changed + gone:
                if uid in known:
                    db.execute("DELETE FROM doc WHERE rowid IN (SELECT id FROM doc_meta WHERE "
                               "session_uid=? AND kind<>'message')", (uid,))
                    db.execute("DELETE FROM doc_meta WHERE session_uid=? AND kind<>'message'",
                               (uid,))
            db.executemany("DELETE FROM session_sig WHERE session_uid=?", [(u,) for u in gone])

            rows: list[tuple] = []

            def add(kind, ref, uid, text, ts, title):
                nonlocal next_id
                meta = sessions.get(uid)
                rows.append((next_id, kind, ref, uid, meta["project_id"] if meta else None,
                             meta["agent"] if meta else None, ts, title, text))
                next_id += 1
                if len(rows) >= BATCH:
                    flush()

            def flush():
                db.executemany("INSERT INTO doc_meta VALUES (?,?,?,?,?,?,?,?)",
                               [r[:8] for r in rows])
                db.executemany("INSERT INTO doc(rowid, text) VALUES (?,?)",
                               [(r[0], r[8]) for r in rows])
                rows.clear()

            for uid in changed:
                r = sessions[uid]
                text = " ".join(x for x in (r["title"], r["project"]) if x)
                if text:
                    add("session", uid, uid, text, r["started_at"], r["title"])
            # Commands and files: one doc per session each (lines joined by newline) keeps
            # the index ~4x smaller; the matching line becomes the hit's ref at query time.
            if changed:
                selected = None if full else changed
                for kind, sql, render in (
                        ("command", "SELECT DISTINCT session_uid, command_head FROM tool_call "
                                    "WHERE command_head IS NOT NULL", str),
                        ("file", "SELECT DISTINCT tc.session_uid, j.value FROM tool_call tc, "
                                 "json_each(tc.files) j WHERE j.type='text'", _file_line)):
                    grouped: dict[str, list[str]] = {}
                    for uid, value in self._distinct(t, sql, selected):
                        lines = grouped.setdefault(uid, [])
                        if len(lines) < MAX_LINES:
                            lines.append(render(value))
                    for uid, lines in grouped.items():
                        meta = sessions.get(uid)
                        add(kind, uid, uid, "\n".join(lines),
                            meta["started_at"] if meta else None, meta["title"] if meta else None)
            last = msg_mark
            for m in t.execute(MESSAGES_SQL, (msg_mark,)):
                add("message", m["event_uid"], m["session_uid"], m["text"], m["ts"], m["title"])
                last = m["rowid"]
            flush()
            db.executemany("INSERT OR REPLACE INTO session_sig VALUES (?,?)",
                           [(uid, sessions[uid]["sig"]) for uid in changed])
            docs = db.execute("SELECT COUNT(*) FROM doc_meta").fetchone()[0]
            db.executemany("INSERT OR REPLACE INTO state VALUES (?,?)", [
                ("version", VERSION), ("run_id", str(run)), ("max_rowid", str(max_rowid)),
                ("msg_rowid", str(last)), ("data_rev", None if data_rev is None else str(data_rev)),
                ("docs", str(docs))])
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return {"mode": "full" if full else "incremental", "sessions": len(changed),
                "messages_from": msg_mark, "docs": docs}

    @staticmethod
    def _distinct(t, sql, sessions):
        if sessions is None:
            yield from t.execute(sql)
            return
        for start in range(0, len(sessions), 500):
            chunk = sessions[start:start + 500]
            where = " AND " if " WHERE " in sql else " WHERE "
            column = "tc.session_uid" if " tc," in sql else "session_uid"
            yield from t.execute(f"{sql}{where}{column} IN ({','.join('?' * len(chunk))})", chunk)

    def close(self) -> None:
        self.db.close()


_indexes: dict[Path, SearchIndex] = {}
_indexes_lock = threading.Lock()


def get_index(home: Path) -> SearchIndex:
    key = Path(home).resolve()
    with _indexes_lock:
        index = _indexes.get(key)
        if index is None or not index.path.exists():
            index = _indexes[key] = SearchIndex(key)
        return index
