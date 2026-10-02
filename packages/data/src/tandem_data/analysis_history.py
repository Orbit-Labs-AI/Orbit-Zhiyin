"""Append-only execution records and content-addressed, checksummed analysis snapshots."""

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


def _json(value: Any) -> str:
    """Keep byte identities stable and reject NaN or unsupported result values."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


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
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("Unsupported analysis history schema")
            if version == 0:
                schema = files("tandem_data").joinpath("migrations/analysis/001.sql").read_text()
                connection.executescript(
                    "BEGIN IMMEDIATE;\n" + schema + "\nPRAGMA user_version=1;\nCOMMIT;"
                )

    @contextmanager
    def connect(self):
        """Bound lock waits and enforce references for every short transaction."""
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def start(self, engine: str, request: Record) -> str:
        """Create an execution even when an identical analysis has previously completed."""
        run_id = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO analysis_run(run_id,engine,status,started_at,request_json) VALUES(?,?,'running',?,?)",
                (run_id, engine, time.time_ns() // 1_000_000, _json(request)),
            )
        return run_id

    def complete(self, run_id: str, result: Record) -> str:
        """Atomically publish the complete result and finish exactly one running execution."""
        data = _json(result).encode("utf-8")
        snapshot_id = hashlib.sha256(data).hexdigest()
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
                    zlib.compress(data),
                    now,
                ),
            )
            connection.execute(
                "UPDATE analysis_run SET status='completed',finished_at=?,snapshot_id=? WHERE run_id=?",
                (now, snapshot_id, run_id),
            )
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
            raise ValueError("Analysis snapshot is corrupt") from error
        if len(data) != row["json_bytes"] or hashlib.sha256(data).hexdigest() != row["snapshot_id"]:
            raise ValueError("Analysis snapshot checksum mismatch")
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
