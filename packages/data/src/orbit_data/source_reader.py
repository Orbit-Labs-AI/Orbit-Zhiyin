"""Read indexed native evidence without storing a second copy of the session.

An index is not a backup. Every record read checks its digest; missing or replaced
source records produce an explicit error, never different evidence under an old UID.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from contextlib import ExitStack, contextmanager
from pathlib import Path

import zstandard

from orbit_data.contract import canonical


class SourceUnavailable(ValueError):
    file_id: str | None = None  # Set when a rebuild can skip just this indexed file.

    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


def source_path(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise SourceUnavailable("changed", "Indexed source path no longer belongs to its root")
    if not path.is_file():
        raise SourceUnavailable("missing", "Indexed source is no longer available")
    return path


def source_stat(path):
    value = path.stat()
    return {
        name: getattr(value, "st_" + name)
        for name in ("dev", "ino", "size", "mtime_ns", "ctime_ns")
    }


def _zstd_lines(raw):
    """Validate all concatenated frames, buffering at most one native line."""
    decoder = zstandard.ZstdDecompressor().decompressobj()
    pending = bytearray()
    seen = False
    while block := raw.read(1024 * 1024):
        while block:
            if decoder.eof:
                decoder = zstandard.ZstdDecompressor().decompressobj()
            pending.extend(decoder.decompress(block))
            block = decoder.unused_data
            seen = seen or decoder.eof
            start = 0
            while (end := pending.find(b"\n", start)) >= 0:
                yield bytes(pending[start : end + 1])
                start = end + 1
            if start:
                del pending[:start]
    if not seen or not decoder.eof:
        raise SourceUnavailable("incomplete", "Incomplete native zstd frame")
    if pending:
        yield bytes(pending)


@contextmanager
def native_lines(path, encoding, agent):
    from orbit_data.store import sqlite_rows

    if encoding == "sqlite_rows":
        rows = sqlite_rows(path, agent)
        try:
            yield rows
        finally:
            rows.close()
    else:
        with path.open("rb") as raw:
            yield (
                [raw.read()]
                if encoding == "json"
                else _zstd_lines(raw)
                if encoding == "jsonl_zstd"
                else raw
            )


def reference_info(db, record_uid):
    return db.execute(
        "SELECT r.*,s.root_path,s.agent,f.relative_path,f.format,l.byte_offset AS live_offset,"
        "l.byte_len AS live_len,l.ordinal AS live_ordinal,l.revision_uid AS live_revision "
        "FROM raw_record r JOIN source_file f USING(file_id) JOIN source s USING(source_id) "
        "JOIN record_location l USING(record_uid) JOIN source_revision v ON v.revision_uid=l.revision_uid "
        "WHERE r.record_uid=? ORDER BY v.revision DESC LIMIT 1",
        (record_uid,),
    ).fetchone()


def read_reference(db, record_uid):
    from orbit_data.store import CODEX_COLUMNS, SQL_TABLES, _json_cell, readonly_connection

    row = reference_info(db, record_uid)
    if row is None:
        raise KeyError(record_uid)
    path = source_path(row["root_path"], row["relative_path"])
    if row["format"] == "sqlite_rows":
        locator = json.loads(row["locator"])
        if len(locator) != 3 or locator[0] != "row":
            raise SourceUnavailable("changed", "Invalid SQLite record locator")
        _, table, key = locator
        if table not in SQL_TABLES.get(row["agent"], ()) or not key:
            raise SourceUnavailable("changed", "SQLite table is outside the source allowlist")
        with readonly_connection(path) as source:
            source.execute("BEGIN")
            columns = list(source.execute(f'PRAGMA table_info("{table}")'))
            primary = {r["name"] for r in columns if r["pk"]}
            if set(key) != primary:
                raise SourceUnavailable("changed", "SQLite primary key changed")
            where = " AND ".join('"' + k.replace('"', '""') + '"=?' for k in key)
            selected = [
                r["name"] for r in columns if row["agent"] != "codex" or r["name"] in CODEX_COLUMNS
            ]
            selection = ",".join('"' + k.replace('"', '""') + '"' for k in selected)
            item = source.execute(
                f'SELECT {selection} FROM "{table}" WHERE {where}', tuple(key.values())
            ).fetchone()
            if item is None:
                raise SourceUnavailable("missing", "Indexed SQLite row was deleted")
            data = (
                canonical(
                    {
                        "table": table,
                        "key": key,
                        "row": {k: _json_cell(item[k]) for k in item.keys()},
                    }
                )
                + "\n"
            ).encode()
    elif row["format"] in ("json", "jsonl"):
        with path.open("rb") as handle:
            handle.seek(row["live_offset"])
            data = handle.read(row["live_len"])
    else:
        # Native compressed offsets refer to decoded bytes, not the compressed stream.
        with (
            path.open("rb") as raw,
            zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as stream,
        ):
            handle = io.BufferedReader(stream)
            remaining = row["live_offset"]
            while remaining:
                block = handle.read(min(remaining, 1024 * 1024))
                if not block:
                    raise SourceUnavailable("changed", "Source is shorter than its locator")
                remaining -= len(block)
            data = handle.read(row["live_len"])
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise SourceUnavailable(
            "changed", "Source record changed; rescan before opening this evidence"
        )
    return data


def record_source(home, record_uid, *, include_content=False):
    """Read-only App entrypoint: indexed evidence, never an arbitrary path supplied by a client."""
    from orbit_data.store import readonly_connection

    with readonly_connection(Path(home) / "orbit.db") as db:
        db.execute("BEGIN")
        row = reference_info(db, record_uid)
        if row is None:
            return archived_source(db, home, record_uid, include_content=include_content)
        result = {
            "record_uid": record_uid,
            "storage": "source_reference",
            "path": str(Path(row["root_path"]) / row["relative_path"]),
            "encoding": row["format"],
            "locator": json.loads(row["locator"]),
            "ordinal": row["live_ordinal"],
            "byte_offset": row["live_offset"],
            "byte_len": row["live_len"],
            "sha256": row["sha256"],
        }
        try:
            data = read_reference(db, record_uid)
            result["status"] = "available"
            if include_content:
                # Local explicit original-evidence access. No truncation or redaction.
                result["content"] = data.decode("utf-8")
        except SourceUnavailable as error:
            result.update(status=error.status, reason=str(error))
        except (OSError, UnicodeError, sqlite3.Error, zstandard.ZstdError) as error:
            result.update(status="unreadable", reason=type(error).__name__)
        return result


def archived_source(db, home, record_uid, *, include_content=False):
    """Read existing archives without migrating or creating another copy."""
    row = db.execute(
        "SELECT r.*,a.path,COALESCE(json_extract(v.source_stat,'$.capture_format'),f.format) AS format,s.root_path,f.relative_path FROM raw_record r "
        "JOIN source_revision v USING(revision_uid) LEFT JOIN archive_blob a USING(archive_uid) "
        "JOIN source_file f ON f.file_id=r.file_id JOIN source s USING(source_id) WHERE record_uid=?",
        (record_uid,),
    ).fetchone()
    if row is None:
        raise KeyError(record_uid)
    result = {
        "record_uid": record_uid,
        "storage": "legacy_archive",
        "locator": json.loads(row["locator"]),
        "path": str(Path(row["root_path"]) / row["relative_path"]),
        "sha256": row["sha256"],
        "byte_offset": row["byte_offset"],
        "byte_len": row["byte_len"],
        "encoding": row["format"],
    }
    if row["path"] is None:
        return {**result, "status": "missing", "reason": "No original source locator available"}
    archive = (Path(home) / row["path"]).resolve()
    if not archive.is_relative_to((Path(home) / "raw").resolve()):
        return {**result, "status": "unreadable", "reason": "Archive path escapes its storage root"}
    try:
        with ExitStack() as stack:
            handle = stack.enter_context(archive.open("rb"))
            handle = stack.enter_context(
                zstandard.ZstdDecompressor().stream_reader(handle, read_across_frames=True)
            )
            if row["format"] == "jsonl_zstd":
                handle = stack.enter_context(
                    zstandard.ZstdDecompressor().stream_reader(handle, read_across_frames=True)
                )
            remaining = row["byte_offset"]
            while remaining:
                block = handle.read(min(remaining, 1024 * 1024))
                if not block:
                    raise ValueError("Archive is shorter than its locator")
                remaining -= len(block)
            data = handle.read(row["byte_len"])
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("Archive record digest mismatch")
        result["status"] = "available"
        if include_content:
            result["content"] = data.decode("utf-8")
    except (ValueError, OSError, zstandard.ZstdError) as error:
        result.update(status="unreadable", reason=str(error))
    return result
