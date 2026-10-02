"""Application boundary for import jobs. One writer; readers use query-only SQLite.

Keep UI, file discovery, and native mapping separate. Callbacks contain progress,
never session text. Cancellation is checked between files; publication is atomic.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import zstandard

from tandem_data import MAPPER_VERSION, REDUCER_VERSION
from tandem_data.connectors import MAPPERS
from tandem_data.contract import now_ms
from tandem_data.discovery import inputs
from tandem_data.privacy import REDACTION_VERSION
from tandem_data.query import event_page as event_page
from tandem_data.store import Store


@dataclass(frozen=True)
class ImportRequest:
    agent: str
    root: Path
    files: tuple[Path, ...] | None = None
    limit: int | None = None
    rebuild: bool = True


class ImportService:
    """Use one instance per worker thread; never share a SQLite connection across threads."""

    def __init__(self, store: Store, progress: Callable[[dict], None] | None = None):
        self.store = store
        self.progress = progress or (lambda _: None)

    @contextmanager
    def _writer(self):
        fd = os.open(self.store.home / "import.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another import worker is active") from error
            yield
        finally:
            os.close(fd)

    def import_source(self, request: ImportRequest, cancel: threading.Event | None = None) -> dict:
        if request.agent not in MAPPERS:
            raise ValueError(f"Unknown connector: {request.agent}")
        if request.limit is not None and request.limit < 1:
            raise ValueError("limit must be positive")
        root = request.root.expanduser().resolve(strict=True)
        started = time.perf_counter()
        with self._writer():
            source_id = self.store.add_source(request.agent, root)
            available = list(inputs(request.agent, root))
            allowed = {item.path.resolve(): item for item in available}
            if request.files is not None:
                selected = []
                for file in request.files:
                    path = (root / file).resolve() if not file.is_absolute() else file.resolve()
                    if path not in allowed:
                        raise ValueError("Selected file is not an allowlisted session input")
                    selected.append(allowed[path])
            else:
                selected = available
            selected = selected[: request.limit] if request.limit is not None else selected
            result = {
                "source_id": source_id,
                "agent": request.agent,
                "files": 0,
                "changed": 0,
                "capture_errors": 0,
                "cancelled": False,
                "selection": "full"
                if request.files is None and request.limit is None
                else "sample",
            }
            for item in selected:
                if cancel and cancel.is_set():
                    result["cancelled"] = True
                    break
                try:
                    captured = self.store.capture_file(source_id, item.path, item.role)
                    result["files"] += 1
                    result["changed"] += int(captured["changed"])
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    sqlite3.Error,
                    zstandard.ZstdError,
                ) as error:
                    result["capture_errors"] += 1
                    self.store.issue(
                        source_id,
                        "capture_failed",
                        stage="l1",
                        detail={
                            "exception": type(error).__name__,
                            "path": str(item.path.relative_to(root)),
                        },
                    )
                self.progress(
                    {
                        "stage": "capture",
                        "agent": request.agent,
                        "completed": result["files"] + result["capture_errors"],
                        "total": len(selected),
                    }
                )
            if result["selection"] == "full" and not result["cancelled"]:
                seen = {str(item.path.relative_to(root)) for item in available}
                for row in self.store.db.execute(
                    "SELECT * FROM source_file WHERE source_id=?", (source_id,)
                ).fetchall():
                    if row["relative_path"] not in seen:
                        self.store.db.execute(
                            "UPDATE source_file SET status='gone_upstream',last_scan_at=? WHERE file_id=?",
                            (now_ms(), row["file_id"]),
                        )
            # A failed/cancelled previous run can leave new L1 revisions unpublished.
            stale_sources = {
                row[0]
                for row in self.store.db.execute(
                    "SELECT DISTINCT source_id FROM source_file WHERE COALESCE(json_extract(watermark,'$.projected_revision'),-1) <> COALESCE(json_extract(watermark,'$.revision'),0) OR COALESCE(json_extract(watermark,'$.mapper_version'),'')<>? OR COALESCE(json_extract(watermark,'$.reducer_version'),'')<>? OR COALESCE(json_extract(watermark,'$.redaction_version'),'')<>?",
                    (MAPPER_VERSION, REDUCER_VERSION, REDACTION_VERSION),
                )
            }
            if request.rebuild and not result["cancelled"] and stale_sources:
                self.progress({"stage": "normalize", "agent": request.agent})
                result["projection"] = self.store.rebuild(source_ids=stale_sources)
            result["elapsed_seconds"] = round(time.perf_counter() - started, 4)
            result["current_unparsed"] = self.store.db.execute(
                "SELECT COUNT(*) FROM raw_record r JOIN file_record c USING(record_uid) JOIN source_file f ON f.file_id=r.file_id WHERE f.source_id=? AND r.disposition='unparsed'",
                (source_id,),
            ).fetchone()[0]
            return result

    def watch(self, request: ImportRequest, stop: threading.Event, interval: float = 2.0):
        """Portable polling fallback; SQLite WAL changes are seen by each read transaction."""
        if interval <= 0:
            raise ValueError("interval must be positive")
        while not stop.is_set():
            yield self.import_source(request, stop)
            stop.wait(interval)
