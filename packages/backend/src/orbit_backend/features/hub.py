"""QueryHub: thread-local read-only connections over app.db with orbit.db (``t``) and
catalog.db (``c``) attached, plus a small pool to run independent queries in parallel.

Writes never go through here; they use ``AppDB.write()``.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ATTACH = (("t", "orbit.db"), ("c", "catalog.db"))


class QueryHub:
    def __init__(self, home: Path, app_db_path: Path, workers: int = 4):
        self.home = Path(home)
        self.app_db = Path(app_db_path)
        self.local = threading.local()
        self.lock = threading.Lock()
        self.conns: list[sqlite3.Connection] = []
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="feat-hub")

    def conn(self) -> sqlite3.Connection:
        db = getattr(self.local, "db", None)
        if db is None:
            db = sqlite3.connect(self.app_db.resolve().as_uri() + "?mode=ro", uri=True,
                                 check_same_thread=False, isolation_level=None)
            db.row_factory = sqlite3.Row
            for pragma in ("query_only = ON", "mmap_size = 268435456", "cache_size = -32768",
                           "busy_timeout = 5000"):
                db.execute(f"PRAGMA {pragma}")
            self.local.db, self.local.attached = db, set()
            with self.lock:
                self.conns.append(db)
        attached: set = self.local.attached
        for alias, name in ATTACH:
            path = self.home / name
            if alias not in attached and not db.in_transaction and path.is_file():
                db.execute(f"ATTACH DATABASE ? AS {alias}",
                           (path.resolve().as_uri() + "?mode=ro",))
                attached.add(alias)
        return db

    def attached(self) -> set:
        self.conn()
        return set(self.local.attached)

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        db = self.conn()
        db.execute("BEGIN")
        try:
            yield db
        finally:
            db.rollback()

    def has(self, schema: str, table: str) -> bool:
        db = self.conn()
        if schema != "main" and schema not in self.local.attached:
            return False
        row = db.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name = ? "
                         "AND type IN ('table','view')", (table,)).fetchone()
        return row is not None

    def submit(self, fn: Callable[[sqlite3.Connection], Any]) -> Future:
        def run():
            with self.read() as db:
                return fn(db)
        return self.pool.submit(run)

    def gather(self, timeout: float | None = None, **calls) -> dict:
        """Run independent ``fn(conn)`` calls in parallel; errors come back as values."""
        futures = {name: self.submit(fn) for name, fn in calls.items()}
        wait_futures(futures.values(), timeout=timeout)
        out: dict = {}
        for name, future in futures.items():
            if not future.done():
                future.cancel()
                out[name] = TimeoutError(name)
            elif future.exception() is not None:
                out[name] = future.exception()
            else:
                out[name] = future.result()
        return out

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            for db in self.conns:
                try:
                    db.close()
                except sqlite3.ProgrammingError:
                    pass
            self.conns.clear()
