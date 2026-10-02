"""Streaming L0/L1 indexes. Native session bytes are never copied into Tandem."""

import hashlib
import json
from pathlib import Path

from tandem_data.contract import RawRecord, canonical, now_ms, uid
from tandem_data.source_reader import SourceUnavailable, native_lines, source_path, source_stat
from tandem_data.store import SQL_TABLES


def index_file(store, source_id, path, role):
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
    before = source_stat(path)
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
            digest = hashlib.sha256()
            with native_lines(path, encoding, source["agent"]) as lines:
                for line in lines:
                    digest.update(line)
            matches = [
                f
                for f in missing
                if json.loads(f["watermark"]).get("source_sha256") == digest.hexdigest()
            ]
            if len(matches) == 1:
                file_id = matches[0]["file_id"]
    latest = store.db.execute(
        "SELECT v.*,f.watermark,f.role,f.status FROM source_revision v JOIN source_file f USING(file_id) "
        "WHERE file_id=? ORDER BY revision DESC LIMIT 1",
        (file_id,),
    ).fetchone()
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
        with native_lines(path, encoding, source["agent"]) as lines:
            count, length, sha = store._index_lines(
                file_id, revision_uid, lines, encoding, role, reference=True
            )
        if encoding != "sqlite_rows" and source_stat(path) != before:
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
        store.db.execute(
            "UPDATE source_file SET watermark=? WHERE file_id=?", (canonical(watermark), file_id)
        )
    store._resolve_capture_issues(source_id, file_id)
    return {"file_id": file_id, "changed": not unchanged, "records": count}


def iter_indexed_file(store, file_id):
    info = store.db.execute(
        "SELECT f.*,s.agent,s.root_path,v.revision_uid,v.captured_at,x.sha256 FROM source_file f "
        "JOIN source s USING(source_id) JOIN source_revision v USING(file_id) "
        "JOIN source_reference x USING(revision_uid) WHERE f.file_id=? ORDER BY v.revision DESC LIMIT 1",
        (file_id,),
    ).fetchone()
    path = source_path(info["root_path"], info["relative_path"])
    digest = hashlib.sha256()
    with native_lines(path, info["format"], info["agent"]) as lines:
        for ordinal, line in enumerate(lines):
            digest.update(line)
            row = store.db.execute(
                "SELECT r.*,l.ordinal AS current_ordinal FROM record_location l JOIN raw_record r USING(record_uid) "
                "WHERE l.revision_uid=? AND l.ordinal=?",
                (info["revision_uid"], ordinal),
            ).fetchone()
            if row is None or hashlib.sha256(line).hexdigest() != row["sha256"]:
                raise SourceUnavailable(
                    "changed", "Indexed source changed; rescan before rebuilding"
                )
            if row["native_type"] in ("invalid", "pending_tail"):
                continue
            yield RawRecord(
                row["record_uid"],
                info["source_id"],
                info["agent"],
                file_id,
                info["relative_path"],
                ordinal,
                row["version"],
                row["native_type"],
                json.loads(line),
                info["captured_at"],
            )
    if digest.hexdigest() != info["sha256"]:
        raise SourceUnavailable("changed", "Indexed source changed; rescan before rebuilding")
