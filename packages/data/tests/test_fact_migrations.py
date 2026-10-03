"""Main's storage v10 and the unpublished analytics v9 converge without data loss."""

import sqlite3

import pytest
from test_migration_008 import LEGACY_FTS

from orbit_data import SCHEMA_VERSION
from orbit_data.contract import canonical
from orbit_data.store import Store


@pytest.mark.parametrize("layout", ["main_v10", "analytics_preview_v9"])
def test_fact_migrations_preserve_records_and_rebuild_native_facts(tmp_path, layout):
    home = tmp_path / "data"
    records = [
        {"type": "session_meta", "payload": {"id": "migration"}},
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "started_at_ms": 1000,
                "completed_at_ms": 4000,
                "item": {
                    "type": "CommandExecution",
                    "id": "command",
                    "command": ["python", "-m", "pytest"],
                    "status": "completed",
                    "exit_code": 0,
                    "duration": {"secs": 2, "nanos": 0},
                },
            },
        },
    ]
    with Store(home) as store:
        source = store.add_source("codex", tmp_path / "source")
        store.capture_stream(
            source, "migration.jsonl", [(canonical(r) + "\n").encode() for r in records]
        )
        store.rebuild()
        before_records = list(
            store.db.execute("SELECT record_uid,sha256 FROM raw_record ORDER BY 1")
        )
        before_events = list(store.db.execute("SELECT event_uid,text,attrs FROM event ORDER BY 1"))
        before_records = [tuple(row) for row in before_records]
        before_events = [tuple(row) for row in before_events]

    with sqlite3.connect(home / "orbit.db") as db:
        # Neither historical layout has the v14 cost/failure/file fields.
        db.execute("DROP TABLE tool_call_file")
        for table, column in (
            ("model_call", "cache_write_1h_tokens"),
            ("model_call", "service_tier"),
            ("tool_call", "failure_kind"),
        ):
            db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        if layout == "main_v10":
            for table, column in (
                ("model_call", "request_identity_quality"),
                ("model_call", "boundary_quality"),
                ("tool_call", "command_spec"),
                ("tool_call", "wall_elapsed_ms"),
                ("tool_call", "native_execution_ms"),
            ):
                db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            version = 10
        else:
            # The unpublished preview had fact columns and the old inline event layout.
            db.executescript(LEGACY_FTS)
            version = 9
        db.execute("UPDATE schema_manifest SET schema_version=?", (version,))
        db.execute(f"PRAGMA user_version={version}")

    with Store(home) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert (
            store.db.execute("SELECT schema_version FROM schema_manifest").fetchone()[0]
            == SCHEMA_VERSION
        )
        assert [
            tuple(row)
            for row in store.db.execute("SELECT record_uid,sha256 FROM raw_record ORDER BY 1")
        ] == before_records
        assert [
            tuple(row)
            for row in store.db.execute("SELECT event_uid,text,attrs FROM event ORDER BY 1")
        ] == before_events
        store.rebuild()
        call = store.db.execute("SELECT * FROM tool_call").fetchone()
        assert call["native_execution_ms"] == 2000
        assert call["wall_elapsed_ms"] == 3000
        assert call["command_spec"] is not None
        # v14 fields exist after the upgrade; a successful command has no failure kind.
        assert "failure_kind" in call.keys() and call["failure_kind"] is None
        columns = {r["name"] for r in store.db.execute("PRAGMA table_info(model_call)")}
        assert {"cache_write_1h_tokens", "service_tier"} <= columns
        assert store.db.execute("SELECT COUNT(*) FROM tool_call_file").fetchone()[0] == 0
        assert store.verify()["integrity"] == "ok"
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
    # Reopening does not reapply fields or downgrade either migration marker.
    with Store(home) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.db.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0] == len(
            before_records
        )
