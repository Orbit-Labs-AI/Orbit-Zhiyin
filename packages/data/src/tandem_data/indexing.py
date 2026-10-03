"""Streaming L0/L1 indexes. Native session bytes are never copied into Tandem storage.

The captured rows of a live SQLite index stay in memory only until the same import has
projected them (``remember_capture``); nothing is written to disk.
"""

import contextlib
import hashlib
import json
from pathlib import Path

from tandem_data.contract import RawRecord, canonical, now_ms, uid
from tandem_data.source_reader import SourceUnavailable, native_lines, source_path, source_stat
from tandem_data.store import SQL_TABLES


def index_file(store, source_id, path, role, scan=None):
    """Capture one allowlisted file. ``scan`` holds line facts computed by a worker."""
    source = store.db.execute("SELECT * FROM source WHERE source_id=?", (source_id,)).fetchone()
    if source is None:
        raise ValueError("Register the source before indexing files")
    root = Path(source["root_path"])
    requested = Path(path).expanduser().absolute()
    if not requested.is_relative_to(root):
        raise ValueError("Source path escapes the registered root")
    relative = str(requested.relative_to(root))
    path = source_path(root, relative)
    if path.suffix in (".sqlite", ".db") and source["agent"] in SQL_TABLES:
        encoding = "sqlite_rows"
    elif path.name.endswith((".jsonl.zst", ".jsonl.zstd")):
        encoding = "jsonl_zstd"
    elif path.suffix == ".jsonl":
        encoding = "jsonl"
    elif path.suffix == ".json" and role in ("subagent_metadata", "session_title", "import_ledger"):
        encoding = "json"
    else:
        raise ValueError("Only allowlisted transcript and session database inputs can be indexed")
    if scan is not None and scan["encoding"] != encoding:
        scan = None  # The allowlist chose another encoding; read the file in this process.
    before = scan["before"] if scan is not None else source_stat(path)
    existing = store.db.execute(
        "SELECT file_id FROM source_file WHERE source_id=? AND relative_path=?",
        (source_id, relative),
    ).fetchone()
    file_id = existing["file_id"] if existing else uid("file", source_id, relative)
    if existing is None:
        missing = list(
            store.db.execute(
                "SELECT file_id,relative_path,watermark FROM source_file WHERE source_id=? AND status='gone_upstream'",
                (source_id,),
            )
        )
        missing = [f for f in missing if not (root / f["relative_path"]).exists()]
        if missing:
            if scan is not None and not scan["start_ordinal"]:
                hexdigest = scan["sha256"]
            else:
                digest = hashlib.sha256()
                with native_lines(path, encoding, source["agent"]) as lines:
                    for line in lines:
                        digest.update(line)
                hexdigest = digest.hexdigest()
            matches = [
                f for f in missing if json.loads(f["watermark"]).get("source_sha256") == hexdigest
            ]
            if len(matches) == 1:
                file_id = matches[0]["file_id"]
                if scan is not None:
                    # Native keys may include the path, so a rename needs a new projection.
                    scan = {**scan, "renamed_from": matches[0]["relative_path"]}
    latest = store.db.execute(
        "SELECT v.*,f.watermark,f.role,f.status FROM source_revision v JOIN source_file f USING(file_id) "
        "WHERE file_id=? ORDER BY revision DESC LIMIT 1",
        (file_id,),
    ).fetchone()
    if scan is not None and scan["start_ordinal"]:
        # Append fast path: the old revision must be a byte prefix of the same inode.
        previous = json.loads(latest["watermark"]) if latest else {}
        if (
            latest is None
            or latest["archive_uid"] is not None
            or latest["record_count"] < scan["start_ordinal"]
            or scan["prefix_sha256"] is None
            or scan["prefix_sha256"] != previous.get("source_sha256")
            or (previous.get("last_source_stat") or {}).get("ino") != before["ino"]
        ):
            scan = None
            before = source_stat(path)
    # SQLite WAL changes are not reflected by the database file's stat.
    if (
        latest
        and latest["archive_uid"] is None
        and encoding != "sqlite_rows"
        and latest["status"] == "active"
        and latest["role"] == role
    ):
        previous_stat = json.loads(latest["watermark"]).get("last_source_stat")
        if previous_stat == before:
            store.db.execute(
                "UPDATE source_file SET last_scan_at=? WHERE file_id=?", (now_ms(), file_id)
            )
            store._resolve_capture_issues(source_id, file_id)
            return {"file_id": file_id, "changed": False, "records": latest["record_count"]}
    captured = now_ms()
    revision = latest["revision"] + 1 if latest else 1
    revision_uid = uid("revision", file_id, revision)
    with store.transaction():
        store._remember_archive_formats(file_id)
        store.db.execute(
            "INSERT INTO source_file(file_id,source_id,relative_path,role,format,last_scan_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(file_id) DO UPDATE SET relative_path=excluded.relative_path,status='active',role=excluded.role,format=excluded.format,last_scan_at=excluded.last_scan_at",
            (file_id, source_id, relative, role, encoding, captured),
        )
        store.db.execute(
            "INSERT INTO source_revision VALUES(?,?,?,NULL,?,?,0)",
            (revision_uid, file_id, revision, captured, canonical(before)),
        )
        store.db.execute("INSERT INTO source_reference VALUES(?,'',0,?)", (revision_uid, encoding))
        kept = None
        if scan is not None:
            count, length, sha = _index_scanned(store, file_id, revision_uid, scan, latest)
            after = scan["after"]
        else:
            with native_lines(path, encoding, source["agent"]) as lines:
                if encoding == "sqlite_rows":
                    kept = []
                    lines = _keep(lines, kept)
                count, length, sha = store._index_lines(
                    file_id, revision_uid, lines, encoding, role, reference=True
                )
            after = source_stat(path) if encoding != "sqlite_rows" else before
        if encoding != "sqlite_rows" and after != before:
            raise SourceUnavailable(
                "changed", "Source changed during indexing; retry after the writer flushes"
            )
        store.db.execute(
            "UPDATE source_reference SET sha256=?,byte_len=? WHERE revision_uid=?",
            (sha, length, revision_uid),
        )
        store.db.execute(
            "UPDATE source_revision SET record_count=? WHERE revision_uid=?", (count, revision_uid)
        )
        previous = json.loads(latest["watermark"]) if latest else {}
        unchanged = (
            latest is not None
            and latest["archive_uid"] is None
            and previous.get("source_sha256") == sha
            and latest["role"] == role
            and not store.db.execute(
                "SELECT 1 FROM ingest_issue WHERE file_id=? AND code='source_unavailable'",
                (file_id,),
            ).fetchone()
        )
        if unchanged:
            store.db.execute("DELETE FROM record_location WHERE revision_uid=?", (revision_uid,))
            store.db.execute("DELETE FROM source_reference WHERE revision_uid=?", (revision_uid,))
            store.db.execute("DELETE FROM source_revision WHERE revision_uid=?", (revision_uid,))
            watermark = {**previous, "last_source_stat": before}
        else:
            watermark = {
                "revision": revision,
                "source_sha256": sha,
                "decoded_bytes": length,
                "records": count,
                "capture": "source_reference",
                "last_source_stat": before,
            }
        if scan is not None and scan.get("renamed_from") not in (None, relative):
            # L1 identity is kept, but the projection is stale: native keys may include the path.
            watermark.pop("projected_revision", None)
        store.db.execute(
            "UPDATE source_file SET watermark=? WHERE file_id=?", (canonical(watermark), file_id)
        )
    if kept is not None:
        remember_capture(store, file_id, latest["revision_uid"] if unchanged else revision_uid, kept)
    store._resolve_capture_issues(source_id, file_id)
    return {"file_id": file_id, "changed": not unchanged, "records": count}


