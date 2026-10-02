"""Parallel capture and two-phase L2 mapping with a single SQLite writer.

Worker processes never open the database. For capture they read one allowlisted
file and return per-line L1 facts. For mapping they run ``prepare``/``map``,
envelope redaction and contract validation for files whose mapper does not read
L2 rows of other files; any other store access raises ``NeedsWriter`` and the file
is mapped by the writer instead. The writer applies every result at the position
the serial pipeline would, so ``seq``, folding, replay and issue decisions are the
same. Small jobs run the same code in-process, without a pool.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import multiprocessing
import os
import pickle
import shutil
import sqlite3
import tempfile
import time
import weakref
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, replace
from pathlib import Path

import zstandard

from tandem_data import MAPPER_VERSION
from tandem_data.connectors import MAPPERS
from tandem_data.contract import canonical, now_ms, shape, uid
from tandem_data.indexing import index_file, indexed_rows, iter_lines_with_rows
from tandem_data.source_reader import SourceUnavailable, _zstd_lines, source_path, source_stat
from tandem_data.store import SQL_TABLES, insert_tuples

# Mappers that only read their own file. Others (Codex history/forks, Kimi indexes,
# OpenCode/Hermes databases) always stay on the writer.
PARALLEL_AGENTS = frozenset({"claude_code", "pi", "dsh"})
LINE_FORMATS = ("jsonl", "jsonl_zstd", "json")
PARALLEL_THRESHOLD = 24  # Smaller jobs are cheaper in-process than spawning a pool.
CAPTURE_ERRORS = (OSError, RuntimeError, ValueError, sqlite3.Error, zstandard.ZstdError)


WRITER_CACHE_KIB = 262_144


def writer_pragmas(db):
    """Session-only settings for the single import writer; results are unaffected.

    The default 2 MiB page cache makes every batch re-read index pages (about 4x slower
    at 100k events). Only raised, never lowered, so a caller's larger cache is kept.
    """
    current = db.execute("PRAGMA cache_size").fetchone()[0]
    if current >= 0 or -current < WRITER_CACHE_KIB:
        db.execute(f"PRAGMA cache_size=-{WRITER_CACHE_KIB}")


def _insert_rows(db, table, columns, rows):
    """Batch INSERT used by the writer; ``store.insert_tuples`` packs event.ext/text."""
    if rows:
        insert_tuples(db, table, columns, rows)


def default_workers() -> int:
    configured = os.environ.get("TANDEM_IMPORT_WORKERS")
    if configured:
        return max(1, int(configured))
    return max(2, min(8, (os.cpu_count() or 2) - 1))


class _Inline:
    """Executor interface that runs work immediately in this process."""

    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - re-raised by Future.result()
            future.set_exception(error)
        return future


INLINE = _Inline()


class WorkerPool:
    """Lazily started process pool shared by one import job."""

    def __init__(self, workers: int, threshold: int = PARALLEL_THRESHOLD):
        self.workers = max(1, workers)
        self.threshold = threshold
        self._pool = None
        self._spill = None
        self.broken = False
        # file_id -> (task, future): files mapped while their source was still being
        # captured. MapPlan reuses a future only for an identical task (map_file is a
        # pure function of it), so the projection is unchanged; it only starts earlier.
        self.premapped = {}

    def executor(self, jobs: int):
        if self.broken or self.workers <= 1 or jobs < max(1, self.threshold):
            return INLINE
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                self.workers, mp_context=multiprocessing.get_context("spawn")
            )
        return self._pool

    def submit(self, executor, fn, *args):
        """Submit work, or return None once the pool is broken: the caller then uses the
        writer's serial path (the ``workers=1`` code) for that file."""
        if self.broken:
            return None
        try:
            return executor.submit(fn, *args)
        except BrokenProcessPool:
            self.mark_broken()
            return None

    def mark_broken(self):
        """A worker process died: stop using processes for the rest of this job."""
        self.broken = True
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def spill_dir(self, home: Path) -> str:
        if self._spill is None:
            self._spill = tempfile.mkdtemp(prefix="import-", dir=home)
        return self._spill

    def close(self):
        for _, future in self.premapped.values():
            if not future.cancel():
                future.add_done_callback(_drop_spill)
        self.premapped = {}
        if self._pool is not None:
            self._pool.shutdown(cancel_futures=True)
            self._pool = None
        if self._spill is not None:
            shutil.rmtree(self._spill, ignore_errors=True)
            self._spill = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _drop_spill(future):
    try:
        outcome = future.result()
    except BaseException:  # noqa: BLE001 - an unused result; nothing to clean up
        return
    if isinstance(outcome, dict) and isinstance(outcome.get("results"), str):
        with contextlib.suppress(OSError):
            os.unlink(outcome["results"])


