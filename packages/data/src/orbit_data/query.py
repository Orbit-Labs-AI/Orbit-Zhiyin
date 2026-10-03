"""Read-only product queries. Every projection reader checks publication freshness.

Freshness has three outcomes (``projection_state``):

* **ready** — every captured L1 revision is reflected in the published L2/L3;
* **pending** — newer L1 revisions are captured but not yet published (an import is
  between capture and publication, or one was interrupted). The published projection is
  still one consistent, committed snapshot: readers of L2/L3 may serve it, marked stale;
* **invalid** — nothing valid to read (wrong contract, obsolete schema, no publication
  yet, output of an obsolete mapper/reducer): ``ValueError``.

A file whose source changed again between capture and projection keeps its previously
published facts and is marked *retained* at that revision (``watermark.retained_revision``
plus the versions that attempted it). A retained revision is settled: it is neither
pending nor stale until the next capture records a newer revision, so one live file can
no longer keep every later import rebuilding its source (docs/development/import-pipeline.md).
"""

from __future__ import annotations

import json
from pathlib import Path

from orbit_data import MAPPER_VERSION, REDUCER_VERSION, SCHEMA_VERSION, payload
from orbit_data.privacy import REDACTION_VERSION
from orbit_data.store import readonly_connection

# Trajectory totals per (home, session, children, publication); a publication is immutable.
_TOTALS: dict[tuple, int] = {}

# Exactly the predicate of the v8 partial index ``source_file_unprojected``.
UNPROJECTED = (
    "COALESCE(json_extract(watermark,'$.projected_revision'),-1) <> "
    "COALESCE(json_extract(watermark,'$.revision'),0)"
)
# A revision whose projection retained the previous facts under the current versions.
SETTLED = (
    "(COALESCE(json_extract(watermark,'$.retained_revision'),-1) = "
    "COALESCE(json_extract(watermark,'$.revision'),0) AND "
    "COALESCE(json_extract(watermark,'$.retained_versions'),'') = ?)"
)
PENDING_MESSAGE = "Projection is pending; rebuild before analysis"
OBSOLETE_MESSAGE = "Projection version is obsolete or incomplete; rebuild before analysis"


def projection_versions() -> str:
    """The versions a retained revision was attempted with (``retained_versions``)."""
    return f"{MAPPER_VERSION}|{REDUCER_VERSION}|{REDACTION_VERSION}"


def settled(watermark: dict) -> bool:
    return watermark.get("retained_revision") == watermark.get("revision", 0) and (
        watermark.get("retained_versions") == projection_versions()
    )


