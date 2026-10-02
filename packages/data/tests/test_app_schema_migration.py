"""Both pre-integration v6 layouts upgrade without losing their evidence."""

import json
import sqlite3

import pytest

from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store


@pytest.mark.parametrize("layout", ["archive", "source_reference"])
def test_v6_evidence_survives_schema_integration(tmp_path, layout):
    root, home = tmp_path / "source", tmp_path / "data"
    transcript = root / "sessions" / "fixture.jsonl"
    transcript.parent.mkdir(parents=True)
    raw = b'{"type":"session","id":"s"}\n'
    transcript.write_bytes(raw)
    with Store(home) as store:
        source = store.add_source("pi", root)
        if layout == "archive":
            store.capture_stream(source, "sessions/fixture.jsonl", [raw])
            store.rebuild()
        else:
            ImportService(store).import_source(ImportRequest("pi", root))
        record = store.db.execute("SELECT record_uid FROM raw_record").fetchone()[0]
        revision = tuple(store.db.execute("SELECT * FROM source_revision").fetchone())
    with sqlite3.connect(home / "tandem.db") as db:
        if layout == "archive":
            for table in (
                "record_location",
                "source_reference",
                "usage_observation",
                "source_scan",
            ):
                db.execute(f"DROP TABLE {table}")
            db.execute("DROP INDEX raw_record_session")
        db.execute("PRAGMA user_version=6")
        db.execute("UPDATE schema_manifest SET schema_version=6")
    with Store(home) as upgraded:
        assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert tuple(upgraded.db.execute("SELECT * FROM source_revision").fetchone()) == revision
        assert upgraded.db.execute("SELECT record_uid FROM raw_record").fetchone()[0] == record
        assert json.loads(upgraded.read_raw(record))["id"] == "s"
        assert upgraded.verify()["integrity"] == "ok"