def map_candidate(db, info) -> bool:
    """Whether a file is mapped by a worker (independent line-format file)."""
    if (
        info["agent"] not in PARALLEL_AGENTS
        or info["agent"] not in MAPPERS
        or info["role"] == "legacy_transcript"
        or info["format"] not in LINE_FORMATS
    ):
        return False
    latest = db.execute(
        "SELECT archive_uid FROM source_revision WHERE file_id=? ORDER BY revision DESC LIMIT 1",
        (info["file_id"],),
    ).fetchone()
    return latest is not None and latest[0] is None


def map_task(db, info, mapper_version):
    meta, rows = indexed_rows(db, info["file_id"])
    return {
        "info": {k: info[k] for k in info.keys()},
        "meta": {k: meta[k] for k in meta.keys()},
        "root_path": meta["root_path"],
        "rows": rows,
        "mapper_version": mapper_version,
    }


PROJECTION_INFO = "SELECT f.*,s.agent FROM source_file f JOIN source s USING(source_id)"


def _premap(store, pool, executor, file_id):
    """First import: start mapping a captured file while later files are captured."""
    info = store.db.execute(PROJECTION_INFO + " WHERE f.file_id=?", (file_id,)).fetchone()
    if info is None or not map_candidate(store.db, info):
        return
    task = map_task(store.db, info, MAPPER_VERSION)
    future = pool.submit(executor, map_file, task, pool.spill_dir(store.home))
    if future is not None:
        pool.premapped[file_id] = (task, future)


# --- capture -----------------------------------------------------------------


def capture_encoding(path: Path, role: str, agent: str) -> str | None:
    """Same allowlist decision as ``indexing.index_file``."""
    if path.suffix in (".sqlite", ".db") and agent in SQL_TABLES:
        return "sqlite_rows"
    if path.name.endswith((".jsonl.zst", ".jsonl.zstd")):
        return "jsonl_zstd"
    if path.suffix == ".jsonl":
        return "jsonl"
    if path.suffix == ".json" and role in ("subagent_metadata", "session_title", "import_ledger"):
        return "json"
    return None


def scan_lines(path, encoding, role, start_ordinal=0, start_offset=0, prefix=0):
    """Worker: per-line L1 facts, identical to ``Store._index_lines`` decisions."""
    path = Path(path)
    before = source_stat(path)
    digest = hashlib.sha256()
    check, unchecked = None, 0
    rows = []
    offset, ordinal = start_offset, start_ordinal
    with path.open("rb") as raw:
        if start_offset:
            remaining = start_offset
            while remaining:
                block = raw.read(min(remaining, 1 << 20))
                if not block:
                    raise SourceUnavailable("changed", "Source shrank during an append scan")
                digest.update(block)
                remaining -= len(block)
        if prefix:
            check, unchecked = digest.copy(), prefix - start_offset
        lines = (
            [raw.read()]
            if encoding == "json"
            else _zstd_lines(raw)
            if encoding == "jsonl_zstd"
            else raw
        )
        for line in lines:
            digest.update(line)
            if check is not None and unchecked:
                check.update(line[:unchecked])
                unchecked -= min(unchecked, len(line))
            row_sha = hashlib.sha256(line).hexdigest()
            try:
                if encoding in ("jsonl", "jsonl_zstd") and not line.endswith(b"\n"):
                    raise ValueError("pending_tail")
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("Record must be an object")
                locator = canonical(["line", ordinal])
                native_type = str(data.get("type", role if encoding == "json" else "unknown"))
                native_id = data.get("uuid", data.get("id"))
                shape_hash = uid("shape", shape(data))
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                data, locator, native_id, shape_hash = {}, canonical(["line", ordinal]), None, None
                native_type = (
                    "pending_tail"
                    if encoding in ("jsonl", "jsonl_zstd") and not line.endswith(b"\n")
                    else "invalid"
                )
            rows.append(
                (
                    ordinal,
                    offset,
                    len(line),
                    row_sha,
                    locator,
                    native_type,
                    str(native_id) if native_id is not None else None,
                    str(data.get("version", data.get("cli_version", ""))) or None,
                    shape_hash,
                )
            )
            offset += len(line)
            ordinal += 1
    return {
        "encoding": encoding,
        "before": before,
        "after": source_stat(path),
        "rows": rows,
        "start_ordinal": start_ordinal,
        "decoded_bytes": offset,
        "sha256": digest.hexdigest(),
        "prefix_sha256": check.hexdigest() if check is not None and not unchecked else None,
    }


