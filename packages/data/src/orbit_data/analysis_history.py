"""Append-only execution records, checksummed snapshots and reusable derived caches.

v2 adds materialized session rows (``session_result``), per-section results
(``analysis_section`` / ``analysis_row``) and persisted exclusions. All of them are derived
from orbit.db and can be deleted at any time; they are verified before every read.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
import zlib
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

Record = dict[str, Any]
SCHEMA_VERSION = 3
KEEP_INPUTS = 3
# A real home's window (sections + session rows) is several hundred MB; 512 MB evicted the
# result of the computation that had just stored it. Retention keeps it bounded instead.
MAX_BYTES = 3 * 1024 * 1024 * 1024
FAILED_RETENTION_MS = 30 * 24 * 3600 * 1000
# Completed runs keep their full result snapshot (often 100+ MB on a real home); only the
# newest few per request survive retention. The section cache serves reads, not runs.
KEEP_RUNS_PER_REQUEST = 2
KEEP_RUNS = 20
# Waits for another writer (a concurrent analysis publishing a large result) before
# "database is locked"; each write transaction is short, so this is generous.
LOCK_TIMEOUT_S = 60.0
# Optional observer ``(run_id, active)`` for every execution this process starts and
# finishes. The analysis worker forwards it to the supervisor, which fails the runs a
# killed worker left ``running`` (SIGKILL skips every ``except``).
RUN_OBSERVER = None


def _observe(run_id: str, active: bool) -> None:
    observer = RUN_OBSERVER
    if observer is not None:
        try:
            observer(run_id, active)
        except Exception:  # noqa: BLE001  observation never breaks an analysis
            pass


CHUNK_DEPTH = 2  # container levels split into separate json.dumps calls by _encode


def _json_pieces(value: Any, depth: int):
    """Yield strings whose concatenation equals ``_json(value, sort_keys=False)``.

    Only dicts with string keys and lists are split (their compact JSON is the members'
    JSON joined by ``,`` / ``:``); everything else is one ``json.dumps``."""
    if depth > 0 and isinstance(value, list) and value:
        yield "["
        for index, item in enumerate(value):
            if index:
                yield ","
            yield from _json_pieces(item, depth - 1)
        yield "]"
    elif depth > 0 and isinstance(value, dict) and value and all(isinstance(k, str) for k in value):
        yield "{"
        for index, (key, item) in enumerate(value.items()):
            yield ("," if index else "") + _json(key) + ":"
            yield from _json_pieces(item, depth - 1)
        yield "}"
    else:
        yield _json(value, sort_keys=False)


class AnalysisIntegrityError(ValueError):
    """A stored payload failed decompression or its checksum; never served silently."""


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _now() -> int:
    return time.time_ns() // 1_000_000


def _json(value: Any, *, sort_keys: bool = True) -> str:
    """Reject NaN or unsupported values; requests sort keys for stable identities.

    Result payloads keep their insertion order (``sort_keys=False``) so a cached result
    serializes to the same bytes as the freshly computed one.
    """
    return json.dumps(
        value, ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":"), allow_nan=False
    )


def _statements(script: str) -> list[str]:
    """Split a migration into complete statements; comments may contain semicolons."""
    statements, buffer = [], ""
    for line in script.splitlines():
        if line.lstrip().startswith("--"):
            continue
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError("Incomplete analysis migration statement")
    return statements


class AnalysisHistory:
    """Use a connection per operation so API threads never share a SQLite handle."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            current = connection.execute("PRAGMA user_version").fetchone()[0]
        if current != SCHEMA_VERSION:
            self._migrate()

    def _migrate(self) -> None:
        """Upgrade in place under a write lock; v1 runs and snapshots stay readable."""
        connection = sqlite3.connect(self.path, timeout=LOCK_TIMEOUT_S, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                connection.execute("ROLLBACK")
                raise ValueError("Unsupported analysis history schema")
            folder = files("orbit_data").joinpath("migrations/analysis")
            for step in range(version + 1, SCHEMA_VERSION + 1):
                for statement in _statements(folder.joinpath(f"{step:03d}.sql").read_text()):
                    connection.execute(statement)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @contextmanager
    def connect(self):
        """Bound lock waits and enforce references for every short transaction."""
        connection = sqlite3.connect(self.path, timeout=LOCK_TIMEOUT_S)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def start(
        self,
        engine: str,
        request: Record,
        *,
        request_key: str | None = None,
        input_fp: str | None = None,
    ) -> str:
        """Create an execution even when an identical analysis has previously completed."""
        self.recover_interrupted()
        run_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO analysis_run(run_id,engine,status,started_at,request_json,request_key,input_fp,owner_pid)"
                " VALUES(?,?,'running',?,?,?,?,?)",
                (run_id, engine, _now(), _json(request), request_key, input_fp, os.getpid()),
            )
        _observe(run_id, True)
        return run_id

    def cached_run(self, engine: str, request_key: str, input_fp: str) -> Record | None:
        """Find the latest completed execution that answered the same request and input."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_run WHERE engine=? AND request_key=? AND input_fp=?"
                " AND status='completed' ORDER BY started_at DESC,rowid DESC LIMIT 1",
                (engine, request_key, input_fp),
            ).fetchone()
        return self._run(row) if row else None

    def record_hit(
        self, engine: str, request: Record, *, request_key: str, input_fp: str, snapshot_id: str
    ) -> str:
        """Log a cache hit as a light completed run that reuses an existing snapshot."""
        run_id, now = uuid.uuid4().hex, _now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO analysis_run(run_id,engine,status,started_at,finished_at,request_json,"
                "snapshot_id,request_key,input_fp,cache_hit) VALUES(?,?,'completed',?,?,?,?,?,?,1)",
                (run_id, engine, now, now, _json(request), snapshot_id, request_key, input_fp),
            )
        return run_id

    def recover_interrupted(self) -> int:
        """Fail running rows whose owner process is gone (a worker killed on timeout)."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT run_id,owner_pid FROM analysis_run WHERE status='running'"
            ).fetchall()
            stale = [row["run_id"] for row in rows if not _alive(row["owner_pid"])]
            now = time.time_ns() // 1_000_000
            for run_id in stale:
                connection.execute(
                    "UPDATE analysis_run SET status='failed',finished_at=?,error_type='Interrupted',"
                    "error_message='analysis process exited before finishing' "
                    "WHERE run_id=? AND status='running'",
                    (now, run_id),
                )
        return len(stale)

    def reuse(self, engine: str, request: Record) -> tuple[str, Record] | None:
        """Record a completed run backed by the newest identical request's verified snapshot."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT run_id,snapshot_id FROM analysis_run WHERE engine=? AND status='completed' "
                "AND request_json=? ORDER BY started_at DESC,rowid DESC LIMIT 1",
                (engine, _json(request)),
            ).fetchone()
        if row is None:
            return None
        try:
            result = self.result(row["run_id"])
        except (KeyError, ValueError):
            return None  # Pruned or corrupt: recompute instead of serving it.
        now = time.time_ns() // 1_000_000
        run_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO analysis_run(run_id,engine,status,started_at,finished_at,request_json,snapshot_id,owner_pid) "
                "SELECT ?,?,'completed',?,?,?,snapshot_id,? FROM analysis_snapshot WHERE snapshot_id=?",
                (run_id, engine, now, now, _json(request), os.getpid(), row["snapshot_id"]),
            )
        return run_id, result

    def complete(self, run_id: str, result: Record) -> str:
        """Atomically publish the complete result and finish exactly one running execution."""
        data = _json(result, sort_keys=False).encode("utf-8")
        snapshot_id = hashlib.sha256(data).hexdigest()
        # Compress before taking the write lock: a 150 MB result must not hold it.
        packed = zlib.compress(data)
        now = time.time_ns() // 1_000_000
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM analysis_run WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None or row["status"] != "running":
                raise ValueError("Only a running analysis can be completed")
            connection.execute(
                "INSERT OR IGNORE INTO analysis_snapshot VALUES(?,?,?,?,?,?)",
                (
                    snapshot_id,
                    result.get("analysis_digest"),
                    result.get("schema_version", result.get("feature_schema_version")),
                    len(data),
                    packed,
                    now,
                ),
            )
            connection.execute(
                "UPDATE analysis_run SET status='completed',finished_at=?,snapshot_id=? WHERE run_id=?",
                (now, snapshot_id, run_id),
            )
        _observe(run_id, False)
        return snapshot_id

    def fail(self, run_id: str, error: BaseException) -> None:
        """Record calculation failures; completed snapshots are never overwritten."""
        with self.connect() as connection:
            changed = connection.execute(
                "UPDATE analysis_run SET status='failed',finished_at=?,error_type=?,error_message=? WHERE run_id=? AND status='running'",
                (time.time_ns() // 1_000_000, type(error).__name__, str(error)[:2000], run_id),
            ).rowcount
            if changed != 1:
                raise ValueError("Only a running analysis can be failed")
        _observe(run_id, False)

    def fail_stale(self, *, older_than_ms: int, reason: str, now: int | None = None) -> int:
        """Fail ``running`` executions started before ``now - older_than_ms`` (their
        process is gone: a crash or a supervisor kill). Returns the number failed."""
        now = _now() if now is None else now
        with self.connect() as connection:
            return connection.execute(
                "UPDATE analysis_run SET status='failed',finished_at=?,error_type=?,"
                "error_message=? WHERE status='running' AND started_at < ?",
                (now, "WorkerTerminated", reason[:2000], now - older_than_ms),
            ).rowcount

    def fail_runs(self, run_ids, reason: str) -> int:
        """Fail the given executions if they are still ``running``."""
        ids = list(run_ids)
        if not ids:
            return 0
        now = _now()
        with self.connect() as connection:
            return connection.execute(
                "UPDATE analysis_run SET status='failed',finished_at=?,error_type=?,"
                f"error_message=? WHERE status='running' AND run_id IN ({','.join('?' * len(ids))})",
                (now, "WorkerTerminated", reason[:2000], *ids),
            ).rowcount

    def list_runs(
        self,
        *,
        engine: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Record:
        """Page execution metadata without decompressing results or exposing arbitrary SQL."""
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("limit must be 1–200 and offset nonnegative")
        conditions, parameters = [], []
        for name, value in (("engine", engine), ("status", status)):
            if value is not None:
                conditions.append(f"{name}=?")
                parameters.append(value)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connect() as connection:
            total = connection.execute(
                "SELECT count(*) FROM analysis_run" + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM analysis_run"
                + where
                + " ORDER BY started_at DESC,rowid DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self._run(row) for row in rows],
        }

    @staticmethod
    def _run(row: sqlite3.Row) -> Record:
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        return result

    def get_run(self, run_id: str) -> Record | None:
        """Fetch an execution's inputs, timestamps, status and immutable snapshot identity."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_run WHERE run_id=?", (run_id,)
            ).fetchone()
        return self._run(row) if row else None

    def result(self, run_id: str) -> Record:
        """Verify the full stored result before decoding it; corruption is never hidden."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT s.* FROM analysis_snapshot s JOIN analysis_run r USING(snapshot_id) WHERE r.run_id=? AND r.status='completed'",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Completed analysis not found")
        try:
            data = zlib.decompress(row["payload"])
        except zlib.error as error:
            raise AnalysisIntegrityError("Analysis snapshot is corrupt") from error
        if len(data) != row["json_bytes"] or hashlib.sha256(data).hexdigest() != row["snapshot_id"]:
            raise AnalysisIntegrityError("Analysis snapshot checksum mismatch")
        return json.loads(data)

    def records(self, run_id: str, pointer: str, *, offset: int = 0, limit: int = 100) -> Record:
        """Page any stored result array using an RFC 6901 JSON pointer, without truncating storage."""
        if not pointer.startswith("/") or offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("Use an absolute JSON pointer, offset >= 0 and limit 1–1000")
        value = self.result(run_id)
        try:
            for part in pointer[1:].split("/"):
                key = part.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (KeyError, ValueError, IndexError, TypeError) as error:
            raise KeyError("Analysis record path not found") from error
        if not isinstance(value, list):
            raise ValueError("The selected record path must be an array")
        return {
            "run_id": run_id,
            "pointer": pointer,
            "total": len(value),
            "offset": offset,
            "limit": limit,
            "items": value[offset : offset + limit],
        }

    # ---- v2 derived caches -------------------------------------------------------------

    @staticmethod
    def _encode(value: Any) -> tuple[bytes, int, str]:
        """(zlib payload, JSON bytes, sha256) of ``_json(value, sort_keys=False)``.

        Large dicts and lists are encoded piece by piece into one compressor, producing
        the same bytes as a single ``json.dumps`` without ever holding the whole document
        (a real home's bottleneck_features section is several hundred MB of JSON, held
        once as str and once as bytes before)."""
        compressor, sha = zlib.compressobj(1), hashlib.sha256()
        parts: list[bytes] = []
        size = 0
        for piece in _json_pieces(value, CHUNK_DEPTH):
            data = piece.encode("utf-8")
            size += len(data)
            sha.update(data)
            parts.append(compressor.compress(data))
        parts.append(compressor.flush())
        return b"".join(parts), size, sha.hexdigest()

    @staticmethod
    def _decode(payload: bytes, json_bytes: int, sha256: str, what: str) -> Any:
        """Verify before decoding; a damaged cache entry is an error, never a silent miss."""
        try:
            data = zlib.decompress(payload)
        except zlib.error as error:
            raise AnalysisIntegrityError(f"Analysis {what} is corrupt") from error
        if len(data) != json_bytes or hashlib.sha256(data).hexdigest() != sha256:
            raise AnalysisIntegrityError(f"Analysis {what} checksum mismatch")
        return json.loads(data)

    def session_results(
        self, scope_class: str, algo_version: str, wanted: dict[str, str]
    ) -> dict[str, Any]:
        """Return stored rows whose tree fingerprint still matches; others are misses."""
        if not wanted:
            return {}
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM session_result WHERE scope_class=? AND algo_version=?"
                " AND root_session_uid IN (SELECT value FROM json_each(?))",
                (scope_class, algo_version, json.dumps(sorted(wanted))),
            ).fetchall()
        return {
            row["root_session_uid"]: self._decode(
                row["payload"], row["json_bytes"], row["sha256"], "session result"
            )
            for row in rows
            if wanted.get(row["root_session_uid"]) == row["tree_fp"]
        }

    def put_session_results(
        self, scope_class: str, algo_version: str, items: dict[str, tuple[str, Any]]
    ) -> None:
        """Replace rows for these roots and drop their rows from older algorithm versions."""
        if not items:
            return
        now = _now()
        values = []
        for root, (tree_fp, value) in items.items():
            payload, size, sha = self._encode(value)
            values.append((root, scope_class, algo_version, tree_fp, payload, size, sha, now))
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO session_result VALUES(?,?,?,?,?,?,?,?)", values
            )
            connection.execute(
                "DELETE FROM session_result WHERE algo_version<>?"
                " AND root_session_uid IN (SELECT value FROM json_each(?))",
                (algo_version, json.dumps(sorted(items))),
            )

    def sections(self, request_key: str, input_fp: str, names: list[str]) -> dict[str, Any]:
        """Read cached sections individually; hits refresh their LRU timestamp."""
        if not names:
            return {}
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_section WHERE request_key=? AND input_fp=?"
                " AND section IN (SELECT value FROM json_each(?))",
                (request_key, input_fp, json.dumps(sorted(set(names)))),
            ).fetchall()
            found = {
                row["section"]: self._decode(
                    row["payload"], row["json_bytes"], row["sha256"], "section"
                )
                for row in rows
            }
            if found:
                connection.execute(
                    "UPDATE analysis_section SET last_hit_at=?,hits=hits+1 WHERE request_key=?"
                    " AND input_fp=? AND section IN (SELECT value FROM json_each(?))",
                    (_now(), request_key, input_fp, json.dumps(sorted(found))),
                )
        return found

    def put_sections(
        self,
        request_key: str,
        input_fp: str,
        values: dict[str, Any],
        rows: dict[str, list[tuple[str | None, Any]]] | None = None,
    ) -> dict[str, int]:
        """Publish sections and their paged rows atomically; readers never see half a section.

        Returns the JSON bytes stored per section (its rows included)."""
        rows = rows or {}
        if set(rows) - set(values):
            raise ValueError("Rows require their section in the same publish")
        now = _now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sizes: dict[str, int] = {}
            for name, value in values.items():
                payload, size, sha = self._encode(value)
                sizes[name] = size
                # Deleting the section cascades to its rows before the new ones are written.
                connection.execute(
                    "DELETE FROM analysis_section WHERE request_key=? AND input_fp=? AND section=?",
                    (request_key, input_fp, name),
                )
                connection.execute(
                    "INSERT INTO analysis_section VALUES(?,?,?,?,?,?,?,?,0)",
                    (request_key, input_fp, name, payload, size, sha, now, now),
                )
            for name, items in rows.items():
                encoded = []
                for index, (key, value) in enumerate(items):
                    payload, size, sha = self._encode(value)
                    sizes[name] = sizes.get(name, 0) + size
                    encoded.append((request_key, input_fp, name, index, key, payload, size, sha))
                connection.executemany("INSERT INTO analysis_row VALUES(?,?,?,?,?,?,?,?)", encoded)
        return sizes

    def section_rows(
        self, request_key: str, input_fp: str, section: str, *, offset: int = 0, limit: int = 50
    ) -> Record:
        """Page stored rows with LIMIT/OFFSET; only the requested rows are decoded."""
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset must be nonnegative and limit 1–1000")
        key = (request_key, input_fp, section)
        with self.connect() as connection:
            total = connection.execute(
                "SELECT count(*) FROM analysis_row WHERE request_key=? AND input_fp=? AND section=?",
                key,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM analysis_row WHERE request_key=? AND input_fp=? AND section=?"
                " ORDER BY idx LIMIT ? OFFSET ?",
                (*key, limit, offset),
            ).fetchall()
        items = [self._decode(r["payload"], r["json_bytes"], r["sha256"], "row") for r in rows]
        return {"total": total, "offset": offset, "limit": limit, "items": items}

    def section_row(self, request_key: str, input_fp: str, section: str, row_key: str) -> Any:
        """Fetch one stored row by key, or None when the section has no such row."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_row WHERE request_key=? AND input_fp=? AND section=?"
                " AND row_key=? ORDER BY idx LIMIT 1",
                (request_key, input_fp, section, row_key),
            ).fetchone()
        if row is None:
            return None
        return self._decode(row["payload"], row["json_bytes"], row["sha256"], "row")

    def exclude(self, session_uid: str, reason: str | None = None) -> Record:
        """Persist an exclusion; repeating it keeps the first timestamp and updates the reason."""
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO session_exclusion VALUES(?,?,?) ON CONFLICT(session_uid)"
                " DO UPDATE SET reason=excluded.reason",
                (session_uid, reason, _now()),
            )
            row = connection.execute(
                "SELECT * FROM session_exclusion WHERE session_uid=?", (session_uid,)
            ).fetchone()
        return dict(row)

    def include(self, session_uid: str) -> bool:
        """Remove an exclusion; returns whether one existed."""
        with self.connect() as connection:
            deleted = connection.execute(
                "DELETE FROM session_exclusion WHERE session_uid=?", (session_uid,)
            ).rowcount
        return deleted == 1

    def exclusions(self) -> list[Record]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM session_exclusion ORDER BY session_uid"
            ).fetchall()
        return [dict(row) for row in rows]

    def stored_bytes(self) -> int:
        """Bytes in use by the database file (free pages excluded)."""
        with self.connect() as connection:
            page = connection.execute("PRAGMA page_size").fetchone()[0]
            count = connection.execute("PRAGMA page_count").fetchone()[0]
            free = connection.execute("PRAGMA freelist_count").fetchone()[0]
        return (count - free) * page

    def prune(
        self,
        *,
        algo_version: str | None = None,
        keep_inputs: int = KEEP_INPUTS,
        max_bytes: int = MAX_BYTES,
        failed_retention_ms: int = FAILED_RETENTION_MS,
        keep_runs_per_request: int = KEEP_RUNS_PER_REQUEST,
        keep_runs: int = KEEP_RUNS,
        protect: list[tuple[str, str]] | None = None,
        now: int | None = None,
    ) -> Record:
        """Apply the retention policy.

        1. each request_key keeps its ``keep_inputs`` most recently used input fingerprints;
        2. failed runs older than the retention window are deleted;
        3. session rows from other algorithm versions are deleted;
        4. completed runs: the newest ``keep_runs_per_request`` per (engine, request) and
           ``keep_runs`` overall keep their snapshots; older runs and the snapshots no run
           references any more are deleted (a full snapshot is often 100+ MB);
        5. while the database exceeds ``max_bytes``, least recently hit sections are evicted,
           except the ``protect``ed (request_key, input_fp) pairs (the caller's own result).
        """
        now = _now() if now is None else now
        stats = {
            "stale_inputs": 0,
            "failed_runs": 0,
            "old_session_results": 0,
            "evicted": 0,
            "old_runs": 0,
            "snapshots": 0,
        }
        with self.connect() as connection:
            stats["stale_inputs"] = connection.execute(
                """DELETE FROM analysis_section WHERE (request_key, input_fp) IN (
                     SELECT request_key, input_fp FROM (
                       SELECT request_key, input_fp, row_number() OVER (
                         PARTITION BY request_key
                         ORDER BY max(last_hit_at) DESC, max(created_at) DESC, input_fp
                       ) AS rank
                       FROM analysis_section GROUP BY request_key, input_fp)
                     WHERE rank > ?)""",
                (keep_inputs,),
            ).rowcount
            stats["failed_runs"] = connection.execute(
                "DELETE FROM analysis_run WHERE status='failed' AND finished_at < ?",
                (now - failed_retention_ms,),
            ).rowcount
            if algo_version is not None:
                stats["old_session_results"] = connection.execute(
                    "DELETE FROM session_result WHERE algo_version<>?", (algo_version,)
                ).rowcount
            stats["old_runs"] = connection.execute(
                """DELETE FROM analysis_run WHERE run_id IN (
                     SELECT run_id FROM (
                       SELECT run_id,
                         row_number() OVER (
                           PARTITION BY engine, COALESCE(request_key, request_json)
                           ORDER BY started_at DESC, rowid DESC) AS per_request,
                         row_number() OVER (ORDER BY started_at DESC, rowid DESC) AS overall
                       FROM analysis_run WHERE status='completed')
                     WHERE per_request > ? OR overall > ?)""",
                (keep_runs_per_request, keep_runs),
            ).rowcount
            stats["snapshots"] = connection.execute(
                "DELETE FROM analysis_snapshot WHERE snapshot_id NOT IN ("
                " SELECT snapshot_id FROM analysis_run WHERE snapshot_id IS NOT NULL)"
            ).rowcount
        while self.stored_bytes() > max_bytes:
            with self.connect() as connection:
                oldest = connection.execute(
                    "SELECT request_key, input_fp, section FROM analysis_section"
                    " WHERE request_key || ' ' || input_fp NOT IN (SELECT value FROM json_each(?))"
                    " ORDER BY last_hit_at, created_at LIMIT 1",
                    (json.dumps([f"{k} {fp}" for k, fp in protect or ()]),),
                ).fetchone()
                if oldest is None:
                    break
                connection.execute(
                    "DELETE FROM analysis_section WHERE request_key=? AND input_fp=? AND section=?",
                    tuple(oldest),
                )
                stats["evicted"] += 1
        return stats

    def file_bytes(self) -> int:
        """Bytes the database occupies on disk, WAL included."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.stat(f"{self.path}{suffix}").st_size
            except OSError:
                pass
        return total

    def vacuum_if_sparse(self, *, min_bytes: int = 256 * 1024 * 1024, ratio: float = 0.5) -> bool:
        """VACUUM when more than ``ratio`` of a large file is free pages (after pruning)."""
        with self.connect() as connection:
            pages = connection.execute("PRAGMA page_count").fetchone()[0]
            free = connection.execute("PRAGMA freelist_count").fetchone()[0]
            page = connection.execute("PRAGMA page_size").fetchone()[0]
        if pages * page < min_bytes or free <= pages * ratio:
            return False
        connection = sqlite3.connect(self.path, timeout=LOCK_TIMEOUT_S, isolation_level=None)
        try:
            connection.execute("VACUUM")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
        return True
