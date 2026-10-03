"""Logical import digest and invariants, independent of physical storage layout.

``logical_digest(home)`` hashes only what an import *means*: L1 record destinations,
record→event provenance, every event as the product reader returns it, L3 tables,
ingest issues and the visible inventory. Row order, rowids, page layout, indexes,
VACUUM, compression and wall-clock capture times do not change it, so a serial
import and a parallel/incremental/deduplicated one over the same sources must agree.

``invariants(home)`` reports soundness checks that must hold for any published home.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from tandem_data.query import event_page
from tandem_data.store import Store, readonly_connection

DIGEST_VERSION = "1"
PAGE = 1000

# Wall-clock observation times differ between two imports of identical sources.
VOLATILE_COLUMNS = frozenset(
    {"captured_at", "last_scan_at", "completed_at", "detected_at", "observed_at", "discovered_at"}
)
RAW_RECORD_COLUMNS = (
    "record_uid",
    "file_id",
    "locator",
    "version",
    "sha256",
    "native_type",
    "disposition",
    "session_uid",
)
L3_TABLES = (
    "project",
    "session",
    "turn",
    "tool_call",
    "tool_call_event",
    "tool_call_file",
    "model_call",
    "usage_snapshot",
    "session_feature",
    "link",
)
INVENTORY_COLUMNS = ("agent", "type", "name", "locator", "content_hash")


def _encode(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode()


def _columns(db, table: str) -> list[str]:
    return [
        row[1]
        for row in db.execute(f"PRAGMA table_info({table})")
        if row[1] not in VOLATILE_COLUMNS
    ]


def _hash_query(db, sql: str, params=()) -> tuple[str, int]:
    digest, count = hashlib.sha256(), 0
    for row in db.execute(sql, params):
        digest.update(_encode(list(row)))
        count += 1
    return digest.hexdigest(), count


def _sorted_table(db, table: str, columns) -> tuple[str, int]:
    names = ",".join(f'"{name}"' for name in columns)
    return _hash_query(db, f"SELECT {names} FROM {table} ORDER BY {names}")


def _events(home: Path, db) -> tuple[str, int]:
    digest, count = hashlib.sha256(), 0
    sessions = [row[0] for row in db.execute("SELECT session_uid FROM session_identity ORDER BY 1")]
    for session_uid in sessions:
        after = -1
        while True:
            page = event_page(home, session_uid, after_seq=after, limit=PAGE)
            for event in page:
                event.pop("rowid", None)
                digest.update(_encode(event))
            count += len(page)
            if len(page) < PAGE:
                break
            after = page[-1]["seq"]
    return digest.hexdigest(), count


def section_digests(home: str | Path) -> dict[str, dict]:
    """Per-section ``{"sha256", "rows"}``; use to locate which logical layer differs."""
    home = Path(home)
    sections = {}
    with readonly_connection(home / "tandem.db") as db:
        db.execute("BEGIN")  # One snapshot for every section.
        raw_columns = ",".join(RAW_RECORD_COLUMNS)
        sections["raw_record"] = _hash_query(
            db, f"SELECT {raw_columns} FROM raw_record ORDER BY record_uid"
        )
        sections["record_event"] = _sorted_table(db, "record_event", _columns(db, "record_event"))
        sections["event"] = _events(home, db)
        for table in L3_TABLES:
            sections[table] = _sorted_table(db, table, _columns(db, table))
        sections["ingest_issue"] = _sorted_table(
            db, "ingest_issue", ("code", "stage", "file_id", "record_uid")
        )
        sections["inventory"] = _hash_query(
            db,
            "SELECT s.agent,i.type,i.name,i.locator,i.content_hash FROM inventory_item i "
            "JOIN inventory_scan s USING(scan_id) WHERE s.scan_id IN "
            "(SELECT MAX(scan_id) FROM inventory_scan GROUP BY source_key) "
            "ORDER BY 1,2,3,4,5",
        )
    return {name: {"sha256": value[0], "rows": value[1]} for name, value in sections.items()}


def logical_digest(home: str | Path) -> str:
    """One sha256 over all logical sections, in a fixed order."""
    digest = hashlib.sha256(_encode(["tandem-logical-digest", DIGEST_VERSION]))
    for name, value in section_digests(home).items():
        digest.update(_encode([name, value["sha256"], value["rows"]]))
    return digest.hexdigest()


def invariants(home: str | Path, *, verify: bool = True) -> dict:
    """Soundness checks. ``problems`` is empty when every invariant holds."""
    home = Path(home)
    problems = []
    result: dict = {}
    if verify:
        try:
            with Store(home) as store:
                result["verify"] = store.verify()
        except (ValueError, OSError, sqlite3.Error) as error:
            result["verify"] = {"error": f"{type(error).__name__}: {error}"}
            problems.append("verify_failed")
    with readonly_connection(home / "tandem.db") as db:
        db.execute("BEGIN")
        result["foreign_key_violations"] = len(db.execute("PRAGMA foreign_key_check").fetchall())
        result["ledger_inconsistent"] = db.execute(
            "SELECT COUNT(*) FROM v_raw_record_ledger WHERE "
            "(disposition IN ('mapped','folded','replayed','duplicate') AND event_count=0) OR "
            "(disposition IN ('ignored','unparsed') AND event_count>0)"
        ).fetchone()[0]
        result["events_without_provenance"] = db.execute(
            "SELECT COUNT(*) FROM event e WHERE NOT EXISTS "
            "(SELECT 1 FROM record_event re WHERE re.event_uid=e.event_uid)"
        ).fetchone()[0]
        result["current_unparsed"] = db.execute(
            "SELECT COUNT(*) FROM raw_record r JOIN file_record USING(record_uid) "
            "WHERE r.disposition='unparsed'"
        ).fetchone()[0]
        result["dispositions"] = dict(
            db.execute("SELECT disposition,COUNT(*) FROM raw_record GROUP BY 1").fetchall()
        )
        result["records"] = db.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0]
        if sum(result["dispositions"].values()) != result["records"]:
            problems.append("record_accounting")
        published = db.execute(
            "SELECT event_count FROM projection_run ORDER BY run_id DESC LIMIT 1"
        )
        run = published.fetchone()
        events = db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        result["events"] = events
        if run is None:
            problems.append("unpublished")
        elif run[0] != events:
            problems.append("projection_event_count")
    for key in ("foreign_key_violations", "ledger_inconsistent", "events_without_provenance"):
        if result[key]:
            problems.append(key)
    result["problems"] = problems
    return result