def _append_plan(store, file, path_stat, role):
    """Return (ordinal, offset, prefix) for a verified JSONL append, else None."""
    if not file or file["archive_uid"] is not None or file["status"] != "active":
        return None
    if file["role"] != role or file["format"] != "jsonl":
        return None
    watermark = json.loads(file["watermark"])
    previous = watermark.get("last_source_stat") or {}
    length = watermark.get("decoded_bytes")
    if (
        not isinstance(length, int)
        or not length
        or not watermark.get("source_sha256")
        or previous.get("ino") != path_stat["ino"]
        or previous.get("dev") != path_stat["dev"]
        or path_stat["size"] <= length
    ):
        return None
    tail = store.db.execute(
        "SELECT l.ordinal,l.byte_offset FROM record_location l JOIN raw_record r USING(record_uid) "
        "WHERE l.revision_uid=? AND r.native_type='pending_tail' ORDER BY l.ordinal LIMIT 1",
        (file["revision_uid"],),
    ).fetchone()
    if tail:
        return tail[0], tail[1], length
    return file["record_count"], length, length


def _relative(prefix, root, path):
    text = str(path)
    if text.startswith(prefix):
        return text[len(prefix) :]
    return str(Path(path).relative_to(root))


def relative_paths(root, items) -> set[str]:
    """``{str(item.path.relative_to(root))}`` without pathlib's per-path ancestor walk."""
    prefix = os.path.join(str(root), "")
    return {_relative(prefix, root, item.path) for item in items}


