"""Idle-gated maintenance on one daemon thread: metric flush, app.db WAL checkpoint and
optimize, snapshot-cache compaction, storage report, retention, telemetry export and a
weekly integrity check. While a job is active only the metric flush runs.

tandem.db is never touched here (single writer: ingest-worker).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import logs, storage, telemetry
from .diagnostics import prune_exports

TICK_S = 5.0
KEEP_RUNS = 200
WAL_TRUNCATE = 64 * 1024 * 1024
DISK_LOW = 2 * 1024**3
LOGS_CAP = 20 * 1024 * 1024
INTERVALS = {
    "metrics_flush": 60, "wal_checkpoint": 300, "optimize": 3600, "snapshot_compact": 600,
    "storage_report": 3600, "retention": 86_400, "install_sweep": 86_400,
    "telemetry_export": 86_400, "integrity": 604_800,
}
LIGHT = frozenset({"metrics_flush"})


class UnknownTask(KeyError):
    pass


def _notify(event: dict) -> None:
    try:
        # The submodule function (the package attribute ``notify`` is rebound to a wrapper).
        from .notify import notify

        notify(event)
    except Exception:  # noqa: BLE001 - notifications are optional.
        pass


class Maintenance:
    def __init__(self, platform, tick_s: float = TICK_S):
        self.platform = platform
        self.tick_s = tick_s
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        self.last: dict[str, dict] = {}
        with platform.appdb.read() as db:
            for row in db.execute(
                    "SELECT task, started_at, ms, ok FROM maintenance_run WHERE id IN ("
                    "SELECT max(id) FROM maintenance_run GROUP BY task)"):
                self.last[row[0]] = {"last_run": row[1], "ms": row[2], "ok": bool(row[3])}
        self.intervals = dict(INTERVALS)
        self.light = set(LIGHT)
        self.tasks = {name: getattr(self, f"_{name}") for name in INTERVALS}

    def register(self, name: str, fn, interval_s: int, *, light: bool = False) -> None:
        """Add a periodic task from another area (runs on this thread, idle-gated unless
        ``light``); also reachable through ``/v1/platform/maintenance/run``."""
        with self.lock:
            self.tasks[name] = fn
            self.intervals[name] = int(interval_s)
            if light:
                self.light.add(name)

    # -- scheduling --------------------------------------------------------------------
    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True,
                                           name="tandem-maintenance")
            self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(5)

    def _busy(self) -> bool:
        state = getattr(self.platform.gw, "state", None)
        try:
            return bool(state is not None and state.active_job())
        except Exception:  # noqa: BLE001
            return False

    def due(self, now_ms: int | None = None) -> list[str]:
        now_ms = now_ms or int(time.time() * 1000)
        # First run of slow tasks waits one interval after startup, except quick ones.
        started = int(self.platform.started_at * 1000)
        out = []
        for name, interval in list(self.intervals.items()):
            last = self.last.get(name, {}).get("last_run")
            reference = last if last is not None else started if interval > 600 else 0
            if now_ms - reference >= interval * 1000:
                out.append(name)
        return out

    def tick(self) -> list[str]:
        if not self.platform.settings.flag("maintenance"):
            return []
        busy = self._busy()
        ran = []
        for name in self.due():
            if self.stopping.is_set():
                break
            if busy and name not in self.light:
                continue
            self.run(name)
            ran.append(name)
        return ran

    def _loop(self) -> None:
        while not self.stopping.wait(self.tick_s):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                logs.log.exception("maintenance tick failed", extra={"ev": "maintenance_tick"})

    def run(self, task: str) -> dict:
        fn = self.tasks.get(task)
        if fn is None:
            raise UnknownTask(task)
        started = int(time.time() * 1000)
        t0 = time.perf_counter()
        with self.lock:
            try:
                detail, ok = fn() or {}, True
            except Exception as error:  # noqa: BLE001 - recorded, never raised to the loop.
                detail, ok = {"error": type(error).__name__, "message": str(error)[:300]}, False
                logs.log_event("maintenance_failed", logging.ERROR, task=task, **detail)
        ms = int((time.perf_counter() - t0) * 1000)
        self.last[task] = {"last_run": started, "ms": ms, "ok": ok}
        try:
            with self.platform.appdb.write() as db:
                db.execute("INSERT INTO maintenance_run (task, started_at, ms, ok, detail) "
                           "VALUES (?,?,?,?,?)", (task, started, ms, int(ok),
                                                  json.dumps(detail, default=str)))
                db.execute("DELETE FROM maintenance_run WHERE id <= (SELECT max(id) FROM "
                           "maintenance_run) - ?", (KEEP_RUNS,))
        except Exception:  # noqa: BLE001 - app.db unavailable during shutdown.
            pass
        telemetry.record("maintenance", ms, task=task)
        return {"task": task, "ok": ok, "ms": ms, "detail": detail}

    def status(self) -> dict:
        started = int(self.platform.started_at * 1000)
        out = {}
        for name, interval in list(self.intervals.items()):
            last = self.last.get(name, {})
            reference = last.get("last_run")
            if reference is None:
                reference = started if interval > 600 else started - interval * 1000
            out[name] = {"interval_s": interval, "last_run": last.get("last_run"),
                         "ms": last.get("ms"), "ok": last.get("ok"),
                         "next_due": reference + interval * 1000}
        return out

    # -- tasks -------------------------------------------------------------------------
    def _metrics_flush(self) -> dict:
        t = self.platform.telemetry
        return {"flushed": t.flush(), "rolled_up": t.rollup()}

    def _wal_checkpoint(self) -> dict:
        wal = self.platform.home / "app.db-wal"
        size = wal.stat().st_size if wal.exists() else 0
        mode = "TRUNCATE" if size > WAL_TRUNCATE else "PASSIVE"
        with self.platform.appdb.lock:
            busy, log_frames, done = self.platform.appdb.db.execute(
                f"PRAGMA wal_checkpoint({mode})").fetchone()
        return {"mode": mode, "wal_bytes": size, "busy": busy, "frames": log_frames,
                "checkpointed": done}

    def _optimize(self) -> dict:
        with self.platform.appdb.lock:
            self.platform.appdb.db.execute("PRAGMA optimize")
        return {}

    def _snapshot_compact(self) -> dict:
        snapshots = getattr(self.platform.gw, "snapshots", None)
        if snapshots is None or not hasattr(snapshots, "compact"):
            return {"skipped": True}
        return snapshots.compact()

    def _storage_report(self) -> dict:
        report = storage.storage_report(self.platform.home)
        storage.save_report(self.platform.appdb, report)
        try:
            import shutil

            free = shutil.disk_usage(self.platform.home).free
        except OSError:
            free = None
        if free is not None and free < DISK_LOW:
            _notify({"type": "system", "key": "system:disk_low", "title": "磁盘空间不足",
                     "body": f"剩余 {free // 1024**2} MB", "payload": {"free_bytes": free}})
        return {"total_bytes": report["total_bytes"], "free_bytes": free}

    def _retention(self) -> dict:
        p = self.platform
        detail = {"metric_rows": p.telemetry.prune(),
                  "exports": prune_exports(p.home)}
        detail["notifications"] = p.notifier.prune()
        detail["log_files"] = _prune_logs(p.home / "logs")
        detail["analysis"] = _analysis_retention(p.home)
        storage.save_report(p.appdb, storage.storage_report(p.home))  # sizes just changed
        return detail

    def _install_sweep(self) -> dict:
        """Record real usage, idle-mark stale installs, drop old backups, plans and fetch cache."""
        service = getattr(self.platform.gw, "install", None)  # set by routes_install.router
        if service is None:
            return {"skipped": True}
        from ..install import lifecycle
        from ..install.fetch import gc

        try:
            used = lifecycle.record_usage(service)
        except Exception as error:  # noqa: BLE001 - tandem.db missing/old: sweep still closes windows
            logs.log_event("install_usage_failed", logging.WARNING, error=str(error))
            used = None
        return {"triggered": used, **lifecycle.sweep(service, int(time.time() * 1000)),
                "backups": service.sweep_backups(keep=50, days=90),
                "plans": service.sweep_plans(30), "fetch_cache": gc(service.cache_dir)}

    def _telemetry_export(self) -> dict:
        p = self.platform
        cfg = p.settings.get("telemetry")
        directory = cfg.get("export_dir")
        if not (cfg.get("enabled") and directory):
            return {"skipped": True}
        day = (datetime.now(UTC) - timedelta(days=1)).date()
        start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)
        with p.appdb.read() as db:
            rows = db.execute("SELECT ts,name,tags,n,sum,min,max,buckets FROM metric_hour "
                              "WHERE ts >= ? AND ts < ? ORDER BY ts, name, tags",
                              (start, start + 86_400_000)).fetchall()
        target = Path(directory) / f"metrics-{day:%Y%m%d}.jsonl"
        partial = target.with_suffix(".jsonl.partial")
        with partial.open("w", encoding="utf-8") as handle:
            for r in rows:
                handle.write(json.dumps({"ts": r[0], "name": r[1], "tags": json.loads(r[2]),
                                         "n": r[3], "sum": r[4], "min": r[5], "max": r[6],
                                         "buckets": json.loads(r[7]) if r[7] else None},
                                        ensure_ascii=False) + "\n")
        os.replace(partial, target)
        return {"file": target.name, "rows": len(rows)}

    def _integrity(self) -> dict:
        from .health import appdb_integrity

        result = appdb_integrity(self.platform, force=True)["result"]
        if result != "ok":
            logs.log_event("integrity_failed", logging.ERROR, db="app.db", result=result)
            _notify({"type": "system", "key": "system:integrity",
                     "title": "应用数据库完整性检查失败"})
            raise RuntimeError(f"app.db quick_check: {result}")
        return {"app_db": result}


def _analysis_retention(home: Path) -> dict:
    """analysis.sqlite: drop old run snapshots and stale cache entries, then VACUUM when
    mostly free pages (each full run snapshot used to stay forever, ~100 MB apiece)."""
    path = home / "analysis.sqlite"
    if not path.is_file():
        return {"skipped": True}
    from tandem_data.analysis_history import AnalysisHistory

    from ..analytics.cache import algo_version

    history = AnalysisHistory(path)
    stats = history.prune(algo_version=algo_version())
    stats["vacuumed"] = history.vacuum_if_sparse()
    stats["file_bytes"] = history.file_bytes()
    return stats


# Files another writer holds open: tandem.log (RotatingFileHandler) and the workers' stderr
# logs opened in append mode by services/supervisor.py. Unlinking one would leave the writer
# on a deleted inode (disk not freed, later lines lost), so live worker logs are truncated in
# place instead — O_APPEND writers continue at the new end.
LIVE_LOGS = ("tandem.log", "ingest.log", "analysis.log")


def _prune_logs(directory: Path) -> int:
    """While the folder exceeds the cap: delete the oldest rotated logs first, then truncate
    live worker logs; tandem.log rotates itself. Returns files deleted or truncated."""
    if not directory.is_dir():
        return 0
    files = sorted((p for p in directory.iterdir() if p.is_file()),
                   key=lambda p: (p.name in LIVE_LOGS, p.stat().st_mtime))
    total = sum(p.stat().st_size for p in files)
    removed = 0
    for path in files:
        if total <= LOGS_CAP:
            break
        if path.name == "tandem.log":
            continue
        size = path.stat().st_size
        if path.name in LIVE_LOGS:
            if not size:
                continue
            os.truncate(path, 0)
        else:
            path.unlink(missing_ok=True)
        total -= size
        removed += 1
    return removed
