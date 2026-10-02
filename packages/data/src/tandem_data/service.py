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
import weakref
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import zstandard

from tandem_data import MAPPER_VERSION, REDUCER_VERSION, parallel, scheduler
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


# Background maintenance per store home. A new writer on the same home stops it (an
# interrupted VACUUM rolls back cleanly) and waits, so imports never queue behind
# maintenance; the next import end schedules it again.
class _Maintenance:
    def __init__(self, home: Path):
        self.home = home
        self.stop = threading.Event()
        self.connection: sqlite3.Connection | None = None
        self.result: dict | None = None
        self.thread = threading.Thread(target=self.run, name="tandem-maintenance", daemon=True)

    def run(self) -> None:
        fd = None
        # Sequential imports (one call per source) follow each other within milliseconds;
        # the grace period lets the next one cancel this run before any work starts.
        if self.stop.wait(MAINTENANCE_GRACE_SECONDS):
            self.result = {"action": "interrupted"}
            self._finish()
            return
        try:
            fd = _lock(self.home)
            with Store(self.home) as store:
                self.connection = store.db
                if self.stop.is_set():
                    self.result = {"action": "interrupted"}
                    return
                self.result = store.maintain()
        except RuntimeError:
            # Another process holds the writer lock; it maintains at its own import end.
            self.result = {"action": "busy"}
        except (OSError, ValueError, sqlite3.Error) as error:
            # Interrupted by a new writer (the VACUUM rolled back) or the store went away.
            self.result = {"action": "interrupted", "error": type(error).__name__}
        finally:
            self.connection = None
            if fd is not None:
                os.close(fd)
            self._finish()

    def _finish(self) -> None:
        with _MAINTENANCE_LOCK:
            if _MAINTENANCE.get(self.home) is self:
                del _MAINTENANCE[self.home]

    def interrupt(self) -> None:
        self.stop.set()
        connection = self.connection
        if connection is not None:
            connection.interrupt()


_MAINTENANCE: dict[Path, _Maintenance] = {}
_MAINTENANCE_LOCK = threading.Lock()
MAINTENANCE_MODES = ("background", "wait", "off")
MAINTENANCE_GRACE_SECONDS = 1.0


def _yield_maintenance(home: Path) -> None:
    with _MAINTENANCE_LOCK:
        running = _MAINTENANCE.get(home)
    if running is None or running.thread is threading.current_thread():
        return
    running.interrupt()
    running.thread.join()


def wait_for_maintenance(home: str | Path) -> dict | None:
    """Block until background maintenance on ``home`` finishes; returns its result."""
    with _MAINTENANCE_LOCK:
        running = _MAINTENANCE.get(Path(home).expanduser().resolve())
    if running is None:
        return None
    running.thread.join()
    return running.result


