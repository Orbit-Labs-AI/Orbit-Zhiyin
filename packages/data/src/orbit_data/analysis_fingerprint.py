"""Cheap change fingerprints for derived analysis caches.

One aggregate query returns a fingerprint per root session tree. A tree fingerprint changes
when rows are added to or removed from a member session (event, tool call, model call), when
a session's rowid span or max(seq) changes, when member session metadata changes, or when the
projection's mapper/reducer versions change. Rowids enter as per-session spans
(max - min): re-projecting a source deletes and re-inserts every tree in it, which shifts
unchanged trees as a block; a shift alone is not a change. Log sources are append-only; an
in-place rewrite that keeps counts, spans and seq identical is not detected (that would need
reading payload pages on every request). Fingerprints never read text or payload columns.
"""

from __future__ import annotations

import hashlib
import json
import os
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
  SELECT session_uid, count(*) AS n, max(rowid) - min(rowid) AS r, max(seq) AS q,
         min(ts) AS lo, max(ts) AS hi, sum(ts IS NULL) AS untimed
  FROM event GROUP BY session_uid
), tc AS (
  SELECT session_uid, count(*) AS n, max(rowid) - min(rowid) AS r FROM tool_call GROUP BY session_uid
), mc AS (
  SELECT session_uid, count(*) AS n, max(rowid) - min(rowid) AS r FROM model_call GROUP BY session_uid
)
SELECT s.root_uid AS root_uid,
       count(*) AS sessions,
       total(ev.n) AS events, total(ev.r) AS event_span, max(ev.q) AS max_seq,
       min(ev.lo) AS min_ts, max(ev.hi) AS max_ts, total(ev.untimed) AS untimed_events,
       total(tc.n) AS tool_calls, total(tc.r) AS tool_span,
       total(mc.n) AS model_calls, total(mc.r) AS model_span,
       group_concat({members}, char(30)) AS members,
       group_concat(s.session_uid, char(30)) AS session_uids,
       group_concat(coalesce(s.project_id, char(31)), char(30)) AS project_ids,
       group_concat(s.source_id, char(30)) AS source_ids
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


def _tree(row, mapper: tuple) -> TreeFingerprint:
    # Hash the member JSON texts as SQLite rendered them (deterministic column order);
    # decoding them per request would dominate the fingerprint cost.
    counts = (
        row["sessions"],
        mapper,
        int(row["events"]),
        int(row["event_span"]),
        row["max_seq"],
        row["min_ts"],
        row["max_ts"],
        int(row["untimed_events"]),
        int(row["tool_calls"]),
        int(row["tool_span"]),
        int(row["model_calls"]),
        int(row["model_span"]),
    )
    text = (
        repr((FINGERPRINT_VERSION, counts))
        + "\x1d"
        + "\x1e".join(sorted(row["members"].split("\x1e")))
    )
    fp = hashlib.sha256(text.encode("utf-8")).hexdigest()
    projects = {None if p == "\x1f" else p for p in row["project_ids"].split("\x1e")}
    return TreeFingerprint(
        root_uid=row["root_uid"],
        fp=fp,
        session_uids=tuple(sorted(row["session_uids"].split("\x1e"))),
        project_ids=tuple(sorted(projects, key=lambda v: (v is None, v or ""))),
        source_ids=tuple(sorted(set(row["source_ids"].split("\x1e")))),
        min_ts=row["min_ts"],
        max_ts=row["max_ts"],
        untimed_events=int(row["untimed_events"]),
        events=int(row["events"]),
    )


def read_fingerprints(connection) -> Fingerprints:
    """Read all tree fingerprints and the global identity from an open connection."""
    latest = connection.execute(
        "SELECT run_id, mapper_version, reducer_version FROM projection_run"
        " ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    run = latest[0] if latest else None
    mapper = tuple(latest[1:]) if latest else ()
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
        tree = _tree(row, mapper)
        trees[tree.root_uid] = tree
    return Fingerprints(run, digest(global_parts), trees)


# Last fingerprint per database, reused while no write has touched the files. Reading
# fingerprints scans every event row; on a real home (770k events) that is 0.7 s with a
# warm page cache and 38 s under memory pressure, and every analysis task (cache hits
# included) starts with it.
_MEMO: dict[str, tuple[tuple, Fingerprints]] = {}


def _stamp(path: Path) -> tuple:
    """(mtime_ns, size) of the database and its WAL: every commit grows the WAL or, at a
    checkpoint, rewrites the database. An empty WAL (a reader opening the file creates one)
    counts as no WAL."""
    stamp = []
    for name in (path, path.with_name(path.name + "-wal")):
        try:
            info = os.stat(name)
        except OSError:
            stamp.append(None)
            continue
        empty_wal = name is not path and info.st_size == 0
        stamp.append(None if empty_wal else (info.st_mtime_ns, info.st_size))
    return tuple(stamp)


def fingerprints(home: str | Path) -> Fingerprints:
    """Open the canonical database read-only and fingerprint it in one transaction
    (memoized until the database or its WAL changes)."""
    path = (Path(home) / "orbit.db").resolve()
    key, before = f"{FINGERPRINT_VERSION}:{path}", _stamp(path)
    cached = _MEMO.get(key)
    if cached is not None and cached[0] == before:
        return cached[1]
    with readonly_connection(path) as connection:
        connection.execute("BEGIN")
        try:
            result = read_fingerprints(connection)
        finally:
            connection.rollback()
    if _stamp(path) == before:  # nothing committed while reading
        _MEMO[key] = (before, result)
    return result


def known_sessions(home: str | Path, session_uids: Iterable[str]) -> set[str]:
    """Return which of the given session UIDs exist in the canonical database."""
    wanted = sorted(set(session_uids))
    if not wanted:
        return set()
    with readonly_connection(Path(home) / "orbit.db") as connection:
        rows = connection.execute(
            "SELECT session_uid FROM session WHERE session_uid IN (SELECT value FROM json_each(?))",
            (json.dumps(wanted),),
        ).fetchall()
    return {row[0] for row in rows}
