"""Cheap change fingerprints for derived analysis caches.

One aggregate query returns a fingerprint per root session tree. A tree fingerprint changes
whenever rows are added to, or replaced in, any member session (event, tool call, model call)
or when member session metadata changes. Fingerprints never read text or payload columns.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .store import readonly_connection

FINGERPRINT_VERSION = "analysis-fingerprint-v1"

# Per-session aggregates first, then one GROUP BY root_uid over the session table.
# ``{members}`` is a json_object over every session column, so in-place metadata
# updates (title, status, repository fields ...) also change the tree fingerprint.
# The aggregates use the (session_uid, seq) unique index and the projection foreign-key
# indexes, so no payload pages are read.
TREE_SQL = """
WITH ev AS (
  SELECT session_uid, count(*) AS n, max(rowid) AS r, max(seq) AS q,
         min(ts) AS lo, max(ts) AS hi, sum(ts IS NULL) AS untimed
  FROM event GROUP BY session_uid
), tc AS (
  SELECT session_uid, count(*) AS n, max(rowid) AS r FROM tool_call GROUP BY session_uid
), mc AS (
  SELECT session_uid, count(*) AS n, max(rowid) AS r FROM model_call GROUP BY session_uid
)
SELECT s.root_uid AS root_uid,
       count(*) AS sessions, max(s.rowid) AS session_rowid,
       total(ev.n) AS events, max(ev.r) AS event_rowid, max(ev.q) AS max_seq,
       min(ev.lo) AS min_ts, max(ev.hi) AS max_ts, total(ev.untimed) AS untimed_events,
       total(tc.n) AS tool_calls, max(tc.r) AS tool_rowid,
       total(mc.n) AS model_calls, max(mc.r) AS model_rowid,
       group_concat({members}, char(30)) AS members
FROM session s
LEFT JOIN ev USING(session_uid)
LEFT JOIN tc USING(session_uid)
LEFT JOIN mc USING(session_uid)
GROUP BY s.root_uid
"""

# Tables outside session trees that still change analysis results (names, aliases, inventory).
GLOBAL_TABLES = (
    "project",
    "project_override",
    "model_alias",
    "source",
    "inventory_scan",
    "inventory_item",
)


def digest(*parts: Any) -> str:
    """Stable SHA-256 of JSON-encodable parts; sets must be sorted by the caller."""
    data = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TreeFingerprint:
    """Change identity and selection hints for one root session tree."""

    root_uid: str
    fp: str
    session_uids: tuple[str, ...]
    project_ids: tuple[str | None, ...]
    source_ids: tuple[str, ...]
    min_ts: int | None
    max_ts: int | None
    untimed_events: int
    events: int


@dataclass(frozen=True)
class Fingerprints:
    """Database-wide fingerprints read inside one read transaction."""

    projection_run_id: int | None
    global_fp: str
    trees: Mapping[str, TreeFingerprint] = field(default_factory=dict)

    def root_of(self) -> dict[str, str]:
        """Map every member session to its tree root."""
        return {sid: root for root, tree in self.trees.items() for sid in tree.session_uids}

    def input_fp(self, roots: Iterable[str] | None = None) -> str:
        """Hash the selected trees (all trees when None) with the global projection identity."""
        selected = sorted(self.trees if roots is None else set(roots) & set(self.trees))
        return digest(
            FINGERPRINT_VERSION,
            self.projection_run_id,
            self.global_fp,
            [(root, self.trees[root].fp) for root in selected],
        )


def _tree(row) -> TreeFingerprint:
    members = sorted(
        (json.loads(text) for text in row["members"].split("\x1e")),
        key=lambda member: member["session_uid"],
    )
    counts = (
        row["sessions"],
        row["session_rowid"],
        int(row["events"]),
        row["event_rowid"],
        row["max_seq"],
        row["min_ts"],
        row["max_ts"],
        int(row["untimed_events"]),
        int(row["tool_calls"]),
        row["tool_rowid"],
        int(row["model_calls"]),
        row["model_rowid"],
    )
    projects = {member.get("project_id") for member in members}
    return TreeFingerprint(
        root_uid=row["root_uid"],
        fp=digest(FINGERPRINT_VERSION, counts, members),
        session_uids=tuple(member["session_uid"] for member in members),
        project_ids=tuple(sorted(projects, key=lambda v: (v is None, v or ""))),
        source_ids=tuple(sorted({member.get("source_id") for member in members})),
        min_ts=row["min_ts"],
        max_ts=row["max_ts"],
        untimed_events=int(row["untimed_events"]),
        events=int(row["events"]),
    )


def read_fingerprints(connection) -> Fingerprints:
    """Read all tree fingerprints and the global identity from an open connection."""
    run = connection.execute("SELECT max(run_id) FROM projection_run").fetchone()[0]
    existing = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    global_parts = [
        (name, *connection.execute(f'SELECT count(*), max(rowid) FROM "{name}"').fetchone())
        for name in GLOBAL_TABLES
        if name in existing
    ]
    columns = [row[1] for row in connection.execute('PRAGMA table_info("session")')]
    members = "json_object(" + ",".join(f"'{c}',s.\"{c}\"" for c in columns) + ")"
    trees = {}
    for row in connection.execute(TREE_SQL.format(members=members)):
        tree = _tree(row)
        trees[tree.root_uid] = tree
    return Fingerprints(run, digest(global_parts), trees)


def fingerprints(home: str | Path) -> Fingerprints:
    """Open the canonical database read-only and fingerprint it in one transaction."""
    with readonly_connection(Path(home) / "tandem.db") as connection:
        connection.execute("BEGIN")
        try:
            return read_fingerprints(connection)
        finally:
            connection.rollback()


def known_sessions(home: str | Path, session_uids: Iterable[str]) -> set[str]:
    """Return which of the given session UIDs exist in the canonical database."""
    wanted = sorted(set(session_uids))
    if not wanted:
        return set()
    with readonly_connection(Path(home) / "tandem.db") as connection:
        rows = connection.execute(
            "SELECT session_uid FROM session WHERE session_uid IN (SELECT value FROM json_each(?))",
            (json.dumps(wanted),),
        ).fetchall()
    return {row[0] for row in rows}