def _lock(home: Path) -> int:
    fd = os.open(home / "import.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(fd)
        raise RuntimeError("Another import worker is active") from error
    return fd


class ImportService:
    """Use one instance per worker thread; never share a SQLite connection across threads.

    ``maintenance`` runs ``Store.maintain`` (compaction) after an import has published,
    outside its timing: ``background`` (default) on a separate connection in a daemon
    thread, ``wait`` synchronously before the import call returns (CLI and benchmarks;
    reported as ``result["maintenance"]``), ``off`` never. WAL readers keep reading their
    snapshot while a VACUUM runs and see the compacted file on their next transaction; a
    page size change needs the only connection and otherwise keeps the current size.
    """

    def __init__(
        self,
        store: Store,
        progress: Callable[[dict], None] | None = None,
        workers: int | None = None,
        maintenance: str = "background",
    ):
        """``workers=1`` keeps the serial whole-source path; the default is parallel."""
        if maintenance not in MAINTENANCE_MODES:
            raise ValueError(f"maintenance must be one of {MAINTENANCE_MODES}")
        self.maintenance = maintenance
        self.store = store
        self.progress = progress or (lambda _: None)
        self.workers = parallel.default_workers() if workers is None else max(1, workers)
        self.pool = parallel.WorkerPool(self.workers) if self.workers != 1 else None
        if self.pool is not None:
            weakref.finalize(self, self.pool.close)
            parallel.writer_pragmas(store.db)

    def close(self):
        if self.pool is not None:
            self.pool.close()

    @contextmanager
    def writer(self):
        _yield_maintenance(self.store.home)
        fd = _lock(self.store.home)
        try:
            yield
        finally:
            os.close(fd)

    def maintain(self, *, force: bool = False) -> dict:
        """Synchronous post-import maintenance on this service's connection."""
        with self.writer():
            return self.store.maintain(force=force)

    def _after_publish(self, result: dict) -> dict:
        """Import end hook: compaction is scheduled after the import has published."""
        if self.maintenance == "wait":
            result["maintenance"] = self.maintain()
        elif self.maintenance == "background":
            home = self.store.home
            with _MAINTENANCE_LOCK:
                if home in _MAINTENANCE:
                    return result
                job = _MAINTENANCE[home] = _Maintenance(home)
                job.thread.start()
            result["maintenance"] = {"action": "scheduled"}
        return result

    _writer = writer  # Compatibility for earlier callers.

    def import_source(self, request: ImportRequest, cancel: threading.Event | None = None) -> dict:
        result = self._import_source(request, cancel)
        if "projection" in result:
            self._after_publish(result)
        return result

    def _import_source(self, request: ImportRequest, cancel: threading.Event | None) -> dict:
        if request.agent not in MAPPERS:
            raise ValueError(f"Unknown connector: {request.agent}")
        if request.limit is not None and request.limit < 1:
            raise ValueError("limit must be positive")
        root = request.root.expanduser().resolve(strict=True)
        started = time.perf_counter()
        with self.writer():
            source_id = self.store.add_source(request.agent, root)
            available = list(inputs(request.agent, root))
            if request.files is not None:
                allowed = {item.path.resolve(): item for item in available}
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
                # Captured files rewritten before projection; their last facts are kept.
                "skipped_files": 0,
                "cancelled": False,
                "selection": "full"
                if request.files is None and request.limit is None
                else "sample",
            }
            if result["selection"] == "full":
                # Mark absences before indexing so an archived/renamed file can be
                # matched by its decoded hash without creating duplicate identities.
                seen = parallel.relative_paths(root, available)
                if self.workers != 1:
                    scheduler.mark_missing(self.store, source_id, seen)
                for file in self.store.db.execute(
                    "SELECT file_id,relative_path FROM source_file WHERE source_id=?", (source_id,)
                ).fetchall():
                    if file["relative_path"] not in seen:
                        self.store.db.execute(
                            "UPDATE source_file SET status='gone_upstream' WHERE file_id=?",
                            (file["file_id"],),
                        )
            self.progress({"stage": "capture", "completed": 0, "total": len(selected)})
            if self.workers != 1:
                parallel.capture(
                    self.store,
                    source_id,
                    root,
                    selected,
                    self.pool,
                    cancel,
                    self.progress,
                    result,
                    request.agent,
                )
            for item in selected if self.workers == 1 else ():
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
                seen = parallel.relative_paths(root, available)
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
            unpublished = not self.store.db.execute(
                "SELECT 1 FROM projection_run LIMIT 1"
            ).fetchone()
            if request.rebuild and not result["cancelled"] and (stale_sources or unpublished):
                self.progress({"stage": "normalize", "agent": request.agent})
                if self.workers != 1:
                    result["projection"] = scheduler.project(
                        self.store, workers=self.workers, pool=self.pool, progress=self.progress
                    )
                else:
                    result["projection"] = self.store.rebuild(
                        source_ids=stale_sources, progress=self.progress, optimize=False
                    )
                result["skipped_files"] = result["projection"].get("skipped_files", 0)
            result["elapsed_seconds"] = round(time.perf_counter() - started, 4)
            result["current_unparsed"] = self._current_unparsed(
                source_id, unchanged=not result["changed"] and "projection" not in result
            )
            result["unknown_events"] = self.store.db.execute(
                "SELECT COUNT(*) FROM event e JOIN session_identity s USING(session_uid) WHERE s.source_id=? AND e.kind='unknown'",
                (source_id,),
            ).fetchone()[0]
            result["discovered_files"] = len(available)
            self.store.db.execute(
                "INSERT OR REPLACE INTO source_scan VALUES(?,?,?,?,?,?,?)",
                (
                    source_id,
                    now_ms(),
                    result["selection"],
                    len(available),
                    result["files"],
                    result["capture_errors"],
                    int(result["cancelled"]),
                ),
            )
            return result

    def _current_unparsed(self, source_id: str, *, unchanged: bool) -> int:
        """Unparsed current records of one source; reused while L1 and L2 are unchanged.

        The count visits every raw record of the source, which dominated no-change
        rescans. Dispositions only change when a file gains a revision (capture) or a
        projection publishes (a new ``projection_run`` row), so a rescan that changed
        neither reuses the value computed for the same stamp on this store.
        """
        db = self.store.db
        stamp = (
            tuple(
                db.execute("SELECT COALESCE(MAX(rowid),0),COUNT(*) FROM projection_run").fetchone()
            ),
            tuple(
                db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(json_extract(watermark,'$.revision')),0),"
                    "group_concat(json_extract(watermark,'$.source_sha256')) FROM source_file "
                    "WHERE source_id=?",
                    (source_id,),
                ).fetchone()
            ),
        )
        memo = self.store.__dict__.setdefault("_unparsed_memo", {})
        cached = memo.get(source_id)
        if unchanged and cached is not None and cached[0] == stamp:
            return cached[1]
        count = db.execute(
            "SELECT COUNT(*) FROM raw_record r JOIN file_record c USING(record_uid) JOIN source_file f ON f.file_id=r.file_id WHERE f.source_id=? AND r.disposition='unparsed'",
            (source_id,),
        ).fetchone()[0]
        memo[source_id] = (stamp, count)
        return count

    def watch(self, request: ImportRequest, stop: threading.Event, interval: float = 2.0):
        """Portable polling fallback; SQLite WAL changes are seen by each read transaction."""
        if interval <= 0:
            raise ValueError("interval must be positive")
        while not stop.is_set():
            if scheduler.paused(self.store.home):
                # Collection is paused: no capture, no new revision. Resume rescans by stat.
                yield {"agent": request.agent, "paused": True}
            else:
                yield self.import_source(request, stop)
            stop.wait(interval)

    def import_progressive(self, requests, cancel: threading.Event | None = None, **options):
        """First import, newest sessions first; see ``scheduler.import_progressive``."""
        summary = scheduler.import_progressive(self, list(requests), cancel=cancel, **options)
        if summary.get("batches"):
            self._after_publish(summary)
        return summary

    def pause_collection(self) -> dict:
        return scheduler.pause(self.store.home)

    def resume_collection(self) -> dict:
        return scheduler.resume(self.store.home)

    def collection_state(self) -> dict:
        return scheduler.collection_state(self.store.home)
