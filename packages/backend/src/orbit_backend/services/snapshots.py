"""Analysis snapshots keyed by (section, scope_hash, data_rev, inventory_rev, rules_digest).

Two disposable tiers: an in-memory LRU (64 MB by default) and ``cache/ui.sqlite`` with
gzip bodies so the first screen after a restart is immediate. Each (section, scope_hash)
keeps its newest two versions on disk; a total byte cap evicts least recently used rows.
The truth stays in orbit.db and analysis.sqlite; dropping this cache only costs time.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from ..platform.telemetry import record

MB = 1024 * 1024


def scope_hash(scope: dict, params: dict | None = None) -> str:
    """Stable digest of a normalized scope; list order is not meaningful."""
    normalized = {k: sorted(v) if isinstance(v, list) else v for k, v in scope.items()}
    payload = json.dumps({"scope": normalized, "params": params or {}}, sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class SnapshotKey:
    section: str
    scope_hash: str
    data_rev: int
    inventory_rev: int
    rules: str


@dataclass
class Snapshot:
    key: SnapshotKey
    body: dict
    computed_at: int
    duration_ms: int
    size: int = field(default=0)


class SnapshotStore:
    def __init__(self, path: Path | None, *, memory_bytes: int = 64 * MB,
                 disk_bytes: int = 512 * MB, keep: int = 2):
        self.memory_bytes, self.disk_bytes, self.keep = memory_bytes, disk_bytes, keep
        self.memory: OrderedDict[SnapshotKey, Snapshot] = OrderedDict()
        self.memory_used = 0
        self.lock = threading.RLock()
        self.path = path
        self.db: sqlite3.Connection | None = None
        if path is not None:
            self._open_disk()

    def _open_disk(self) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.db = self._connect()
        except sqlite3.DatabaseError:
            # Disposable cache: a corrupt file is replaced instead of failing reads.
            self.path.unlink(missing_ok=True)
            self.db = self._connect()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS snapshot (section TEXT NOT NULL, scope_hash TEXT NOT NULL,"
            " data_rev INTEGER NOT NULL, inventory_rev INTEGER NOT NULL, rules TEXT NOT NULL,"
            " computed_at INTEGER NOT NULL, duration_ms INTEGER NOT NULL,"
            " accessed_at INTEGER NOT NULL, size INTEGER NOT NULL, body BLOB NOT NULL,"
            " PRIMARY KEY(section, scope_hash, data_rev, inventory_rev, rules))")
        db.execute("SELECT count(*) FROM snapshot").fetchone()  # Detect corruption early.
        return db

    # -- memory tier ---------------------------------------------------------------
    def _remember(self, snapshot: Snapshot) -> None:
        old = self.memory.pop(snapshot.key, None)
        if old is not None:
            self.memory_used -= old.size
        if snapshot.size > self.memory_bytes:
            return  # Larger than the whole tier: serve from disk only.
        self.memory[snapshot.key] = snapshot
        self.memory_used += snapshot.size
        while self.memory_used > self.memory_bytes and self.memory:
            _, evicted = self.memory.popitem(last=False)
            self.memory_used -= evicted.size

    # -- public API -------------------------------------------------------------------
    def put(self, key: SnapshotKey, body: dict, *, duration_ms: int = 0,
            computed_at: int | None = None) -> Snapshot:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str).encode()
        snapshot = Snapshot(key, body, computed_at or int(time.time() * 1000), duration_ms,
                            len(raw))
        if duration_ms:
            record("analysis.duration", duration_ms, section=key.section)
        with self.lock:
            self._remember(snapshot)
            if self.db is not None:
                packed = gzip.compress(raw, compresslevel=5)
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    self.db.execute(
                        "INSERT OR REPLACE INTO snapshot VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (key.section, key.scope_hash, key.data_rev, key.inventory_rev, key.rules,
                         snapshot.computed_at, duration_ms, snapshot.computed_at, len(packed),
                         packed))
                    self.db.execute(
                        "DELETE FROM snapshot WHERE section=? AND scope_hash=? AND rowid NOT IN ("
                        " SELECT rowid FROM snapshot WHERE section=? AND scope_hash=?"
                        " ORDER BY computed_at DESC, data_rev DESC LIMIT ?)",
                        (key.section, key.scope_hash, key.section, key.scope_hash, self.keep))
                    self._enforce_disk_cap()
                    self.db.execute("COMMIT")
                except sqlite3.Error:
                    self.db.execute("ROLLBACK")
                    raise
            # Memory follows the same per-key retention as disk.
            versions = [k for k in self.memory
                        if (k.section, k.scope_hash) == (key.section, key.scope_hash)]
            versions.sort(key=lambda k: self.memory[k].computed_at)
            for stale in versions[:-self.keep]:
                self.memory_used -= self.memory.pop(stale).size
        return snapshot

    def _enforce_disk_cap(self) -> None:
        assert self.db is not None
        total = self.db.execute("SELECT COALESCE(SUM(size),0) FROM snapshot").fetchone()[0]
        if total <= self.disk_bytes:
            return
        for rowid, size in self.db.execute(
                "SELECT rowid,size FROM snapshot ORDER BY accessed_at, computed_at").fetchall():
            if total <= self.disk_bytes:
                break
            self.db.execute("DELETE FROM snapshot WHERE rowid=?", (rowid,))
            total -= size

    def _load(self, where: str, params: tuple) -> Snapshot | None:
        if self.db is None:
            return None
        row = self.db.execute(
            "SELECT section,scope_hash,data_rev,inventory_rev,rules,computed_at,duration_ms,body"
            f" FROM snapshot WHERE {where} ORDER BY computed_at DESC, data_rev DESC LIMIT 1",
            params).fetchone()
        if row is None:
            return None
        try:
            raw = gzip.decompress(row[7])
            body = json.loads(raw)
        except (OSError, ValueError):
            return None
        snapshot = Snapshot(SnapshotKey(*row[:5]), body, row[5], row[6], len(raw))
        self.db.execute(
            "UPDATE snapshot SET accessed_at=? WHERE section=? AND scope_hash=? AND data_rev=?"
            " AND inventory_rev=? AND rules=?", (int(time.time() * 1000), *row[:5]))
        self._remember(snapshot)
        return snapshot

    def get(self, key: SnapshotKey) -> Snapshot | None:
        with self.lock:
            snapshot = self.memory.get(key)
            if snapshot is not None:
                self.memory.move_to_end(key)
            else:
                snapshot = self._load(
                    "section=? AND scope_hash=? AND data_rev=? AND inventory_rev=? AND rules=?",
                    (key.section, key.scope_hash, key.data_rev, key.inventory_rev, key.rules))
        record("cache.snapshot", 1, result="miss" if snapshot is None else "hit")
        return snapshot

    def latest(self, section: str, scope_hash_: str, rules: str) -> Snapshot | None:
        """Newest version of the same section and scope, at any data revision."""
        with self.lock:
            candidates = [s for k, s in self.memory.items()
                          if (k.section, k.scope_hash, k.rules) == (section, scope_hash_, rules)]
            best = max(candidates, key=lambda s: (s.computed_at, s.key.data_rev), default=None)
            disk = self._load("section=? AND scope_hash=? AND rules=?",
                              (section, scope_hash_, rules)) if best is None else None
        found = best or disk
        record("cache.snapshot", 1, result="miss" if found is None else "hit")
        return found

    def stats(self) -> dict:
        with self.lock:
            memory = {"memory_bytes": self.memory_used, "memory_rows": len(self.memory)}
            if self.db is None:
                return {**memory, "disk_bytes": 0, "rows": 0}
            rows, size = self.db.execute(
                "SELECT count(*), COALESCE(SUM(size),0) FROM snapshot").fetchone()
        return {**memory, "disk_bytes": size, "rows": rows}

    def compact(self) -> dict:
        """Maintenance: enforce the byte cap, truncate the WAL, optimize; VACUUM if mostly
        free pages in a large file."""
        with self.lock:
            if self.db is None:
                return {"skipped": True}
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._enforce_disk_cap()
                self.db.execute("COMMIT")
            except sqlite3.Error:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.execute("PRAGMA optimize")
            pages = self.db.execute("PRAGMA page_count").fetchone()[0]
            free = self.db.execute("PRAGMA freelist_count").fetchone()[0]
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            vacuumed = pages * page_size > 64 * MB and free > pages / 2
            if vacuumed:
                self.db.execute("VACUUM")
        return {"pages": pages, "free_pages": free, "vacuumed": vacuumed}

    def close(self) -> None:
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None