# Rows of a live SQLite index as captured (per Store, bounded). The projection of the same
# import reads these instead of re-reading a database the agent keeps writing: otherwise a
# row updated in between (Codex ``state_5.sqlite``) fails the digest check, rolls the whole
# rebuild back and retains the file. Every line still passes the same per-line and
# aggregate digest checks against the captured revision.
CAPTURE_CACHE_BYTES = 64 * 1024 * 1024


def _keep(lines, sink):
    for line in lines:
        sink.append(line)
        yield line


def remember_capture(store, file_id, revision_uid, lines) -> None:
    cache = store.__dict__.setdefault("_captured_lines", {})
    cache.pop(file_id, None)
    size = sum(len(line) for line in lines)
    used = sum(entry[2] for entry in cache.values())
    if size <= CAPTURE_CACHE_BYTES and used + size <= CAPTURE_CACHE_BYTES:
        cache[file_id] = (revision_uid, lines, size)


def captured_lines(store, file_id, revision_uid):
    entry = store.__dict__.get("_captured_lines", {}).get(file_id)
    return entry[1] if entry is not None and entry[0] == revision_uid else None


def _captured(lines, length):
    """Stop at the captured byte length; a line completed later is cut to its pending tail."""
    if length <= 0:
        return
    for line in lines:
        yield line[:length]
        length -= len(line)
        if length <= 0:
            return  # Never read past the capture: appended bytes belong to the next scan.


