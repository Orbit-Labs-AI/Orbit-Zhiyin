"""Ordered, versioned upgrades for tables an older app.db already has.

The module DDL files only *create* (``CREATE TABLE IF NOT EXISTS``), so a column added to a
DDL file never reaches an existing user's table. Each change to an existing table is
therefore also one numbered step here. ``schema_version(module, version)`` records the last
step applied per module; steps run in order, each in its own write transaction together
with its version bump, so a crash leaves the database at a whole step.

Steps must be idempotent with respect to the DDL: on a fresh database the DDL already
created the latest shape, so every step checks before it alters (``add_column`` does).
Indexes on a migrated column belong in the step, not in the DDL file (the DDL replays
before the steps and would fail on an old table).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

Step = Callable[[sqlite3.Connection], None]


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def add_column(table: str, column: str, decl: str) -> Step:
    """Step: ``ALTER TABLE … ADD COLUMN`` unless the table is absent or already has it."""

    def step(db: sqlite3.Connection) -> None:
        have = columns(db, table)
        if have and column not in have:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    step.__name__ = f"add_column_{table}_{column}"
    return step


# module -> steps; version n means steps[:n] are applied. Append only, never reorder.
MIGRATIONS: dict[str, list[Step]] = {
    "install": [
        add_column("install_ledger", "inv_id", "TEXT"),
        add_column("install_ledger", "catalog_item_id", "TEXT"),
    ],
}


def apply(appdb, migrations: dict[str, list[Step]] | None = None) -> dict[str, int]:
    """Run pending steps; returns {module: version} after the run."""
    migrations = MIGRATIONS if migrations is None else migrations
    with appdb.write() as db:
        db.execute("CREATE TABLE IF NOT EXISTS schema_version (module TEXT PRIMARY KEY, "
                   "version INTEGER NOT NULL, applied_at INTEGER NOT NULL) STRICT")
        current = dict(db.execute("SELECT module, version FROM schema_version").fetchall())
    for module, steps in migrations.items():
        done = current.get(module, 0)
        if done > len(steps):
            raise RuntimeError(f"app.db {module} schema v{done} is newer than this build (v{len(steps)})")
        for n in range(done, len(steps)):
            with appdb.write() as db:
                steps[n](db)
                db.execute("INSERT INTO schema_version VALUES (?, ?, ?) ON CONFLICT(module) DO UPDATE "
                           "SET version = excluded.version, applied_at = excluded.applied_at",
                           (module, n + 1, int(time.time() * 1000)))
        current[module] = len(steps)
    return current