def projection_state(connection) -> dict:
    """Published run and its freshness; raises ``ValueError`` only when nothing is readable.

    ``pending_files`` counts captured files whose newest revision is not published yet;
    ``retained_files`` counts settled retained files (their previous facts are published
    and flagged by a ``source_unavailable`` issue).
    """
    manifest = connection.execute("SELECT * FROM schema_manifest").fetchone()
    if not manifest or manifest["contract_id"] != "orbit-session-v1":
        raise ValueError("Expected canonical orbit-session-v1")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Storage schema is obsolete; migrate and rebuild before analysis")
    run = connection.execute("SELECT * FROM projection_run ORDER BY run_id DESC LIMIT 1").fetchone()
    if not run:
        raise ValueError(PENDING_MESSAGE)  # Nothing published yet (the first import runs).
    if run["mapper_version"] != MAPPER_VERSION or run["reducer_version"] != REDUCER_VERSION:
        raise ValueError(OBSOLETE_MESSAGE)
    # The unprojected set is small (captured, not yet published); the partial index finds it.
    pending = retained = unprojected_current = gap = 0
    for row in connection.execute(f"SELECT watermark FROM source_file WHERE {UNPROJECTED}"):
        watermark = json.loads(row[0])
        if settled(watermark):
            retained += 1
            gap += watermark.get("revision", 0) - (watermark.get("projected_revision") or 0)
        else:
            pending += 1
        unprojected_current += (
            watermark.get("mapper_version"),
            watermark.get("reducer_version"),
            watermark.get("redaction_version"),
        ) == (MAPPER_VERSION, REDUCER_VERSION, REDACTION_VERSION)
    total = connection.execute("SELECT COUNT(*) FROM source_file").fetchone()[0]
    current = connection.execute(
        "SELECT COUNT(*) FROM source_file WHERE json_extract(watermark,'$.mapper_version')=? "
        "AND json_extract(watermark,'$.reducer_version')=? AND json_extract(watermark,'$.redaction_version')=?",
        (MAPPER_VERSION, REDUCER_VERSION, REDACTION_VERSION),
    ).fetchone()[0]
    # Published files whose facts came from an older mapper/reducer/redaction need a rebuild;
    # unprojected files (pending or settled) are accounted for above.
    unprojected = pending + retained
    if total - current - (unprojected - unprojected_current) > 0:
        raise ValueError(OBSOLETE_MESSAGE)
    revisions = connection.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0]
    # Revisions this run accounts for: projected ones plus settled retained ones.
    behind = revisions - gap != run["l1_revision_count"]
    return {
        "manifest": manifest,
        "run": run,
        "pending": bool(pending or behind),
        "pending_files": pending,
        "retained_files": retained,
    }


def current_projection(connection):
    """Strict check for readers that mix L1 and L2 (or must not serve a stale snapshot)."""
    state = projection_state(connection)
    if state["pending"]:
        raise ValueError(PENDING_MESSAGE)
    return state["manifest"], state["run"]


def published_projection(connection):
    """For L2/L3 readers: the published snapshot, also while newer captures are pending.

    Returns ``(manifest, run, state)``; ``state["pending"]`` tells the caller to mark its
    answer stale instead of failing it.
    """
    state = projection_state(connection)
    return state["manifest"], state["run"], state


def source_status(connection) -> list[dict]:
    """Per-source session/file counts and last scan, using per-source index lookups."""
    return [
        dict(row)
        for row in connection.execute(
            "SELECT s.source_id,s.agent,s.label,"
            "(SELECT COUNT(*) FROM session x WHERE x.source_id=s.source_id) AS sessions,"
            "(SELECT COUNT(*) FROM source_file f WHERE f.source_id=s.source_id) AS files,"
            "(SELECT MAX(f.last_scan_at) FROM source_file f WHERE f.source_id=s.source_id) AS last_scan_at "
            "FROM source s ORDER BY s.source_id"
        )
    ]