def _index_scanned(store, file_id, revision_uid, scan, latest):
    """Batch form of ``Store._index_lines`` for worker-computed line facts.

    An append scan starts at ``start_ordinal``: earlier lines keep their L1 rows and
    their locations are copied to the new revision. Version numbers, record UIDs and
    pending-tail dispositions match the line-by-line writer.
    """
    db = store.db
    start = scan["start_ordinal"]
    rows = scan["rows"]
    if start:
        db.execute(
            "INSERT INTO record_location SELECT record_uid,?,ordinal,byte_offset,byte_len "
            "FROM record_location WHERE revision_uid=? AND ordinal<?",
            (revision_uid, latest["revision_uid"], start),
        )
        stale = [canonical(["line", ordinal]) for ordinal in range(start, latest["record_count"])]
        previous = {}
        for chunk in _chunks(stale):
            previous.update(
                (row[0], (row[1], row[2]))
                for row in db.execute(
                    "SELECT f.locator,r.record_uid,r.sha256 FROM file_record f JOIN raw_record r "
                    f"USING(record_uid) WHERE f.file_id=? AND f.locator IN ({_marks(chunk)})",
                    (file_id, *chunk),
                )
            )
            db.execute(
                f"DELETE FROM file_record WHERE file_id=? AND locator IN ({_marks(chunk)})",
                (file_id, *chunk),
            )
    else:
        previous = {
            row[0]: (row[1], row[2])
            for row in db.execute(
                "SELECT f.locator,r.record_uid,r.sha256 FROM file_record f JOIN raw_record r "
                "USING(record_uid) WHERE f.file_id=?",
                (file_id,),
            )
        }
        db.execute("DELETE FROM file_record WHERE file_id=?", (file_id,))
    versions = {}
    changed = [row[4] for row in rows if previous.get(row[4], (None, None))[1] != row[3]]
    for chunk in _chunks(changed):
        versions.update(
            db.execute(
                "SELECT locator,MAX(version) FROM raw_record WHERE file_id=? "
                f"AND locator IN ({_marks(chunk)}) GROUP BY locator",
                (file_id, *chunk),
            ).fetchall()
        )
    tail_note = canonical({"reason": "incomplete_tail_retained_in_L0"})
    inserted, ignored, located, current = [], [], [], []
    for ordinal, offset, length, row_sha, locator, native_type, native_id, harness, shape in rows:
        old = previous.get(locator)
        pending = native_type == "pending_tail"
        if old and old[1] == row_sha:
            record_uid = old[0]
            if pending:
                ignored.append((tail_note, record_uid))
        else:
            version = versions.get(locator, 0) + 1
            versions[locator] = version
            record_uid = uid("record", file_id, json.loads(locator), version)
            inserted.append(
                (
                    record_uid,
                    file_id,
                    revision_uid,
                    locator,
                    version,
                    ordinal,
                    offset,
                    length,
                    row_sha,
                    native_type,
                    native_id,
                    harness,
                    shape,
                    "ignored" if pending else "unparsed",
                    tail_note if pending else "{}",
                )
            )
        current.append((file_id, locator, record_uid))
        located.append((record_uid, revision_uid, ordinal, offset, length))
    db.executemany(
        "INSERT INTO raw_record(record_uid,file_id,revision_uid,locator,version,ordinal,"
        "byte_offset,byte_len,sha256,native_type,native_id,harness_version,shape_hash,"
        "disposition,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        inserted,
    )
    db.executemany("UPDATE raw_record SET disposition='ignored',note=? WHERE record_uid=?", ignored)
    db.executemany("INSERT INTO file_record VALUES(?,?,?)", current)
    db.executemany("INSERT INTO record_location VALUES(?,?,?,?,?)", located)
    return start + len(rows), scan["decoded_bytes"], scan["sha256"]


