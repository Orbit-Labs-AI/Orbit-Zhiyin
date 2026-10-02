"""DT-15 / DT-03 storage usage by layer and the confirmed "delete all local data" action."""

from __future__ import annotations

import fcntl
import os
import stat
from pathlib import Path

from tandem_data.store import readonly_connection

PURGE_CONFIRMATION = "DELETE ALL LOCAL DATA"
DB_FILES = ("tandem.db", "tandem.db-wal", "tandem.db-shm", "tandem.db-journal")
CACHE_FILES = ("cache/capabilities.json",)
LAYERS = ("raw", "l1", "l2", "l3", "fts", "inventory", "other", "free", "wal")
L1 = {
    "source",
    "source_file",
    "source_revision",
    "source_reference",
    "record_location",
    "raw_record",
    "archive_blob",
    "file_record",
    "usage_observation",
    "source_scan",
    "connector_checkpoint",
    "connector_record_link",
}
L2 = {"event", "record_event", "event_context", "session_identity"}
L3 = {
    "session",
    "turn",
    "tool_call",
    "tool_call_event",
    "model_call",
    "usage_snapshot",
    "link",
    "session_feature",
    "project",
    "project_override",
    "model_alias",
    "projection_run",
}
INVENTORY = {"inventory_scan", "inventory_item"}
FTS_PREFIXES = ("event_fts", "event_search")


class PurgeRefused(ValueError):
    """The purge request was rejected before any file was touched."""


def layer_of(table: str) -> str:
    if table.startswith(FTS_PREFIXES):
        return "fts"
    for layer, names in (("l1", L1), ("l2", L2), ("l3", L3), ("inventory", INVENTORY)):
        if table in names:
            return layer
    return "other"


def storage_usage(home: str | Path) -> dict:
    """Bytes per layer. Database layers come from ``dbstat``; raw from a no-follow walk."""
    home = Path(home).expanduser()
    layers = dict.fromkeys(LAYERS, 0)
    tables: dict[str, int] = {}
    database = {"file_bytes": 0, "page_size": 0, "page_count": 0, "dbstat_bytes": 0}
    db_path = home / "tandem.db"
    if db_path.is_file() and not db_path.is_symlink():
        with readonly_connection(db_path) as db:
            owner = {
                row[0]: row[1] for row in db.execute("SELECT name, tbl_name FROM sqlite_schema")
            }
            for name, size in db.execute("SELECT name, pgsize FROM dbstat WHERE aggregate=TRUE"):
                table = owner.get(name, name)
                tables[table] = tables.get(table, 0) + size
                layers[layer_of(table)] += size
                database["dbstat_bytes"] += size
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            page_count = db.execute("PRAGMA page_count").fetchone()[0]
            layers["free"] = db.execute("PRAGMA freelist_count").fetchone()[0] * page_size
        database.update(
            file_bytes=db_path.stat().st_size, page_size=page_size, page_count=page_count
        )
    for name in DB_FILES[1:]:
        path = home / name
        if path.is_file() and not path.is_symlink():
            layers["wal"] += path.stat().st_size
    raw_bytes, raw_files = _tree_size(home / "raw")
    layers["raw"] = raw_bytes
    return {
        "home": str(home),
        "layers": layers,
        "total_bytes": sum(layers.values()),
        "database": database,
        "raw": {"bytes": raw_bytes, "files": raw_files},
        "tables": dict(sorted(tables.items(), key=lambda item: (-item[1], item[0]))),
    }


def _tree_size(root: Path) -> tuple[int, int]:
    if not root.is_dir() or root.is_symlink():
        return 0, 0
    total = files = 0
    for folder, _directories, names in os.walk(root, followlinks=False):
        for name in names:
            info = os.lstat(os.path.join(folder, name))
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
                files += 1
    return total, files


def purge_all(home: str | Path, confirm: str) -> dict:
    """Delete tandem.db (+WAL/SHM/journal), the raw archive and derived caches in ``home``.

    Every check runs before the first deletion: a wrong confirmation, a symlink anywhere in
    the deletion set, a path that resolves outside ``home`` or an active import all refuse
    without touching any file. Other files in ``home`` (e.g. catalog.db) are kept.
    """
    if confirm != PURGE_CONFIRMATION:
        raise PurgeRefused(f"confirmation must be exactly {PURGE_CONFIRMATION!r}")
    given = Path(home).expanduser()
    if given.is_symlink():
        raise PurgeRefused("data home must not be a symbolic link")
    if not given.is_dir():
        raise PurgeRefused("data home does not exist")
    root = given.resolve(strict=True)
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise PurgeRefused("refusing to purge a filesystem root or the user home directory")
    if not (root / "tandem.db").exists() and not (root / "raw").exists():
        raise PurgeRefused("not a Tandem data home (no tandem.db or raw/)")

    files: list[Path] = []
    directories: list[Path] = []
    for name in (*DB_FILES, *CACHE_FILES):
        path = root / name
        if os.path.lexists(path):
            _check_inside(root, path)
            if not path.is_file():
                raise PurgeRefused(f"{name} is not a regular file")
            files.append(path)
    raw = root / "raw"
    if os.path.lexists(raw):
        _check_inside(root, raw)
        if not raw.is_dir():
            raise PurgeRefused("raw is not a directory")
        for folder, names, entries in os.walk(raw, followlinks=False):
            for name in (*names, *entries):
                path = Path(folder) / name
                _check_inside(raw.resolve(), path)
                if name in entries:
                    files.append(path)
            directories.append(Path(folder))

    lock = os.open(root / "import.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("An import worker is active; stop it before purging") from error
        deleted = 0
        for path in files:
            deleted += path.lstat().st_size
            path.unlink()
        for folder in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            folder.rmdir()
    finally:
        os.close(lock)
    return {
        "home": str(root),
        "deleted_files": len(files),
        "deleted_bytes": deleted,
        "kept": sorted(path.name for path in root.iterdir()),
    }


def _check_inside(root: Path, path: Path) -> None:
    if path.is_symlink():
        raise PurgeRefused(f"refusing to follow symbolic link {path}")
    if not path.resolve().is_relative_to(root):
        raise PurgeRefused(f"{path} resolves outside the data home")
