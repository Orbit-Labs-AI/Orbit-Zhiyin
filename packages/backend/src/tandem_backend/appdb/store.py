"""``app.db``: WAL, one serialized writer, per-thread ``mode=ro`` readers."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

APPLICATION_ID = 0x54415050  # TAPP; refuses tandem.db / catalog.db by mistake.


class AppDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.Lock()
        self.local = threading.local()
        self.readers: list[sqlite3.Connection] = []
        fresh = not self.path.exists()
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if fresh:
            os.chmod(self.path, 0o600)
            self.db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        elif self.db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            self.db.close()
            raise ValueError(f"{self.path} is not a Tandem app.db")
        for pragma in ("journal_mode = WAL", "synchronous = NORMAL", "foreign_keys = ON",
                       "busy_timeout = 5000", "temp_store = MEMORY"):
            self.db.execute(f"PRAGMA {pragma}")
        self._apply_schemas()

    def _apply_schemas(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS module_schema (module TEXT PRIMARY KEY, "
                        "sha256 TEXT NOT NULL, applied_at INTEGER NOT NULL) STRICT")
        applied = dict(self.db.execute("SELECT module, sha256 FROM module_schema").fetchall())
        root = files("tandem_backend.appdb").joinpath("schema")
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            if not entry.name.endswith(".sql"):
                continue
            sql = entry.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode()).hexdigest()
            module = entry.name.removesuffix(".sql")
            if applied.get(module) == digest:
                continue
            with self.write() as db:
                for statement in _statements(sql):
                    db.execute(statement)
                db.execute("INSERT INTO module_schema VALUES (?, ?, ?) ON CONFLICT(module) DO "
                           "UPDATE SET sha256 = excluded.sha256, applied_at = excluded.applied_at",
                           (module, digest, int(time.time() * 1000)))

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One transaction at a time across threads; rolls back on error."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Snapshot read on a per-thread query-only connection; never waits for the writer."""
        connection = getattr(self.local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True,
                                         check_same_thread=False, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            self.local.connection = connection
            with self.lock:
                self.readers.append(connection)
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.rollback()

    def close(self) -> None:
        with self.lock:
            for connection in self.readers:
                connection.close()
            self.readers.clear()
            self.db.close()


def _statements(sql: str) -> Iterator[str]:
    """Split a schema file into complete statements (handles triggers' inner semicolons)."""
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                yield buffer
            buffer = ""
    if buffer.strip():
        raise ValueError(f"Incomplete SQL statement: {buffer[:80]!r}")