def _chunks(values, size=500):
    values = list(values)
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _marks(values):
    return ",".join("?" * len(values))


def indexed_rows(db, file_id):
    """Latest source-reference revision and its ordinal -> L1 row map, in one query."""
    info = db.execute(
        "SELECT f.*,s.agent,s.root_path,v.revision_uid,v.captured_at,x.sha256,x.byte_len "
        "FROM source_file f JOIN source s USING(source_id) JOIN source_revision v USING(file_id) "
        "JOIN source_reference x USING(revision_uid) WHERE f.file_id=? ORDER BY v.revision DESC LIMIT 1",
        (file_id,),
    ).fetchone()
    rows = {
        row[0]: tuple(row[1:])
        for row in db.execute(
            "SELECT l.ordinal,r.record_uid,r.version,r.native_type,r.sha256 FROM record_location l "
            "JOIN raw_record r USING(record_uid) WHERE l.revision_uid=?",
            (info["revision_uid"],),
        )
    }
    return info, rows


def iter_lines_with_rows(path, info, rows, captured=None):
    """Yield verified records of the captured revision of one indexed file.

    Agents keep appending to their logs while Tandem imports. Reading stops at the
    captured ``byte_len`` (the same length and digest the append scan extends), so an
    appended file still projects its captured records, while a truncated or rewritten
    prefix fails the per-line and aggregate checks. ``captured`` replaces the live read
    with the lines kept at capture (``remember_capture``); the checks are the same.
    """
    digest = hashlib.sha256()
    source = (
        contextlib.nullcontext(iter(captured))
        if captured is not None
        else native_lines(path, info["format"], info["agent"])
    )
    with source as lines:
        for ordinal, line in enumerate(_captured(lines, info["byte_len"])):
            digest.update(line)
            row = rows.get(ordinal)
            if row is None or hashlib.sha256(line).hexdigest() != row[3]:
                raise SourceUnavailable(
                    "changed", "Indexed source changed; rescan before rebuilding"
                )
            if row[2] in ("invalid", "pending_tail"):
                continue
            yield RawRecord(
                row[0],
                info["source_id"],
                info["agent"],
                info["file_id"],
                info["relative_path"],
                ordinal,
                row[1],
                row[2],
                json.loads(line),
                info["captured_at"],
            )
    if digest.hexdigest() != info["sha256"]:
        raise SourceUnavailable("changed", "Indexed source changed; rescan before rebuilding")


def iter_indexed_file(store, file_id):
    info, rows = indexed_rows(store.db, file_id)
    path = source_path(info["root_path"], info["relative_path"])
    try:
        yield from iter_lines_with_rows(
            path, info, rows, captured_lines(store, file_id, info["revision_uid"])
        )
    except SourceUnavailable as error:
        error.file_id = file_id  # A rebuild can retain just this file's facts.
        raise
