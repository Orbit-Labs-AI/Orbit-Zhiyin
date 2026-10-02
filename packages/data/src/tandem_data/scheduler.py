"""What to rebuild and when: session-closure increments, progressive first import, pause.

A change is projected by rebuilding the *closure* of the sessions it touches: every
file and session connected through L1 session ownership, L2 evidence links, event
parent links and L3 lineage (parent, fork, root). Guards inside the rebuild escalate
to a larger closure, and finally to the whole source, whenever a mapped record
reaches an event or session outside the closure. Results therefore equal a full
rebuild of the source; the closure only bounds the work.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tandem_data import MAPPER_VERSION, REDUCER_VERSION
from tandem_data.contract import now_ms
from tandem_data.privacy import REDACTION_VERSION
from tandem_data.source_reader import source_path

CLOSURE_AGENTS = frozenset({"claude_code", "pi", "dsh"})
MAX_CLOSURE_FRACTION = 0.3
MAX_ESCALATIONS = 4
STALE_FILES = (
    "SELECT f.file_id,f.source_id FROM source_file f WHERE "
    "COALESCE(json_extract(watermark,'$.projected_revision'),-1) <> COALESCE(json_extract(watermark,'$.revision'),0) "
    "OR COALESCE(json_extract(watermark,'$.mapper_version'),'')<>? "
    "OR COALESCE(json_extract(watermark,'$.reducer_version'),'')<>? "
    "OR COALESCE(json_extract(watermark,'$.redaction_version'),'')<>?"
)


class ScopeEscalation(Exception):  # noqa: N818 - control flow inside one rebuild
    """The closure missed a dependency; retry with these sessions included."""

    def __init__(self, sessions, reason):
        self.sessions = {s for s in sessions if s}
        super().__init__(reason)


class _NoRetained:
    files: dict = {}

    def restore(self, *_):
        pass

    def finish(self, *_):
        pass


@dataclass(frozen=True)
class ClosureScope:
    source_ids: tuple
    files: frozenset
    sessions: frozenset
    agent: str
    sessions_sql = "SELECT session_uid FROM rebuild_sessions"
    files_sql = "SELECT file_id FROM rebuild_files"

    def install(self, db):
        db.execute("CREATE TEMP TABLE IF NOT EXISTS rebuild_files(file_id TEXT PRIMARY KEY)")
        db.execute("CREATE TEMP TABLE IF NOT EXISTS rebuild_sessions(session_uid TEXT PRIMARY KEY)")
        db.execute("DELETE FROM rebuild_files")
        db.execute("DELETE FROM rebuild_sessions")
        db.executemany("INSERT INTO rebuild_files VALUES(?)", ((f,) for f in sorted(self.files)))
        db.executemany(
            "INSERT INTO rebuild_sessions VALUES(?)", ((s,) for s in sorted(self.sessions))
        )
        return self.sessions_sql, self.files_sql

    def retained(self):
        return _NoRetained()

    def delete_issues(self, db):
        db.execute(
            "DELETE FROM ingest_issue WHERE stage IN ('l2','l3') AND (file_id IN rebuild_files OR "
            "record_uid IN (SELECT record_uid FROM raw_record WHERE file_id IN rebuild_files))"
        )

    def check_existing(self, db, existing):
        owner = db.execute(
            "SELECT file_id FROM raw_record WHERE record_uid=?", (existing["record_uid"],)
        ).fetchone()
        if owner is None or owner[0] not in self.files:
            raise ScopeEscalation({existing["session_uid"]}, "event owned outside the closure")

    def check_parent_key(self, db, native_key):
        row = db.execute(
            "SELECT e.session_uid,r.file_id FROM event e JOIN raw_record r USING(record_uid) "
            "WHERE e.native_key=? LIMIT 1",
            (native_key,),
        ).fetchone()
        if row and row[1] not in self.files:
            raise ScopeEscalation({row[0]}, "parent event outside the closure")

    def before_derive(self, db):
        db.execute(
            "INSERT OR IGNORE INTO rebuild_sessions SELECT DISTINCT session_uid FROM raw_record "
            "WHERE file_id IN rebuild_files AND session_uid IS NOT NULL"
        )
        db.execute(
            "INSERT OR IGNORE INTO rebuild_sessions SELECT DISTINCT e.session_uid FROM raw_record r "
            "JOIN record_event x ON x.record_uid=r.record_uid JOIN event e ON e.event_uid=x.event_uid "
            "WHERE r.file_id IN rebuild_files"
        )
        outside = {
            row[0]
            for row in db.execute(
                "SELECT DISTINCT e.session_uid FROM event e JOIN raw_record r ON r.record_uid=e.record_uid "
                "WHERE e.session_uid IN rebuild_sessions AND r.file_id NOT IN rebuild_files"
            )
        }
        if outside:
            raise ScopeEscalation(outside, "session shared with files outside the closure")
        parents = {
            row[0]
            for row in db.execute(
                "SELECT DISTINCT json_extract(attrs,'$.parent_uid') FROM event WHERE session_uid IN rebuild_sessions "
                "AND kind IN ('session.meta','setting.change') AND json_extract(attrs,'$.parent_uid') IS NOT NULL "
                "AND json_extract(attrs,'$.parent_uid') NOT IN rebuild_sessions"
            )
        }
        lineage = {
            parent
            for parent in parents
            if db.execute("SELECT 1 FROM event WHERE session_uid=? LIMIT 1", (parent,)).fetchone()
        }
        lineage.update(
            row[0]
            for row in db.execute(
                "SELECT session_uid FROM session WHERE session_uid NOT IN rebuild_sessions AND "
                "(parent_uid IN rebuild_sessions OR forked_from IN rebuild_sessions OR root_uid IN rebuild_sessions)"
            )
        )
        if self.agent == "pi":
            root = db.execute(
                "SELECT root_path FROM source WHERE source_id=?", (self.source_ids[0],)
            ).fetchone()[0]
            paths = {
                row[0]
                for row in db.execute(
                    "SELECT relative_path FROM source_file WHERE file_id IN rebuild_files"
                )
            }
            for session_uid, parent in db.execute(
                "SELECT session_uid,json_extract(attrs,'$.fork_parent_path') FROM event "
                "WHERE kind='session.meta' AND session_uid NOT IN rebuild_sessions "
                "AND json_extract(attrs,'$.fork_parent_path') IS NOT NULL"
            ):
                path = Path(parent)
                relative = str(path.relative_to(root)) if path.is_relative_to(root) else parent
                if relative in paths:
                    lineage.add(session_uid)
        if lineage:
            raise ScopeEscalation(lineage, "lineage crosses the closure")


def stale_files(db):
    stale = {}
    for file_id, source_id in db.execute(
        STALE_FILES, (MAPPER_VERSION, REDUCER_VERSION, REDACTION_VERSION)
    ):
        stale.setdefault(source_id, set()).add(file_id)
    return stale


def closure(store, source_id, files, extra_sessions=(), max_fraction=MAX_CLOSURE_FRACTION):
    """Session closure of changed files, or None when the whole source must be rebuilt."""
    db = store.db
    source = db.execute(
        "SELECT agent,root_path FROM source WHERE source_id=?", (source_id,)
    ).fetchone()
    if source is None or source["agent"] not in CLOSURE_AGENTS:
        return None
    if not db.execute("SELECT 1 FROM projection_run LIMIT 1").fetchone():
        return None
    if db.execute(
        "SELECT 1 FROM ingest_issue WHERE source_id=? AND stage IN ('l2','l3') "
        "AND file_id IS NULL AND record_uid IS NULL LIMIT 1",
        (source_id,),
    ).fetchone():
        return None  # Source-wide findings are only recomputed by a full source rebuild.
    total = db.execute(
        "SELECT COUNT(*) FROM source_file WHERE source_id=?", (source_id,)
    ).fetchone()[0]
    limit = max_fraction * total
    files, sessions = set(files), set(extra_sessions)
    db.execute("CREATE TEMP TABLE IF NOT EXISTS closure_files(file_id TEXT PRIMARY KEY)")
    db.execute("CREATE TEMP TABLE IF NOT EXISTS closure_sessions(session_uid TEXT PRIMARY KEY)")
    try:
        while True:
            if len(files) > limit:
                return None
            db.execute("DELETE FROM closure_files")
            db.execute("DELETE FROM closure_sessions")
            db.executemany("INSERT INTO closure_files VALUES(?)", ((f,) for f in files))
            db.executemany("INSERT INTO closure_sessions VALUES(?)", ((s,) for s in sessions))
            found = set(sessions)
            for sql in (
                "SELECT DISTINCT session_uid FROM raw_record WHERE file_id IN closure_files AND session_uid IS NOT NULL",
                "SELECT DISTINCT e.session_uid FROM raw_record r JOIN record_event x ON x.record_uid=r.record_uid "
                "JOIN event e ON e.event_uid=x.event_uid WHERE r.file_id IN closure_files",
                "SELECT DISTINCT c.session_uid FROM event p JOIN event c ON c.parent_uid=p.event_uid "
                "WHERE p.session_uid IN closure_sessions",
                "SELECT DISTINCT p.session_uid FROM event c JOIN event p ON p.event_uid=c.parent_uid "
                "WHERE c.session_uid IN closure_sessions",
            ):
                found.update(row[0] for row in db.execute(sql))
            for row in db.execute(
                "SELECT session_uid,parent_uid,forked_from,root_uid FROM session WHERE "
                "session_uid IN closure_sessions OR parent_uid IN closure_sessions OR "
                "forked_from IN closure_sessions OR root_uid IN closure_sessions"
            ):
                found.update(value for value in row if value)
            db.executemany(
                "INSERT OR IGNORE INTO closure_sessions VALUES(?)", ((s,) for s in found)
            )
            grown = set(files)
            for sql in (
                "SELECT DISTINCT file_id FROM raw_record WHERE session_uid IN closure_sessions",
                "SELECT DISTINCT r.file_id FROM event e JOIN record_event x ON x.event_uid=e.event_uid "
                "JOIN raw_record r ON r.record_uid=x.record_uid WHERE e.session_uid IN closure_sessions",
            ):
                grown.update(row[0] for row in db.execute(sql))
            if found == sessions and grown == files:
                break
            files, sessions = grown, found
    finally:
        db.execute("DELETE FROM closure_files")
        db.execute("DELETE FROM closure_sessions")
    rows = db.execute(
        "SELECT f.file_id,f.source_id,f.status,f.relative_path,(SELECT archive_uid FROM source_revision v "
        "WHERE v.file_id=f.file_id ORDER BY revision DESC LIMIT 1) AS archive_uid FROM source_file f "
        f"WHERE f.file_id IN ({','.join('?' * len(files))})",
        sorted(files),
    ).fetchall()
    for row in rows:
        if row["source_id"] != source_id or row["status"] != "active" or row["archive_uid"]:
            return None  # Retained, archived or foreign evidence: rebuild the whole source.
        if not source_path(source["root_path"], row["relative_path"]).exists():
            return None
    if len(rows) != len(files):
        return None
    return ClosureScope((source_id,), frozenset(files), frozenset(sessions), source["agent"])


def project(store, *, workers, pool=None, progress=None, max_fraction=MAX_CLOSURE_FRACTION):
    """Publish every stale file, preferring session closures over whole sources."""
    from tandem_data.pipeline import rebuild

    stale = stale_files(store.db)
    result = None
    try:
        if not stale:
            return rebuild(store, source_ids=set(), progress=progress, workers=workers, pool=pool)
        for source_id in sorted(stale):
            extra = set()
            for _ in range(MAX_ESCALATIONS):
                scope = closure(store, source_id, stale[source_id], extra, max_fraction)
                if scope is None:
                    break
                try:
                    result = rebuild(
                        store, scope=scope, progress=progress, workers=workers, pool=pool
                    )
                    result["scope"] = {"files": len(scope.files), "kind": "closure"}
                    break
                except ScopeEscalation as escalation:
                    extra |= set(scope.sessions) | escalation.sessions
                    store._unavailable_files = set()
            else:
                scope = None
            if scope is None:
                with _join_batch(store):
                    result = rebuild(
                        store, source_ids={source_id}, progress=progress, workers=workers, pool=pool
                    )
                result["scope"] = {"kind": "source"}
        return result
    finally:
        store._unavailable_files = set()


def mark_missing(store, source_id, seen):
    """A newly missing indexed file is re-projected so its facts become retained facts."""
    store.db.executemany(
        "UPDATE source_file SET status='gone_upstream',watermark=json_remove(watermark,'$.projected_revision') "
        "WHERE file_id=? AND status='active'",
        (
            (row[0],)
            for row in store.db.execute(
                "SELECT file_id,relative_path FROM source_file WHERE source_id=?", (source_id,)
            ).fetchall()
            if row[1] not in seen
        ),
    )


# --- pause / resume (DT-02.1) ------------------------------------------------


def _collection_path(home):
    return Path(home) / "collection.json"


def collection_state(home) -> dict:
    try:
        state = json.loads(_collection_path(home).read_text())
    except (OSError, ValueError):
        return {"paused": False}
    return state if isinstance(state, dict) else {"paused": False}


def _write_state(home, state):
    handle, temporary = tempfile.mkstemp(dir=home, prefix=".collection-")
    with os.fdopen(handle, "w") as out:
        json.dump(state, out, sort_keys=True)
    os.chmod(temporary, 0o600)
    os.replace(temporary, _collection_path(home))


def pause(home) -> dict:
    state = {**collection_state(home), "paused": True, "paused_at": now_ms()}
    _write_state(home, state)
    return state


def resume(home) -> dict:
    state = {**collection_state(home), "paused": False, "resumed_at": now_ms()}
    _write_state(home, state)
    return state


def paused(home) -> bool:
    return bool(collection_state(home).get("paused"))


# --- progressive first import -------------------------------------------------


def session_group(agent, relative):
    """Files that normally describe one session are captured in the same batch."""
    path = PurePosixPath(relative)
    if agent == "claude_code":
        parts = path.parts
        if "subagents" in parts:
            return str(PurePosixPath(*parts[: parts.index("subagents")]))
        name = path.name.removesuffix(".jsonl").removesuffix(".meta.json").removesuffix(".json")
        return str(path.with_name(name))
    if agent == "dsh":
        return str(path.parent)
    return relative


@contextmanager
def _join_batch(store):
    """Inside a batch, run a whole-source rebuild in the batch transaction itself.

    A savepoint around a rebuild makes it several times slower (profiled: event and
    record inserts dominate while a savepoint is open). Only closure rebuilds need one,
    to retry after a ScopeEscalation; a failed source rebuild already aborts the whole
    batch, whose ROLLBACK discards its writes.
    """
    savepoint = store.__dict__.get("transaction")
    if savepoint is None:  # Not inside batch_transaction: the store's own transaction.
        yield
        return
    store.transaction = contextlib.nullcontext
    try:
        yield
    finally:
        store.transaction = savepoint


@contextmanager
def batch_transaction(store):
    """One write transaction for a whole batch; inner transactions become savepoints."""
    names = itertools.count()

    @contextmanager
    def savepoint():
        name = f"tandem_batch_{next(names)}"
        store.db.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            store.db.execute(f"ROLLBACK TO {name}")
            store.db.execute(f"RELEASE {name}")
            raise
        store.db.execute(f"RELEASE {name}")

    store.db.execute("BEGIN IMMEDIATE")
    store.db.execute("PRAGMA defer_foreign_keys = ON")
    store.transaction = savepoint
    try:
        yield
        store.db.execute("COMMIT")
    except BaseException:
        store.db.execute("ROLLBACK")
        raise
    finally:
        del store.transaction


FIRST_BATCH_BYTES = 6_000_000


def plan_batches(entries, *, first_sessions, first_days, first_bytes=FIRST_BATCH_BYTES, now):
    """Newest groups first: a small first batch, then one batch per source.

    The first batch is bounded by source bytes (a proxy for event volume and so for
    time to first read), by ``first_sessions`` and by recency, and always holds at
    least the newest group. Every later batch is the remainder of one source, so each
    source is projected once more as a whole instead of once per small batch.
    """
    groups = {}
    for entry in entries:
        groups.setdefault(entry["group"], []).append(entry)
    ordered = sorted(
        groups.values(),
        key=lambda members: (-max(m["mtime"] for m in members), members[0]["group"]),
    )
    recent = now - first_days * 86_400
    first, size = [], 0
    for members in ordered:
        grown = size + sum(m.get("size", 0) for m in members)
        if first and (
            len(first) >= first_sessions
            or max(m["mtime"] for m in members) < recent
            or grown > first_bytes
        ):
            break
        first.append(members)
        size = grown
    batches = [[m for members in first for m in members]] if first else []
    rest = {}
    for members in ordered[len(first) :]:
        rest.setdefault(members[0]["group"][0], []).extend(members)  # group = (source, key)
    batches.extend(rest.values())  # Sources in order of their newest remaining group.
    return batches


def import_progressive(
    service,
    requests,
    *,
    cancel: threading.Event | None = None,
    first_sessions=200,
    first_days=7,
    first_bytes=FIRST_BATCH_BYTES,
    on_batch=None,
):
    """First import: publish the newest sessions first, then the rest one source per batch.

    Each batch captures and publishes inside one write transaction, so readers keep
    seeing the previous consistent snapshot and never a pending projection. On a store
    without a projection every batch rebuilds its stale sources as a whole: closure
    increments on a growing store cost far more than one bulk source rebuild, and the
    whole-source rebuild is the same path an ordinary first import publishes with.
    """
    from tandem_data.discovery import inputs
    from tandem_data.parallel import WorkerPool, capture

    store = service.store
    started = time.perf_counter()
    summary = {"batches": 0, "files": 0, "changed": 0, "capture_errors": 0, "complete": False}
    if paused(store.home):
        return {**summary, "paused": True}
    own_pool = None if service.pool is not None else WorkerPool(service.workers)
    pool = service.pool or own_pool
    with service.writer():
        # Fresh store: bulk source rebuilds. Existing store: the usual closure rules.
        fraction = (
            MAX_CLOSURE_FRACTION
            if store.db.execute("SELECT 1 FROM projection_run LIMIT 1").fetchone()
            else 0.0
        )
        entries, sources = [], {}
        for request in requests:
            root = request.root.expanduser().resolve(strict=True)
            source_id = store.add_source(request.agent, root)
            available = list(inputs(request.agent, root))
            sources[source_id] = (request.agent, root, len(available))
            mark_missing(store, source_id, {str(i.path.relative_to(root)) for i in available})
            for item in available:
                relative = str(item.path.relative_to(root))
                stat = item.path.stat()
                entries.append(
                    {
                        "source_id": source_id,
                        "agent": request.agent,
                        "root": root,
                        "item": item,
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                        "group": (source_id, session_group(request.agent, relative)),
                    }
                )
        batches = plan_batches(
            entries,
            first_sessions=first_sessions,
            first_days=first_days,
            first_bytes=first_bytes,
            now=time.time(),
        )
        summary["planned_batches"] = len(batches)
        for index, batch in enumerate(batches):
            if (cancel and cancel.is_set()) or paused(store.home):
                summary["cancelled"] = bool(cancel and cancel.is_set())
                summary["paused"] = paused(store.home)
                break
            with batch_transaction(store):
                for source_id, (agent, root, _discovered) in sources.items():
                    selected = [e["item"] for e in batch if e["source_id"] == source_id]
                    if not selected:
                        continue
                    counts = {"files": 0, "changed": 0, "capture_errors": 0, "cancelled": False}
                    capture(
                        store,
                        source_id,
                        root,
                        selected,
                        pool,
                        None,
                        service.progress,
                        counts,
                        agent,
                    )
                    for key in ("files", "changed", "capture_errors"):
                        summary[key] += counts[key]
                project(
                    store,
                    workers=service.workers,
                    pool=pool,
                    progress=service.progress,
                    max_fraction=fraction,
                )
                last = index == len(batches) - 1
                for source_id, (_, _, discovered) in sources.items():
                    store.db.execute(
                        "INSERT OR REPLACE INTO source_scan VALUES(?,?,?,?,?,?,?)",
                        (
                            source_id,
                            now_ms(),
                            "full" if last else "progressive",
                            discovered,
                            store.db.execute(
                                "SELECT COUNT(*) FROM source_file WHERE source_id=? AND status='active'",
                                (source_id,),
                            ).fetchone()[0],
                            0,
                            0,
                        ),
                    )
            summary["batches"] += 1
            event = {
                "stage": "progressive_batch",
                "batch": index + 1,
                "total": len(batches),
                "files": len(batch),
                "elapsed_seconds": round(time.perf_counter() - started, 4),
            }
            if index == 0:
                summary["first_batch_seconds"] = event["elapsed_seconds"]
            service.progress(event)
            if on_batch:
                on_batch(event)
        else:
            summary["complete"] = True
            if not batches:
                project(store, workers=service.workers, pool=pool, progress=service.progress)
    if own_pool is not None:
        own_pool.close()
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    return summary
