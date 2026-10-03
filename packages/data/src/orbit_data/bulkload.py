"""Bulk-load mode for large projection rebuilds (first import of a source).

Inserting rows with random hash keys into tables that carry many secondary indexes makes
the single writer update each index B-tree row by row. When a rebuild is about to write at
least as many events as the database already holds (always true for the first import on a
new library), it is cheaper to drop those indexes inside the rebuild transaction and
recreate them with one sorted build each once the rows are written.

Safety: everything happens inside the caller's write transaction. A failure rolls back
the DROP statements too, so readers never see a library without its indexes, and the
recreated indexes use the exact ``sqlite_master`` text so the schema is unchanged.
Indexes needed by lookups during the rebuild are kept or restored before they are used.
"""

from __future__ import annotations

# Secondary indexes on rows a rebuild writes in bulk that no lookup needs while mapping.
# Kept: native-key indexes (mappers resolve parents by them) and child-key indexes that
# SQLite scans when a parent row is inserted while deferred foreign keys are pending
# (event.turn_uid during derivation).
DEFERRABLE = (
    "fk_event_record_uid",
    "event_by_kind_time",
    "event_by_parent_set",
    "evidence_by_event",
    "fk_event_context_project_id",
)
# Read by retained-row handling and derivation (session order, record joins).
AFTER_MAP = ("fk_event_record_uid",)


class DeferredIndexes:
    def __init__(self, db, definitions):
        self.db = db
        self.definitions = definitions  # name -> CREATE INDEX text, schema order

    @classmethod
    def start(cls, db, *, incoming: int):
        """Drop secondary indexes when ``incoming`` rows outnumber existing events."""
        if not db.in_transaction or incoming <= 0:
            return None
        existing = db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        if existing > incoming:
            return None  # Incremental maintenance is cheaper than rebuilding the index.
        placeholders = ",".join("?" for _ in DEFERRABLE)
        definitions = {
            name: sql
            for name, sql in db.execute(
                "SELECT name,sql FROM main.sqlite_master WHERE type='index' AND sql IS NOT NULL "
                f"AND name IN ({placeholders}) ORDER BY rowid",
                DEFERRABLE,
            )
        }
        if not definitions:
            return None
        for name in definitions:
            db.execute(f'DROP INDEX main."{name}"')
        return cls(db, definitions)

    def restore(self, names=None):
        """Recreate ``names`` (default: every index still deferred)."""
        for name in list(self.definitions):
            if names is None or name in names:
                self.db.execute(self.definitions.pop(name))
