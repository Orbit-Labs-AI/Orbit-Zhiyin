"""Read-only product queries. Every projection reader checks publication freshness."""

from __future__ import annotations

import json
from pathlib import Path

from tandem_data import MAPPER_VERSION, REDUCER_VERSION, SCHEMA_VERSION, payload
from tandem_data.privacy import REDACTION_VERSION
from tandem_data.store import readonly_connection


def current_projection(connection):
    manifest = connection.execute("SELECT * FROM schema_manifest").fetchone()
    if not manifest or manifest["contract_id"] != "tandem-session-v1":
        raise ValueError("Expected canonical tandem-session-v1")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Storage schema is obsolete; migrate and rebuild before analysis")
    run = connection.execute("SELECT * FROM projection_run ORDER BY run_id DESC LIMIT 1").fetchone()
    revisions = connection.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0]
    if not run or revisions != run["l1_revision_count"]:
        raise ValueError("Projection is pending; rebuild before analysis")
    obsolete = run["mapper_version"] != MAPPER_VERSION or run["reducer_version"] != REDUCER_VERSION
    incomplete = connection.execute(
        "SELECT 1 FROM source_file WHERE COALESCE(json_extract(watermark,'$.projected_revision'),-1) <> COALESCE(json_extract(watermark,'$.revision'),0) "
        "OR COALESCE(json_extract(watermark,'$.mapper_version'),'')<>? OR COALESCE(json_extract(watermark,'$.reducer_version'),'')<>? OR COALESCE(json_extract(watermark,'$.redaction_version'),'')<>? LIMIT 1",
        (MAPPER_VERSION, REDUCER_VERSION, REDACTION_VERSION),
    ).fetchone()
    if obsolete or incomplete:
        raise ValueError("Projection version is obsolete or incomplete; rebuild before analysis")
    return manifest, run


def event_page(
    home: Path, session_uid: str, *, after_seq: int = -1, limit: int = 100
) -> list[dict]:
    """Cursor pagination for the product App. Does not load L0 or full session histories."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    with readonly_connection(Path(home) / "tandem.db") as db:
        db.execute("BEGIN")
        current_projection(db)
        rows = db.execute(
            "SELECT * FROM event WHERE session_uid=? AND seq>? ORDER BY seq LIMIT ?",
            (session_uid, after_seq, limit),
        )
        cache: dict = {}
        return [
            {
                **dict(row),
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
    with readonly_connection(Path(home) / "tandem.db") as db:
        db.execute("BEGIN")
        _, run = current_projection(db)
        if run_id is not None and run_id != run["run_id"]:
            raise ValueError("Trajectory publication changed; restart pagination")
        if not db.execute(
            "SELECT 1 FROM session_identity WHERE session_uid=?", (session_uid,)
        ).fetchone():
            raise KeyError(session_uid)
        scope = "WITH RECURSIVE selected(id) AS (SELECT ? UNION SELECT s.session_uid FROM session s JOIN selected p ON s.parent_uid=p.id WHERE ?) "
        where = (
            "FROM raw_record r JOIN file_record c USING(record_uid) JOIN source_file f ON f.file_id=r.file_id "
            "LEFT JOIN record_location l ON l.record_uid=r.record_uid AND l.revision_uid=(SELECT revision_uid FROM source_revision v WHERE v.file_id=f.file_id ORDER BY revision DESC LIMIT 1) "
            "WHERE r.session_uid IN (SELECT id FROM selected) OR r.record_uid IN "
            "(SELECT x.record_uid FROM record_event x JOIN event e USING(event_uid) WHERE e.session_uid IN (SELECT id FROM selected)) OR (f.format<>'sqlite_rows' "
            "AND f.role IN ('transcript','subagent_transcript','legacy_transcript') AND f.file_id IN "
            "(SELECT file_id FROM raw_record WHERE session_uid IN (SELECT id FROM selected)))"
        )
        args = (session_uid, include_children)
        total = db.execute(scope + "SELECT COUNT(*) " + where, args).fetchone()[0]
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
