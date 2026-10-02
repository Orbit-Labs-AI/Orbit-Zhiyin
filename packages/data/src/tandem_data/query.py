"""Read-only product queries. Every projection reader checks publication freshness."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from tandem_data import MAPPER_VERSION, REDUCER_VERSION
from tandem_data.store import readonly_connection


def current_projection(connection):
    manifest = connection.execute("SELECT * FROM schema_manifest").fetchone()
    if not manifest or manifest["contract_id"] != "tandem-session-v1":
        raise ValueError("Expected canonical tandem-session-v1")
    run = connection.execute("SELECT * FROM projection_run ORDER BY run_id DESC LIMIT 1").fetchone()
    revisions = connection.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0]
    if not run or revisions != run["l1_revision_count"]:
        raise ValueError("Projection is pending; rebuild before analysis")
    obsolete = run["mapper_version"] != MAPPER_VERSION or run["reducer_version"] != REDUCER_VERSION
    incomplete = connection.execute(
        "SELECT 1 FROM source_file WHERE COALESCE(json_extract(watermark,'$.projected_revision'),-1) <> COALESCE(json_extract(watermark,'$.revision'),0) "
        "OR COALESCE(json_extract(watermark,'$.mapper_version'),'')<>? OR COALESCE(json_extract(watermark,'$.reducer_version'),'')<>? LIMIT 1",
        (MAPPER_VERSION, REDUCER_VERSION),
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
    with closing(readonly_connection(Path(home) / "tandem.db")) as db:
        db.execute("BEGIN")
        current_projection(db)
        rows = db.execute(
            "SELECT * FROM event WHERE session_uid=? AND seq>? ORDER BY seq LIMIT ?",
            (session_uid, after_seq, limit),
        )
        return [
            {
                **dict(row),
                "attrs": json.loads(row["attrs"]),
                "ext": json.loads(row["ext"]),
                "native_key": json.loads(row["native_key"]),
            }
            for row in rows
        ]
