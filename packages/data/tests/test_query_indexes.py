"""Product query plans: indexed lists, rewritten trajectory query, index-only freshness."""

import json
import time

import pytest
from test_storage_dedup import import_home, write_sessions

from orbit_data.query import (
    UNPROJECTED,
    current_projection,
    projection_state,
    source_status,
    trajectory_page,
)
from orbit_data.store import Store, readonly_connection


def plan(db, sql, args=()):
    return " | ".join(r[3] for r in db.execute("EXPLAIN QUERY PLAN " + sql, args))


def test_every_foreign_key_has_a_leading_index(tmp_path):
    with Store(tmp_path / "home") as store:
        db = store.db
        missing = []
        for (table,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE 'CREATE TABLE%'"
        ).fetchall():
            leading = {
                next(iter(db.execute(f'PRAGMA index_info("{index[1]}")')), (0, 0, None))[2]
                for index in db.execute(f'PRAGMA index_list("{table}")')
            }
            leading |= {r[1] for r in db.execute(f'PRAGMA table_info("{table}")') if r[5] == 1}
            missing += [
                f"{table}.{fk[3]}"
                for fk in db.execute(f'PRAGMA foreign_key_list("{table}")')
                if fk[3] not in leading
            ]
        assert missing == []


def test_list_and_tool_queries_avoid_temp_sorts(tmp_path):
    source = tmp_path / "claude"
    write_sessions(source)
    with import_home(tmp_path / "home", source) as store:
        db = store.db
        project = db.execute("SELECT project_id FROM session LIMIT 1").fetchone()[0]
        source_id = db.execute("SELECT source_id FROM session LIMIT 1").fetchone()[0]
        for sql, args in (
            ("SELECT * FROM session ORDER BY started_at DESC LIMIT 50", ()),
            (
                "SELECT * FROM session WHERE project_id=? ORDER BY started_at DESC LIMIT 50",
                (project,),
            ),
            (
                "SELECT * FROM session WHERE source_id=? ORDER BY started_at DESC LIMIT 50",
                (source_id,),
            ),
            ("SELECT * FROM tool_call WHERE name=? ORDER BY started_at DESC LIMIT 5", ("Bash",)),
            (
                "SELECT MAX(version) FROM raw_record WHERE file_id=? AND locator=?",
                ("f", '["line",0]'),
            ),
        ):
            text = plan(db, sql, args)
            assert "TEMP B-TREE" not in text and "SCAN raw_record" not in text, (sql, text)
        assert "USING INDEX tool_by_name_started" in plan(
            db, "SELECT * FROM tool_call WHERE name='Bash' ORDER BY started_at DESC LIMIT 5"
        )
        # Freshness reads a partial index and an expression index, never every watermark.
        freshness = (
            plan(
                db,
                "SELECT 1 FROM source_file WHERE COALESCE(json_extract(watermark,'$.projected_revision'),-1) <> COALESCE(json_extract(watermark,'$.revision'),0) LIMIT 1",
            )
            + plan(db, f"SELECT watermark FROM source_file WHERE {UNPROJECTED}")
            + plan(
                db,
                "SELECT COUNT(*) FROM source_file WHERE json_extract(watermark,'$.mapper_version')=? "
                "AND json_extract(watermark,'$.reducer_version')=? AND json_extract(watermark,'$.redaction_version')=?",
                ("a", "b", "c"),
            )
        )
        assert "source_file_unprojected" in freshness
        assert "source_file_projection_versions" in freshness


def test_freshness_detects_every_incomplete_file(tmp_path):
    source = tmp_path / "claude"
    write_sessions(source)
    home = tmp_path / "home"
    import_home(home, source).db.close()
    with readonly_connection(home / "orbit.db") as db:
        current_projection(db)
    # An unpublished file only makes the published snapshot stale (pending); facts of an
    # older mapper or redaction make it unreadable until a rebuild (obsolete).
    for change, expected in (
        ("json_remove(watermark,'$.projected_revision')", "pending"),
        ("json_set(watermark,'$.mapper_version','0.0.0')", "obsolete or incomplete"),
        ("json_remove(watermark,'$.redaction_version')", "obsolete or incomplete"),
    ):
        with Store(home) as store:
            original = store.db.execute(
                "SELECT file_id,watermark FROM source_file LIMIT 1"
            ).fetchone()
            store.db.execute(
                f"UPDATE source_file SET watermark={change} WHERE file_id=?", (original[0],)
            )
        with readonly_connection(home / "orbit.db") as db:
            try:
                current_projection(db)
                raise AssertionError(change)
            except ValueError as error:
                assert expected in str(error)
            if expected == "pending":
                state = projection_state(db)
                assert state["pending"] and state["pending_files"] == 1
                assert state["run"]["run_id"] == 1  # The published snapshot stays readable.
        with Store(home) as store:
            store.db.execute("UPDATE source_file SET watermark=? WHERE file_id=?", original[::-1])


@pytest.mark.serial
def test_trajectory_page_matches_reference_query(tmp_path):
    source = tmp_path / "claude"
    write_sessions(source)
    home = tmp_path / "home"
    import_home(home, source).db.close()
    reference = (
        "WITH RECURSIVE selected(id) AS (SELECT ? UNION SELECT s.session_uid FROM session s JOIN selected p ON s.parent_uid=p.id WHERE ?) "
        "SELECT r.record_uid FROM raw_record r JOIN file_record c USING(record_uid) JOIN source_file f ON f.file_id=r.file_id "
        "WHERE r.session_uid IN (SELECT id FROM selected) OR r.record_uid IN "
        "(SELECT x.record_uid FROM record_event x JOIN event e USING(event_uid) WHERE e.session_uid IN (SELECT id FROM selected)) OR (f.format<>'sqlite_rows' "
        "AND f.role IN ('transcript','subagent_transcript','legacy_transcript') AND f.file_id IN "
        "(SELECT file_id FROM raw_record WHERE session_uid IN (SELECT id FROM selected)))"
    )
    with readonly_connection(home / "orbit.db") as db:
        sessions = [r[0] for r in db.execute("SELECT session_uid FROM session")]
        for session in sessions:
            expected = sorted(r[0] for r in db.execute(reference, (session, True)))
            page = trajectory_page(home, session, limit=1000)
            assert page["total"] == len(expected)
            assert sorted(item["record_uid"] for item in page["items"]) == expected
            # Paging covers the same records in the same order.
            first = trajectory_page(home, session, limit=7)
            assert [i["record_uid"] for i in first["items"]] == [
                i["record_uid"] for i in page["items"][:7]
            ]
            json.dumps(page)
        start = time.perf_counter()
        trajectory_page(home, sessions[0], limit=100)
        assert time.perf_counter() - start < 1.0
        status = source_status(db)
        assert [(s["agent"], s["sessions"]) for s in status] == [("claude_code", len(sessions))]
        assert status[0]["files"] == 2 and status[0]["last_scan_at"]
