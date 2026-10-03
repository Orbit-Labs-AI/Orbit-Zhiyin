"""Clear all Orbit data (SET-12): mark now, delete on the next start.

A running gateway holds orbit.db, app.db, catalog.db and the snapshot cache open, so
``POST /v1/app/data/clear`` only writes ``<home>/.clear_pending``. ``apply_pending(home)``
runs first thing in ``Gateway.__init__`` and removes Orbit's own files. Agent logs and
agent configs live outside the home and are never touched; ``logs/`` is kept for support.
Every target must resolve inside the home: a symlink pointing elsewhere is refused.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from ..platform.storage import storage_report

log = logging.getLogger(__name__)

MARKER = ".clear_pending"
CONFIRM_WORD = "清除"
KEEPS = ["agent_logs", "agent_configs"]
# storage component ids removed by a clear (``logs`` stays).
WILL_DELETE = ["orbit_db", "raw", "app_db", "catalog_db", "analysis", "snapshot_cache",
               "backups", "exports", "app_state", "hooks"]
TARGETS = ("orbit.db", "orbit.db-wal", "orbit.db-shm", "raw", "archive", "analysis*.db",
           "analysis*.db-wal", "analysis*.db-shm", "analysis.sqlite*", "cache",
           "catalog.db", "catalog.db-wal", "catalog.db-shm", "backups", "exports",
           "app.db", "app.db-wal", "app.db-shm", "app-state.json", "app-state.tmp", "hooks")


def mark(home: Path, *, reason: str = "user") -> dict:
    home = home.expanduser().resolve()
    body = {"requested_at": int(time.time() * 1000), "reason": reason, "will_delete": WILL_DELETE}
    path = home / MARKER
    path.write_text(json.dumps(body, ensure_ascii=False))
    path.chmod(0o600)
    return {"marker": str(path), "restart_required": True, "will_delete": WILL_DELETE}


def pending(home: Path) -> bool:
    return (home / MARKER).is_file()


def _inside(home: Path, path: Path) -> bool:
    """True when ``path`` itself and what it resolves to both live under ``home``."""
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return path.parent.resolve().is_relative_to(home) and resolved.is_relative_to(home) and (
        resolved != home)


def _targets(home: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in TARGETS:
        paths = sorted(home.glob(pattern)) if "*" in pattern else [home / pattern]
        found += [p for p in paths if p.exists() or p.is_symlink()]
    return found


def apply_pending(home: Path) -> dict | None:
    """Delete Orbit data when a clear is pending; returns a summary or None."""
    home = home.expanduser().resolve()
    marker = home / MARKER
    if not marker.is_file():
        return None
    deleted, refused, failed = [], [], []
    for path in _targets(home):
        if path.is_symlink() or not _inside(home, path):
            refused.append(path.name)  # Never follow a link out of (or within) the home.
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            deleted.append(path.name)
        except OSError as error:
            log.warning("clear: could not delete %s: %s", path, error)
            failed.append(path.name)
    marker.unlink(missing_ok=True)
    summary = {"deleted": deleted, "refused": refused, "failed": failed,
               "applied_at": int(time.time() * 1000)}
    log.info("clear applied: %s", summary)
    return summary


def describe(home: Path, appdb, state) -> dict:
    """``GET /v1/app/data``: what a clear removes and what stays."""
    report = storage_report(home)
    installs = ledger = 0
    try:
        with appdb.read() as db:
            installs = db.execute("SELECT COUNT(*) FROM install_state WHERE state NOT IN "
                                  "('reverted','archived')").fetchone()[0]
            ledger = db.execute("SELECT COUNT(*) FROM install_ledger").fetchone()[0]
    except Exception:  # noqa: BLE001 - counts are informative only.
        log.debug("install counts unavailable", exc_info=True)
    active = state.active_job()
    return {"home": report["home"], "total_bytes": report["total_bytes"],
            "components": report["components"], "will_delete": WILL_DELETE, "keeps": KEEPS,
            "installs_active": installs, "ledger_entries": ledger,
            "jobs_active": 1 if active else 0, "pending": pending(home),
            "confirm_word": CONFIRM_WORD,
            "note": "清除后需要重启 Orbit；已安装到 Agent 的组件不会被撤销，请先在安装台账中撤销。"}
