"""Deep health: databases, disk, workers, event bus, loops, maintenance, logs.

The shallow result is cached 5 s and stays under ~100 ms; ``deep`` adds an integrity
check of orbit.db through the read pool (never writes it) and refreshes app.db's.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .. import __version__

CACHE_S = 5.0
APPDB_CHECK_S = 86_400
WAL_WARN = 512 * 1024 * 1024
DISK_WARN = 2 * 1024**3
DISK_FAIL = 200 * 1024**2
RANK = {"ok": 0, "warn": 1, "fail": 2}


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _check(checks: list, cid: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        status, detail = fn()
    except Exception as error:  # noqa: BLE001 - a broken probe is itself a failure.
        status, detail = "fail", {"error": type(error).__name__, "message": str(error)[:200]}
    checks.append({"id": cid, "status": status, "ms": round((time.perf_counter() - t0) * 1000, 1),
                   "detail": detail})


def _rss(pids: list[int]) -> dict[int, int]:
    if not pids:
        return {}
    try:
        out = subprocess.run(["ps", "-o", "pid=,rss=", "-p", ",".join(map(str, pids))],
                             capture_output=True, text=True, timeout=1, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    result = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            result[int(parts[0])] = int(parts[1]) * 1024
    return result


def appdb_integrity(platform, force: bool = False) -> dict:
    cached = platform.appdb_check
    if cached and not force and time.time() - cached["at"] < APPDB_CHECK_S:
        return cached
    with platform.appdb.read() as db:
        result = db.execute("PRAGMA quick_check(1)").fetchone()[0]
    platform.appdb_check = {"at": time.time(), "result": result}
    return platform.appdb_check


def health(platform, deep: bool = False) -> dict:
    cached = platform.health_cache
    if not deep and cached and time.monotonic() - cached[0] < CACHE_S:
        return cached[1]
    gw, home = platform.gw, platform.home
    checks: list[dict] = []

    def app_db():
        check = appdb_integrity(platform, force=deep)
        return ("ok" if check["result"] == "ok" else "fail"), {
            "quick_check": check["result"], "checked_at": int(check["at"] * 1000),
            "bytes": _size(home / "app.db"), "wal_bytes": _size(home / "app.db-wal")}

    def orbit_db():
        path = home / "orbit.db"
        if not path.is_file():
            return "ok", {"absent": True}
        detail = {"bytes": _size(path), "wal_bytes": _size(home / "orbit.db-wal")}
        status = "warn" if detail["wal_bytes"] > WAL_WARN else "ok"
        if deep:
            with gw.reads.read(check=False) as db:
                detail["quick_check"] = db.execute("PRAGMA quick_check(1)").fetchone()[0]
            if detail["quick_check"] != "ok":
                status = "fail"
        return status, detail

    def cache_db():
        snapshots = getattr(gw, "snapshots", None)
        stats = snapshots.stats() if snapshots is not None and hasattr(snapshots, "stats") else {}
        return "ok", stats

    def disk():
        usage = shutil.disk_usage(home)
        status = "fail" if usage.free < DISK_FAIL else "warn" if usage.free < DISK_WARN else "ok"
        return status, {"free_bytes": usage.free, "total_bytes": usage.total}

    services = gw.supervisor.services() if getattr(gw, "supervisor", None) else {}

    def workers():
        stale = getattr(getattr(gw, "config", None), "stale_s", 15.0)
        status, notes = "ok", []
        for name, info in services.items():
            if info.get("state") == "degraded":
                status = "fail"
                notes.append(f"{name} degraded")
            elif (info.get("last_hb_age_s") or 0) > stale:
                status = max(status, "warn", key=RANK.get)
                notes.append(f"{name} heartbeat stale")
        if sum(int(i.get("restarts") or 0) for i in services.values()) > 10:
            status = max(status, "warn", key=RANK.get)
            notes.append("frequent restarts")
        return status, {"notes": notes}

    def event_bus():
        bus = gw.bus
        return ("fail" if bus.closed else "ok"), {"last_id": bus.last_id,
                                                  "clients": len(bus.waiters)}

    def sync_loop():
        thread = getattr(gw, "sync_thread", None)
        if thread is None:
            return "ok", {"running": False}
        alive = thread.is_alive()
        stopping = getattr(gw, "stopping", None)
        return ("ok" if alive or (stopping and stopping.is_set()) else "fail"), {"running": alive}

    maintenance = platform.maintenance.status() if platform.maintenance else {}

    def maintenance_check():
        uptime = time.time() - platform.started_at
        late = [task for task, info in maintenance.items()
                if info["interval_s"] <= 3600 and (
                    (info["last_run"] is None and uptime > 2 * info["interval_s"])
                    or (info["last_run"] is not None
                        and time.time() * 1000 - info["last_run"] > 2 * info["interval_s"] * 1000))]
        failed = [task for task, info in maintenance.items() if info.get("ok") is False]
        return ("warn" if late or failed else "ok"), {"late": late, "failed": failed}

    def logs_check():
        directory = home / "logs"
        ok = directory.is_dir() and os.access(directory, os.W_OK)
        return ("ok" if ok else "warn"), {"writable": ok}

    for cid, fn in (("app_db", app_db), ("orbit_db", orbit_db), ("cache_db", cache_db),
                    ("disk", disk), ("workers", workers), ("event_bus", event_bus),
                    ("sync_loop", sync_loop), ("maintenance", maintenance_check),
                    ("logs", logs_check)):
        _check(checks, cid, fn)

    rss = _rss([i["pid"] for i in services.values() if i.get("pid")])
    services = {name: {**info, **({"rss_bytes": rss[info["pid"]]} if info.get("pid") in rss
                                  else {})} for name, info in services.items()}
    worst = max((c["status"] for c in checks), key=RANK.get, default="ok")
    disk_detail = next((c["detail"] for c in checks if c["id"] == "disk"), {})
    collection = getattr(platform, "collection", None)
    result = {
        "status": {"ok": "ok", "warn": "degraded", "fail": "fail"}[worst],
        "version": __version__,
        "uptime_s": round(time.time() - platform.started_at, 1),
        "generated_at": int(time.time() * 1000),
        "checks": checks,
        "services": services,
        "disk": disk_detail if "free_bytes" in disk_detail else None,
        "db": {"orbit_db": _size(home / "orbit.db"), "orbit_wal": _size(home / "orbit.db-wal"),
               "app_db": _size(home / "app.db"), "catalog_db": _size(home / "catalog.db"),
               "analysis": sum(_size(p) for p in home.glob("analysis.sqlite*")),
               "snapshot_cache": sum(_size(p) for p in (home / "cache").glob("ui.sqlite*"))},
        "collection": {"paused": bool(getattr(collection, "paused", False))}
        if collection is not None else None,
        "maintenance": {task: {"last_run": i["last_run"], "ms": i["ms"], "ok": i["ok"]}
                        for task, i in maintenance.items()},
    }
    if not deep:
        platform.health_cache = (time.monotonic(), result)
    return result