class _SourcePaths:
    """``source_reader.source_path`` with the root and parent directories resolved once.

    A non-symlink file resolves to its resolved parent plus its own name, so caching the
    parent keeps the same containment check without re-walking every path component.
    String checks replace ``Path.is_relative_to``, which builds every ancestor path.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.prefix = os.path.join(str(self.root), "")
        self.parents = {}

    def relative(self, path):
        return _relative(self.prefix, self.root, path)

    def __call__(self, relative):
        path = os.path.join(str(self.root), relative)
        if os.path.islink(path):
            raise SourceUnavailable("changed", "Indexed source path no longer belongs to its root")
        folder, name = os.path.split(path)
        parent = self.parents.get(folder)
        if parent is None:
            parent = self.parents[folder] = os.path.join(os.path.realpath(folder), "")
        if not (parent + name).startswith(self.prefix):
            raise SourceUnavailable("changed", "Indexed source path no longer belongs to its root")
        if not os.path.isfile(path):
            raise SourceUnavailable("missing", "Indexed source is no longer available")
        return Path(path)


CAPTURE_GROUP_FILES = 256
CAPTURE_GROUP_SECONDS = 1.0


class _CommitGroup:
    """Commit captured files in groups instead of one durable COMMIT per file.

    Each file keeps its own savepoint, so a failing file still rolls back alone and is
    reported as before. A crash loses at most one uncommitted group, which the next scan
    captures again because its watermark was never written. Inside an outer transaction
    (progressive batches) the caller's transaction is used unchanged.
    """

    def __init__(self, store):
        self.store = store
        self.batch = None
        self.files = 0
        self.started = 0.0

    def next(self):
        if self.batch is not None and (
            self.files >= CAPTURE_GROUP_FILES
            or time.monotonic() - self.started >= CAPTURE_GROUP_SECONDS
        ):
            self.close()
        if self.batch is None and not self.store.db.in_transaction:
            from tandem_data.scheduler import batch_transaction

            self.batch = batch_transaction(self.store)
            self.batch.__enter__()
            self.files, self.started = 0, time.monotonic()
        self.files += 1

    def close(self):
        batch, self.batch = self.batch, None
        if batch is not None:
            batch.__exit__(None, None, None)

    def abort(self):
        batch, self.batch = self.batch, None
        if batch is not None:
            batch.__exit__(RuntimeError, RuntimeError("capture aborted"), None)


def capture(store, source_id, root, selected, pool, cancel, progress, result, agent, premap=True):
    """Capture selected inputs: stat-unchanged files in one transaction, the rest in workers.

    On the first import of a source (``premap``), each captured line file is also handed
    to a worker for mapping right away, so stage A of the projection overlaps capture.
    """
    files = {
        row["relative_path"]: row
        for row in store.db.execute(
            "SELECT f.*,v.revision_uid,v.archive_uid,v.record_count FROM source_file f "
            "LEFT JOIN source_revision v ON v.revision_uid=(SELECT revision_uid FROM source_revision "
            "WHERE file_id=f.file_id ORDER BY revision DESC LIMIT 1) WHERE f.source_id=?",
            (source_id,),
        )
    }
    resolve = store.db.execute(
        "SELECT 1 FROM ingest_issue WHERE source_id=? AND stage='l1' LIMIT 1", (source_id,)
    ).fetchone()
    skipped, jobs = [], []
    locate = _SourcePaths(root)
    for item in selected:
        relative = locate.relative(item.path)
        file = files.get(relative)
        encoding = capture_encoding(item.path, item.role, agent)
        try:
            current = source_stat(locate(relative))
        except (OSError, ValueError):
            current = None  # index_file reports the failure in order.
        if (
            file is not None
            and current is not None
            and file["revision_uid"] is not None
            and file["archive_uid"] is None
            and encoding != "sqlite_rows"
            and file["status"] == "active"
            and file["role"] == item.role
            and json.loads(file["watermark"]).get("last_source_stat") == current
        ):
            skipped.append(file["file_id"])
            jobs.append((item, None))
        elif encoding in LINE_FORMATS and current is not None:
            append = _append_plan(store, file, current, item.role)
            jobs.append((item, (str(item.path), encoding, item.role, *(append or (0, 0, 0)))))
        else:
            jobs.append((item, False))  # SQLite rows or unreadable: the serial writer path.
    if skipped:
        with store.transaction():
            store.db.executemany(
                "UPDATE source_file SET last_scan_at=? WHERE file_id=?",
                ((now_ms(), file_id) for file_id in skipped),
            )
            if resolve:
                for file_id in skipped:
                    store._resolve_capture_issues(source_id, file_id)
    executor = pool.executor(sum(1 for _, job in jobs if job))
    futures = [pool.submit(executor, scan_lines, *job) if job else None for _, job in jobs]
    premap = premap and not files and executor is not INLINE
    progress({"stage": "capture", "completed": 0, "total": len(selected)})
    group = _CommitGroup(store)
    try:
        for (item, job), future in zip(jobs, futures, strict=True):
            if cancel and cancel.is_set():
                result["cancelled"] = True
                break
            group.next()
            if job is None:
                result["files"] += 1
            else:
                try:
                    try:
                        scan = future.result() if future is not None else None
                    except BrokenProcessPool:
                        pool.mark_broken()
                        scan = None  # Serial capture, exactly as with workers=1.
                    captured = index_file(store, source_id, item.path, item.role, scan)
                    result["files"] += 1
                    result["changed"] += int(captured["changed"])
                    if premap and scan is not None and not pool.broken:
                        _premap(store, pool, executor, captured["file_id"])
                except CAPTURE_ERRORS as error:
                    result["capture_errors"] += 1
                    store.issue(
                        source_id,
                        "capture_failed",
                        stage="l1",
                        detail={
                            "exception": type(error).__name__,
                            "path": str(item.path.relative_to(root)),
                        },
                    )
            progress(
                {
                    "stage": "capture",
                    "agent": agent,
                    "completed": result["files"] + result["capture_errors"],
                    "total": len(selected),
                }
            )
        group.close()
    finally:
        group.abort()
        for future in futures:
            if future is not None:
                future.cancel()


# --- mapping -----------------------------------------------------------------


class NeedsWriter(Exception):  # noqa: N818 - control flow, never shown to users
    """A worker mapper touched state that only the writer may read or write."""


class _Cursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class _RecordingDb:
    def __init__(self, actions):
        self.actions = actions

    def execute(self, sql, params=()):
        if sql.startswith("UPDATE raw_record SET disposition='unparsed'"):
            self.actions.append(("sql", sql, tuple(params)))
            return _Cursor()
        raise NeedsWriter(sql.split(" ", 3)[:3])

    def executemany(self, sql, params):
        raise NeedsWriter(sql.split(" ", 3)[:3])


class FacadeStore:
    """The part of ``Store`` an independent mapper may use, recorded for the writer."""

    def __init__(self):
        self.actions = []
        self.db = _RecordingDb(self.actions)

    def identity(self, source_id, native_id, file_scope=None):
        # Must match Store.identity exactly; tests compare both paths.
        key = canonical([native_id, file_scope] if file_scope else [native_id])
        session_uid = uid("session", source_id, json.loads(key))
        self.actions.append(("identity", (session_uid, source_id, native_id, key)))
        return session_uid

    def issue(self, *args, **kwargs):
        self.actions.append(("issue", args, kwargs))

    def iter_file(self, file_id):
        raise NeedsWriter("iter_file")

    def iter_versions(self, file_id, native_type):
        raise NeedsWriter("iter_versions")

    def take(self):
        actions = list(self.actions)
        self.actions.clear()
        return actions

    def __getattr__(self, name):
        raise NeedsWriter(name)


def apply_actions(store, actions):
    for action in actions:
        if action[0] == "identity":
            store.db.execute("INSERT OR IGNORE INTO session_identity VALUES(?,?,?,?)", action[1])
        elif action[0] == "issue":
            store.issue(*action[1], **action[2])
        else:
            store.db.execute(action[1], action[2])


@dataclass
class LiteDraft:
    """The draft fields the writer reads; the envelope carries the content."""

    event_uid: str
    session_uid: str
    kind: str
    ts: int | None
    attrs: dict
    native_key: list
    parent_native_key: list | None


TOKENS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def _lite(mapped):
    if mapped is None or mapped.error:
        return mapped
    prepared, encoded = [], []
    for draft, envelope in mapped.prepared:
        attrs = {"time": draft.attrs["time"]}
        attrs.update((token, draft.attrs[token]) for token in TOKENS if token in draft.attrs)
        prepared.append(
            (
                LiteDraft(
                    draft.event_uid,
                    draft.session_uid,
                    draft.kind,
                    draft.ts,
                    attrs,
                    draft.native_key,
                    draft.parent_native_key,
                ),
                envelope,
            )
        )
        encoded.append(
            (
                canonical(envelope["native_key"]),
                canonical(envelope["attrs"]),
                canonical(envelope["ext"]),
                canonical(draft.parent_native_key) if draft.parent_native_key else None,
            )
        )
    return replace(mapped, prepared=prepared, encoded=encoded)


def map_file(task, spill_dir=None):
    """Worker: prepare and map one independent file without touching SQLite."""
    from tandem_data.pipeline import map_native

    info = task["info"]
    facade = FacadeStore()
    path = source_path(task["root_path"], info["relative_path"])
    try:
        records = list(iter_lines_with_rows(path, task["meta"], task["rows"]))
    except SourceUnavailable as error:
        return {"unavailable": error.status, "message": str(error)}
    mapper = MAPPERS[info["agent"]](facade, info)
    try:
        mapper.prepare(iter(records))
    except NeedsWriter:
        return {"serial": True}
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return {"prepare_error": type(error).__name__, "prepare_actions": facade.take()}
    prepare_actions = facade.take()
    results = []
    try:
        for record in records:
            if record.native_type == "table:session_model_usage":
                continue
            mapped = _lite(map_native(mapper, record, task["mapper_version"]))
            results.append((replace(record, data={}), mapped, facade.take()))
    except NeedsWriter:
        return {"serial": True}
    stub = {
        "header": mapper.header,
        "session_uid": mapper.session_uid,
        "preparation_failures": set(getattr(mapper, "preparation_failures", set())),
    }
    for name in ("parent_file_id", "parent", "cut"):
        if hasattr(mapper, name):
            stub[name] = getattr(mapper, name)
    if spill_dir is not None:
        handle, spill = tempfile.mkstemp(dir=spill_dir, suffix=".map")
        with os.fdopen(handle, "wb") as out:
            pickle.dump(results, out, protocol=pickle.HIGHEST_PROTOCOL)
        results = spill
    return {"stub": stub, "prepare_actions": prepare_actions, "results": results}


class ReplayMapper:
    """Writer-side stand-in for a mapper that ran in a worker."""

    def __init__(self, info, stub, results):
        self.info = info
        self.header = stub["header"]
        self.session_uid = stub["session_uid"]
        self.preparation_failures = stub["preparation_failures"]
        for name in ("parent_file_id", "parent", "cut"):
            if name in stub:
                setattr(self, name, stub[name])
        self.results = results


EVENT_INSERT_LIMIT = 2000


DEFER_SEARCH_INDEX_FILES = 64
SEARCHED = "('message.user','message.assistant','session.title')"
EVENT_SEARCH_TRIGGERS = {
    "event_search_ai": "CREATE TRIGGER event_search_ai AFTER INSERT ON event "
    f"WHEN new.kind IN {SEARCHED} AND new.text IS NOT NULL BEGIN "
    "INSERT INTO event_search(rowid, text) VALUES (new.rowid, new.text); END",
    "event_search_ad": "CREATE TRIGGER event_search_ad AFTER DELETE ON event "
    f"WHEN old.kind IN {SEARCHED} AND old.text IS NOT NULL BEGIN "
    "DELETE FROM event_search WHERE rowid = old.rowid; END",
    "event_search_au": "CREATE TRIGGER event_search_au AFTER UPDATE OF text, kind ON event BEGIN "
    "DELETE FROM event_search WHERE rowid = old.rowid "
    f"AND old.kind IN {SEARCHED} AND old.text IS NOT NULL; "
    "INSERT INTO event_search(rowid, text) SELECT new.rowid, new.text "
    f"WHERE new.kind IN {SEARCHED} AND new.text IS NOT NULL; END",
}


class DeferredSearchIndex:
    """Index new events in ``event_search`` with one bulk insert instead of row triggers.

    FTS5 flushes a new segment for every trigger-driven insert, which then has to be
    merged: about a third of the writer's time on a large rebuild. Inside the rebuild's
    write transaction the three persistent search triggers (migration 008) are replaced by
    TEMP triggers that keep rows that were already indexed in sync (new rows are found by
    rowid above the starting maximum, so inserts carry no search trigger at all);
    other ``event`` triggers (content_blob reference counts) stay untouched. ``finish``
    indexes the new rows that qualify and restores the original triggers. Everything
    is part of the same transaction, so readers never observe the swap and a rollback
    restores the schema. Only used when the trigger definitions are exactly these.
    """

    def __init__(self, db, definitions, floor):
        self.db = db
        self.definitions = definitions
        self.floor = floor

    @classmethod
    def start(cls, db, files):
        if files < DEFER_SEARCH_INDEX_FILES or not db.in_transaction:
            return None
        definitions = dict(
            db.execute(
                "SELECT name,sql FROM main.sqlite_master WHERE type='trigger' "
                "AND tbl_name='event' AND name LIKE 'event_search%'"
            )
        )
        normal = {name: " ".join(sql.split()) for name, sql in definitions.items()}
        if (
            normal != EVENT_SEARCH_TRIGGERS
            or db.execute(
                "SELECT 1 FROM temp.sqlite_master WHERE name IN ('event_search','fts_pending')"
            ).fetchone()
        ):
            return None  # Unknown search-index wiring: keep the row triggers.
        for name in definitions:
            db.execute(f"DROP TRIGGER main.{name}")
        # Rows inserted from here on get rowids above ``floor`` (max+1), so they need no
        # per-row trigger. ``fts_pending`` records deleted pre-existing rowids: a later insert
        # may reuse one, so those rowids are treated as pending too.
        floor = db.execute("SELECT COALESCE(MAX(rowid),0) FROM main.event").fetchone()[0]
        db.execute("CREATE TEMP TABLE fts_pending(id INTEGER PRIMARY KEY)")
        pending = f"(old.rowid>{floor} OR EXISTS(SELECT 1 FROM fts_pending WHERE id=old.rowid))"
        db.execute(
            "CREATE TEMP TRIGGER fts_defer_ad AFTER DELETE ON main.event BEGIN "
            "DELETE FROM main.event_search WHERE rowid=old.rowid "
            f"AND old.kind IN {SEARCHED} AND old.text IS NOT NULL AND NOT {pending}; "
            f"INSERT OR IGNORE INTO fts_pending SELECT old.rowid WHERE old.rowid<={floor}; END"
        )
        db.execute(
            "CREATE TEMP TRIGGER fts_defer_au AFTER UPDATE OF text, kind ON main.event "
            f"WHEN NOT {pending} BEGIN "
            "DELETE FROM main.event_search WHERE rowid=old.rowid "
            f"AND old.kind IN {SEARCHED} AND old.text IS NOT NULL; "
            "INSERT INTO main.event_search(rowid,text) SELECT new.rowid,new.text "
            f"WHERE new.kind IN {SEARCHED} AND new.text IS NOT NULL; END"
        )
        return cls(db, definitions, floor)

    def finish(self):
        db = self.db
        db.execute(
            "INSERT INTO main.event_search(rowid,text) SELECT rowid,text FROM main.event "
            f"WHERE (rowid>? OR rowid IN (SELECT id FROM temp.fts_pending)) "
            f"AND kind IN {SEARCHED} AND text IS NOT NULL ORDER BY rowid",
            (self.floor,),
        )
        for name in ("fts_defer_ad", "fts_defer_au"):
            db.execute(f"DROP TRIGGER temp.{name}")
        db.execute("DROP TABLE temp.fts_pending")
        for name in EVENT_SEARCH_TRIGGERS:
            db.execute(self.definitions[name])


class MapPlan:
    """Stage A in workers, stage B (ordered, batched writes) in the writer."""

    def __init__(self, store, infos, unavailable, mapper_version, pool, workers, scope):
        self.store = store
        self.scope = scope
        writer_pragmas(store.db)
        self.futures = {}
        self.current = {}
        self.present = set()
        self.events, self.links, self.updates = [], [], []
        self.columns = None
        if pool is None:
            pool = WorkerPool(workers if workers else default_workers())
            weakref.finalize(self, pool.close)
        self.pool = pool
        self.search_index = DeferredSearchIndex.start(store.db, len(infos))
        candidates = [
            info
            for info in infos
            if info["file_id"] not in unavailable and map_candidate(store.db, info)
        ]
        executor = self.pool.executor(len(candidates))
        spill = self.pool.spill_dir(store.home) if executor is not INLINE else None
        premapped = getattr(self.pool, "premapped", {})
        # Submit while reading L1 rows so workers start before the last file is loaded.
        for info in candidates:
            task = map_task(store.db, info, mapper_version)
            early = premapped.pop(info["file_id"], None)
            if early is not None and early[0] == task:
                self.futures[info["file_id"]] = early[1]  # Same input, started at capture.
                continue
            if early is not None and not early[1].cancel():
                early[1].add_done_callback(_drop_spill)  # Stale input: never used.
            future = self.pool.submit(executor, map_file, task, spill)
            if future is not None:  # None: the pool broke; this file is mapped serially.
                self.futures[info["file_id"]] = future

    def finish_mapping(self):
        """Called once L2 rows are written, before derivation reads or updates them."""
        self.flush()
        if self.search_index is not None:
            self.search_index.finish()
            self.search_index = None

    def prepared(self, info, mappers):
        """Apply a worker's prepare phase in serial order; False means map serially."""
        future = self.futures.get(info["file_id"])
        if future is None:
            return False
        try:
            outcome = future.result()
        except BrokenProcessPool:
            # A worker died; this and every later file use the writer's serial mapping.
            self.pool.mark_broken()
            del self.futures[info["file_id"]]
            return False
        if outcome.get("unavailable"):
            raise SourceUnavailable(outcome["unavailable"], outcome["message"])
        if outcome.get("serial"):
            del self.futures[info["file_id"]]
            return False
        apply_actions(self.store, outcome["prepare_actions"])
        if "prepare_error" in outcome:
            self.store.issue(
                info["source_id"],
                "file_preparation_error",
                file_id=info["file_id"],
                detail={"exception": outcome["prepare_error"]},
            )
            return True
        mappers[info["file_id"]] = ReplayMapper(info, outcome["stub"], outcome["results"])
        return True

    def owns(self, mapper):
        return isinstance(mapper, ReplayMapper)

    def records(self, mapper):
        results = mapper.results
        if isinstance(results, str):
            with open(results, "rb") as handle:
                results = pickle.load(handle)
            os.unlink(mapper.results)
        mapper.results = None
        uids = [
            draft.event_uid
            for _, mapped, _ in results
            if mapped is not None and not mapped.error
            for draft, _ in mapped.prepared
        ]
        self.present = set()
        for start in range(0, len(uids), 500):
            chunk = uids[start : start + 500]
            self.present.update(
                row[0]
                for row in self.store.db.execute(
                    f"SELECT event_uid FROM event WHERE event_uid IN ({','.join('?' * len(chunk))})",
                    chunk,
                )
            )
        for record, mapped, actions in results:
            self.current[record.record_uid] = (mapped, actions)
            yield record

    def apply(self, mapper, record, apply_mapped, sequences, first_by_native, parent_keys, pending):
        from tandem_data.connectors.base import Mapping

        mapped, actions = self.current.pop(record.record_uid)
        apply_actions(self.store, actions)
        if mapped is None:
            return
        uids = [draft.event_uid for draft, _ in mapped.prepared]
        if mapped.error or self.present.intersection(uids) or len(set(uids)) != len(uids):
            # Folding, replay and error paths read the database: use the serial code.
            self.flush()
            apply_mapped(mapper, record, mapped)
            self.present.update(uids)
            return
        session_uid = mapped.session_hint
        for (draft, envelope), encoded in zip(mapped.prepared, mapped.encoded, strict=True):
            if self.columns is None:
                self.columns = list(envelope)
            row = {
                **envelope,
                "seq": sequences[draft.session_uid],
                "native_key": encoded[0],
                "attrs": encoded[1],
                "ext": encoded[2],
            }
            sequences[draft.session_uid] += 1
            self.events.append(tuple(row[column] for column in self.columns))
            self.links.append((record.record_uid, draft.event_uid))
            first_by_native.setdefault(encoded[0], draft.event_uid)
            if encoded[3]:
                parent_keys[draft.event_uid] = encoded[3]
            if draft.kind == "unknown":
                self.store.issue(
                    record.source_id,
                    "unknown_native_type",
                    record_uid=record.record_uid,
                    file_id=record.file_id,
                    detail={"native_type": record.native_type},
                )
            session_uid = draft.session_uid
        self.present.update(uids)
        result = mapped.result
        if result.references:
            pending.append(
                (record, Mapping(disposition=result.disposition, references=result.references))
            )
        disposition = "mapped" if uids else (result.disposition or "ignored")
        note = canonical({"reason": result.reason} if result.reason else {})
        self.updates.append((session_uid, disposition, note, record.record_uid))
        if len(self.events) >= EVENT_INSERT_LIMIT:
            self.flush()

    def flush(self):
        db = self.store.db
        _insert_rows(db, "event", self.columns, self.events)
        _insert_rows(
            db,
            "record_event",
            ("record_uid", "event_uid", "relation", "contribution"),
            [(*link, "mapped", "{}") for link in self.links],
        )
        if self.updates:
            db.executemany(
                "UPDATE raw_record SET session_uid=COALESCE(?,session_uid),disposition=?,note=? "
                "WHERE record_uid=?",
                self.updates,
            )
        self.events, self.links, self.updates = [], [], []

    # --- scope guards and validation ------------------------------------------

    def check_existing(self, existing):
        if self.scope is not None:
            self.scope.check_existing(self.store.db, existing)

    def unresolved_parent(self, native_key):
        if self.scope is not None:
            self.scope.check_parent_key(self.store.db, native_key)

    def validate(self, files_sql, sessions_sql):
        """Foreign keys and L1 accounting for rebuilt rows. COMMIT re-checks deferred keys."""
        db = self.store.db
        in_sessions = f"c.session_uid IN ({sessions_sql})"
        scoped = {
            "event": in_sessions,
            "session": in_sessions,
            "turn": in_sessions,
            "tool_call": in_sessions,
            "model_call": in_sessions,
            "usage_snapshot": in_sessions,
            "session_feature": in_sessions,
            "link": in_sessions,
            "event_context": f"c.event_uid IN (SELECT event_uid FROM event WHERE session_uid IN ({sessions_sql}))",
            "tool_call_event": f"c.call_uid IN (SELECT call_uid FROM tool_call WHERE session_uid IN ({sessions_sql}))",
            "record_event": f"c.record_uid IN (SELECT record_uid FROM raw_record WHERE file_id IN ({files_sql}))",
            "raw_record": f"c.file_id IN ({files_sql})",
        }
        for table, where in scoped.items():
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            references = {}
            for row in db.execute(f"PRAGMA foreign_key_list({table})"):
                references.setdefault(row[0], (row[2], []))[1].append((row[3], row[4]))
            for parent, pairs in references.values():
                if not all(child in columns for child, _ in pairs):
                    continue
                targets = [
                    target or _primary_key(db, parent)[index]
                    for index, (_, target) in enumerate(pairs)
                ]
                present = " AND ".join(f"c.{child} IS NOT NULL" for child, _ in pairs)
                match = " AND ".join(
                    f"p.{target}=c.{child}"
                    for (child, _), target in zip(pairs, targets, strict=True)
                )
                broken = db.execute(
                    f"SELECT 1 FROM {table} c WHERE {where} AND {present} "
                    f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE {match}) LIMIT 1"
                ).fetchone()
                if broken:
                    raise ValueError("Projection contains broken foreign keys")
        invalid = db.execute(
            f"SELECT COUNT(*) FROM v_raw_record_ledger WHERE file_id IN ({files_sql}) AND ("
            "(disposition IN ('mapped','folded','replayed','duplicate') AND event_count=0) OR "
            "(disposition IN ('ignored','unparsed') AND event_count>0))"
        ).fetchone()[0]
        if invalid:
            raise ValueError("L1 disposition and provenance links disagree")


def _primary_key(db, table):
    rows = sorted((row[5], row[1]) for row in db.execute(f"PRAGMA table_info({table})") if row[5])
    return [name for _, name in rows]
