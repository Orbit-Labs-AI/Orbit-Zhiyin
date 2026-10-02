"""v6 (with or without the reserved 007 FK indexes) and v7 stores upgrade to v8 in place."""

import json
import re
import sqlite3
from importlib.resources import files

import pytest
from test_storage_dedup import import_home, write_sessions

from tandem_data import SCHEMA_VERSION, payload
from tandem_data.query import event_page, trajectory_page
from tandem_data.store import Store

V8_INDEXES = (
    "session_by_started",
    "session_by_project_started",
    "session_by_source_started",
    "tool_by_name_started",
    "record_by_file_locator",
    "source_file_unprojected",
    "source_file_projection_versions",
)
FK_INDEXES = re.findall(
    r"CREATE INDEX IF NOT EXISTS (fk_\w+)",
    files("tandem_data").joinpath("migrations/008.sql").read_text(),
)
LEGACY_FTS = """
DROP TRIGGER event_blob_ai; DROP TRIGGER event_blob_ad; DROP TRIGGER event_blob_au;
DROP TABLE content_blob;
DROP TRIGGER event_search_ai; DROP TRIGGER event_search_ad; DROP TRIGGER event_search_au;
DROP TABLE event_search;
CREATE VIRTUAL TABLE event_fts USING fts5(text, content='event', content_rowid='rowid');
CREATE TRIGGER event_ai AFTER INSERT ON event BEGIN
  INSERT INTO event_fts(rowid,text) VALUES(new.rowid,new.text);
END;
CREATE TRIGGER event_ad AFTER DELETE ON event BEGIN
  INSERT INTO event_fts(event_fts,rowid,text) VALUES('delete',old.rowid,old.text);
END;
CREATE TRIGGER event_au AFTER UPDATE OF text ON event BEGIN
  INSERT INTO event_fts(event_fts,rowid,text) VALUES('delete',old.rowid,old.text);
  INSERT INTO event_fts(rowid,text) VALUES(new.rowid,new.text);
END;
INSERT INTO event_fts(event_fts) VALUES('rebuild');
"""


def snapshot(home):
    with Store(home) as store:
        db = store.db
        sessions = [r[0] for r in db.execute("SELECT session_uid FROM session ORDER BY 1")]
        counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "raw_record",
                "file_record",
                "source_file",
                "source_revision",
                "source_reference",
                "record_location",
                "inventory_scan",
                "inventory_item",
                "event",
                "tool_call",
            )
        }
    pages = [
        (event_page(home, s, limit=1000), trajectory_page(home, s, limit=1000)) for s in sessions
    ]
    return counts, json.dumps(pages, ensure_ascii=False)


def downgrade(home, variant):
    """Rewrite a v8 store into the physical layout of an older release."""
    with sqlite3.connect(home / "tandem.db") as db:
        db.executescript(LEGACY_FTS)
        for name in V8_INDEXES:
            db.execute(f"DROP INDEX {name}")
        if variant == "v6":
            for name in FK_INDEXES:
                db.execute(f"DROP INDEX {name}")
        version = 7 if variant == "v7" else 6
        db.execute("UPDATE schema_manifest SET schema_version=?", (version,))
        db.execute(f"PRAGMA user_version={version}")


@pytest.mark.parametrize("variant", ["v6", "v6_fk", "v7"])
def test_older_stores_upgrade_to_008_preserving_data(tmp_path, variant, monkeypatch):
    source = tmp_path / "claude"
    write_sessions(source)
    home = tmp_path / "home"
    with monkeypatch.context() as patch:
        patch.setattr(payload, "THRESHOLD", 1 << 40)  # Older layouts had inline ext only.
        with import_home(home, source) as store:
            store.db.execute(
                "INSERT INTO inventory_scan VALUES(1,'root','pi','/synthetic','global',NULL,1,'test','{}','[]')"
            )
            store.db.execute(
                "INSERT INTO inventory_item VALUES(1,'item','skill','test','/synthetic/SKILL.md','root',1,'file','{}','hash')"
            )
    before = snapshot(home)
    downgrade(home, variant)
    with sqlite3.connect(home / "tandem.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] in (6, 7)
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='event_fts'").fetchone()

    with Store(home) as store:
        db = store.db
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 8
        assert db.execute("SELECT schema_version FROM schema_manifest").fetchone()[0] == 8
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
        assert set(V8_INDEXES) | set(FK_INDEXES) | {"content_blob", "event_search"} <= names
        assert not {n for n in names if n.startswith("event_fts")}
        assert (
            db.execute("SELECT COUNT(*) FROM event_search").fetchone()[0]
            == db.execute(
                "SELECT COUNT(*) FROM event WHERE kind IN ('message.user','message.assistant','session.title') AND text IS NOT NULL"
            ).fetchone()[0]
        )
        assert store.verify()["integrity"] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        # Physical columns match the published field dictionary.
        saved = json.loads(
            files("tandem_data").joinpath("schemas/tables-v1.schema.json").read_text()
        )["$defs"]
        for table, spec in saved.items():
            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            assert columns == list(spec["properties"]), table
        db.execute("DROP INDEX session_by_started")
    assert snapshot(home) == before

    # Reopening a v8 store does not run 008 again.
    with Store(home) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 8
        assert not store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='session_by_started'"
        ).fetchone()


def test_unknown_future_version_is_rejected(tmp_path):
    home = tmp_path / "home"
    Store(home).db.close()
    with sqlite3.connect(home / "tandem.db") as db:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(ValueError, match="Unsupported database version"):
        Store(home)