def event_page(
    home: Path, session_uid: str, *, after_seq: int = -1, limit: int = 100
) -> list[dict]:
    """Cursor pagination for the product App. Does not load L0 or full session histories."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    with readonly_connection(Path(home) / "orbit.db") as db:
        db.execute("BEGIN")
        published_projection(db)  # L2 only: the published snapshot, also while pending.
        rows = db.execute(
            "SELECT * FROM event WHERE session_uid=? AND seq>? ORDER BY seq LIMIT ?",
            (session_uid, after_seq, limit),
        )
        cache: dict = {}
        return [
            {
                **payload.restore_row(db, row, cache),
                "attrs": json.loads(row["attrs"]),
                "ext": payload.restore(db, json.loads(row["ext"]), cache),
                "native_key": json.loads(row["native_key"]),
            }
            for row in rows.fetchall()
        ]


def trajectory_page(home, session_uid, *, after=0, limit=100, run_id=None, include_children=True):
    """All indexed native records, including ignored/unknown/replayed records, with L2 links.

    Pagination limits record count, never content length. A publication ID pins a page
    sequence so rescans cannot silently shift a user's cursor. Per-file native order is
    preserved; records from different files are not assigned a fabricated global clock.
    """
    if after < 0 or not 1 <= limit <= 1000:
        raise ValueError("Invalid trajectory cursor or page size")
    with readonly_connection(Path(home) / "orbit.db") as db:
        db.execute("BEGIN")
        _, run = current_projection(db)
        if run_id is not None and run_id != run["run_id"]:
            raise ValueError("Trajectory publication changed; restart pagination")
        if not db.execute(
            "SELECT 1 FROM session_identity WHERE session_uid=?", (session_uid,)
        ).fetchone():
            raise KeyError(session_uid)
        # Materialise the record set first (three indexed branches), then join; an
        # OR over IN-subqueries forces a full raw_record scan. CROSS JOIN pins the
        # small driving set as the outer loop so each branch is an index lookup.
        scope = (
            "WITH RECURSIVE selected(id) AS (SELECT ? UNION SELECT s.session_uid FROM selected p CROSS JOIN session s INDEXED BY fk_session_parent_uid ON s.parent_uid=p.id WHERE ?), "
            "sessions(id) AS MATERIALIZED (SELECT id FROM selected), "
            "touched(file_id) AS MATERIALIZED (SELECT DISTINCT r.file_id FROM sessions s CROSS JOIN raw_record r ON r.session_uid=s.id), "
            "picked(record_uid) AS MATERIALIZED ("
            "SELECT r.record_uid FROM sessions s CROSS JOIN raw_record r ON r.session_uid=s.id "
            "UNION SELECT x.record_uid FROM sessions s CROSS JOIN event e ON e.session_uid=s.id CROSS JOIN record_event x ON x.event_uid=e.event_uid "
            "UNION SELECT r.record_uid FROM touched t CROSS JOIN source_file f ON f.file_id=t.file_id CROSS JOIN raw_record r ON r.file_id=t.file_id "
            "WHERE f.format<>'sqlite_rows' AND f.role IN ('transcript','subagent_transcript','legacy_transcript')) "
        )
        where = (
            "FROM picked p CROSS JOIN raw_record r ON r.record_uid=p.record_uid JOIN file_record c ON c.record_uid=r.record_uid "
            "JOIN source_file f ON f.file_id=r.file_id "
            "LEFT JOIN record_location l ON l.record_uid=r.record_uid AND l.revision_uid=(SELECT revision_uid FROM source_revision v WHERE v.file_id=f.file_id ORDER BY revision DESC LIMIT 1) "
        )
        args = (session_uid, include_children)
        key = (
            str(Path(home).resolve()),
            session_uid,
            bool(include_children),
            run["run_id"],
            run["completed_at"],
        )
        total = _TOTALS.get(key)
        if total is None:
            total = db.execute(scope + "SELECT COUNT(*) " + where, args).fetchone()[0]
            if len(_TOTALS) >= 256:
                _TOTALS.clear()
            _TOTALS[key] = total
        records = []
        for row in db.execute(
            scope
            + "SELECT r.*,f.relative_path,f.format,f.status AS source_status,COALESCE(l.ordinal,r.ordinal) AS current_ordinal "
            + where
            + " ORDER BY f.relative_path,current_ordinal,r.record_uid LIMIT ? OFFSET ?",
            (*args, limit, after),
        ):
            item = dict(row)
            item["ordinal"] = item.pop("current_ordinal")
            for key in ("locator", "note"):
                item[key] = json.loads(item[key])
            item["events"] = [
                dict(e)
                for e in db.execute(
                    "SELECT x.event_uid,x.relation,e.kind,e.seq,e.session_uid FROM record_event x JOIN event e USING(event_uid) WHERE x.record_uid=? ORDER BY e.session_uid,e.seq",
                    (row["record_uid"],),
                )
            ]
            item["source_url"] = f"/v1/records/{row['record_uid']}/source"
            records.append(item)
        return {
            "run_id": run["run_id"],
            "session_uid": session_uid,
            "total": total,
            "items": records,
            "next_after": after + len(records) if after + len(records) < total else None,
            "order": "source_file_then_native_ordinal",
        }
