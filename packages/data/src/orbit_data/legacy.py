"""Data written under the old working name Tandem (up to v0.0.3): read it, then move it once.

orbit-rename: keep-file — this module names the legacy identifiers on purpose.

Everything here is idempotent and never overwrites an Orbit file. The old data directory is
moved, not copied, and a link is left at the old path: hooks installed before the rename write
to absolute paths under it (``hooks/events.jsonl``), and the install ledger restores backups
from there.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ENV_PREFIX = "TANDEM_"
APP_DIR = "Tandem"
CONTRACT_ID = "tandem-session-v1"
AI_MARKER = "[tandem-analysis v1"
AI_MARKER_FILE = ".tandem-ai"
COLLECT_SPEC_ID = "tandem-collect"
HOOKS_TOKEN = "tandem.hooks"
# The old database and its SQLite side files, renamed together while nothing has them open.
HOME_FILES = {f"tandem.db{s}": f"orbit.db{s}" for s in ("", "-wal", "-shm", "-journal")}
CATALOG_SOURCES = {"tandem-seeds": "orbit-seeds", "tandem-kb": "orbit-kb"}


def adopt_env(environ=os.environ) -> None:
    """``TANDEM_X`` still configures Orbit when ``ORBIT_X`` is not set."""
    for key, value in list(environ.items()):
        if key.startswith(ENV_PREFIX):
            environ.setdefault("ORBIT_" + key[len(ENV_PREFIX) :], value)


def move_app_dir(home: Path) -> None:
    """``Application Support/Tandem`` becomes ``Application Support/Orbit`` (default home only)."""
    old = home.parent / APP_DIR
    if home.exists() or home.is_symlink() or old.is_symlink() or not old.is_dir():
        return
    try:
        old.rename(home)
        old.symlink_to(home.name)
    except OSError:
        pass  # Another process got there first, or the folder is not ours to move: use it as found.


def migrate_home(home: Path) -> None:
    """Rename the files inside a data home that carried the old name."""
    home = Path(home)
    if not home.is_dir():
        return
    if not (home / "orbit.db").exists():
        for old, new in HOME_FILES.items():
            if (home / old).exists() and not (home / new).exists():
                (home / old).rename(home / new)
    cwd = home / "agent-cwd"
    if (cwd / AI_MARKER_FILE).is_file() and not (cwd / ".orbit-ai").exists():
        (cwd / AI_MARKER_FILE).rename(cwd / ".orbit-ai")


def upgrade_manifest(db: sqlite3.Connection, contract_id: str) -> None:
    """The canonical store's manifest names the contract; rewrite the old id in place."""
    db.execute(
        "UPDATE schema_manifest SET contract_id=? WHERE contract_id=?", (contract_id, CONTRACT_ID)
    )


def upgrade_artifact(value):
    """An AI artifact saved before the rename addresses its hook files and rule blocks by the old name."""
    if not isinstance(value, str):
        return value
    return value.replace(HOOKS_TOKEN, "orbit.hooks").replace("tandem:rule", "orbit:rule")


def has_catalog_sources(conn: sqlite3.Connection) -> bool:
    marks = ",".join("?" * len(CATALOG_SOURCES))
    return (
        conn.execute(
            f"SELECT 1 FROM catalog_source WHERE source_id IN ({marks})", tuple(CATALOG_SOURCES)
        ).fetchone()
        is not None
    )


def rename_catalog_sources(conn: sqlite3.Connection) -> None:
    """Bundled catalog sources keep their items, sync history and links under the new ids.

    Runs on a connection without foreign-key enforcement, inside one transaction.
    """
    for old, new in CATALOG_SOURCES.items():
        if not conn.execute("SELECT 1 FROM catalog_source WHERE source_id=?", (old,)).fetchone():
            continue
        if conn.execute("SELECT 1 FROM catalog_source WHERE source_id=?", (new,)).fetchone():
            conn.execute("DELETE FROM catalog_source WHERE source_id=?", (old,))
        else:
            conn.execute(
                "UPDATE catalog_source SET source_id=?, spec=replace(spec, ?, ?) WHERE source_id=?",
                (new, f'"{old}"', f'"{new}"', old),
            )
        conn.execute("UPDATE sync_run SET source_id=? WHERE source_id=?", (new, old))
        conn.execute("UPDATE OR IGNORE item_source SET source_id=? WHERE source_id=?", (new, old))
        conn.execute("DELETE FROM item_source WHERE source_id=?", (old,))
