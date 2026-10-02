import json
import sqlite3
from importlib.resources import files

import pytest
import zstandard

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.contract import canonical
from tandem_data.service import ImportRequest, ImportService
from tandem_data.source_reader import record_source
from tandem_data.store import Store, sqlite_rows


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(r) + "\n" for r in rows))


def pi_rows(identity, text):
    return [
        {"type": "session", "id": identity},
        {"type": "message", "id": "m", "message": {"role": "user", "content": text}},
    ]


def test_deleted_source_does_not_block_other_sessions_and_recovers(tmp_path):
    root = tmp_path / "pi"
    old, live = root / "sessions/old.jsonl", root / "sessions/live.jsonl"
    original = pi_rows("old", "published before deletion")
    write(old, original)
    write(live, pi_rows("live", "first"))
    with Store(tmp_path / "data") as store:
        service, request = ImportService(store), ImportRequest("pi", root)
        service.import_source(request)
        record = store.db.execute(
            "SELECT record_uid FROM event WHERE text='published before deletion'"
        ).fetchone()[0]
        old.unlink()
        write(live, pi_rows("live", "updated"))
        assert service.import_source(request)["current_unparsed"] == 0
        bundle = read_analysis(store.home, AnalysisScope("UTC"))
        assert {e["text"] for e in bundle["events"] if e["kind"] == "message.user"} == {
            "updated",
            "published before deletion",
        }
        retained = next(e for e in bundle["events"] if e["text"] == "published before deletion")
        assert retained["attrs"]["source_status"] == "missing"
        assert "source_unavailable_preserved_facts" in bundle["coverage"]["events"]["reasons"]
        assert record_source(store.home, record)["status"] == "missing"
        assert store.verify()["integrity"] == "partial"
        assert not list(store.raw_dir.iterdir())
        # Repeated rebuilds preserve accounting; restoring the same bytes clears stale labels.
        store.rebuild()
        write(old, original)
        assert service.import_source(request)["changed"] == 1
        assert record_source(store.home, record)["status"] == "available"
        assert not store.db.execute(
            "SELECT 1 FROM ingest_issue WHERE code='source_unavailable'"
        ).fetchone()
        assert store.verify()["integrity"] == "ok"


def test_codex_nonadjacent_idless_and_multiblock_representations(tmp_path):
    root = tmp_path / "codex"
    rows = [
        {"type": "session_meta", "payload": {"id": "s"}},
        {"type": "event_msg", "payload": {"type": "turn_started", "turn_id": "t"}},
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "turn_id": "t",
                "item": {"type": "UserMessage", "content": [{"type": "text", "text": "prompt"}]},
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "prompt"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "part one\npart two"},
        },
        *[{"type": "event_msg", "payload": {"type": "item_started"}} for _ in range(4)],
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "part one"},
                    {"type": "output_text", "text": "part two"},
                ],
            },
        },
    ]
    write(root / "sessions/rollout-s.jsonl", rows)
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("codex", root))
        assert result["current_unparsed"] == result["unknown_events"] == 0
        messages = store.db.execute(
            "SELECT kind,text FROM event WHERE kind LIKE 'message.%' ORDER BY seq"
        ).fetchall()
        assert [tuple(m) for m in messages] == [
            ("message.user", "prompt"),
            ("message.assistant", "part one\npart two"),
        ]
        assert store.verify()["integrity"] == "ok"


def test_live_shared_event_wins_over_missing_cached_representation(tmp_path):
    root = tmp_path / "claude"
    first, second = root / "projects/p/a.jsonl", root / "projects/p/b.jsonl"

    def rows(text):
        return [
            {
                "sessionId": "s",
                "type": "assistant",
                "uuid": "same-message",
                "message": {"content": text},
            }
        ]

    write(first, rows("original long reply"))
    write(second, rows("original long reply"))
    with Store(tmp_path / "data") as store:
        service, request = ImportService(store), ImportRequest("claude_code", root)
        service.import_source(request)
        first.unlink()
        write(second, rows("corrected"))
        service.import_source(request)
        event = store.db.execute(
            "SELECT text,attrs FROM event WHERE kind='message.assistant'"
        ).fetchone()
        assert event["text"] == "corrected"
        assert "source_status" not in json.loads(event["attrs"])
        assert store.verify()["integrity"] == "partial"


def test_old_archive_keeps_its_encoding_after_native_compression_migration(tmp_path):
    root = tmp_path / "pi"
    root.mkdir()
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", root)
        old = "".join(canonical(r) + "\n" for r in pi_rows("s", "old archived text")).encode()
        new = "".join(canonical(r) + "\n" for r in pi_rows("s", "new text")).encode()
        store.capture_stream(source, "sessions/s.jsonl", [old])
        record = store.db.execute("SELECT record_uid FROM raw_record WHERE ordinal=1").fetchone()[0]
        store.capture_stream(source, "sessions/s.jsonl", [new])
        store.db.execute("UPDATE source_revision SET source_stat='{}'")  # Pre-index archive schema.
        # A previously archived logical file is now represented by a native compressed file.
        path = root / "sessions/s.jsonl.zst"
        path.parent.mkdir()
        path.write_bytes(zstandard.ZstdCompressor().compress(new))
        store.db.execute("UPDATE source_file SET status='gone_upstream'")
        store.capture_file(source, path)
        assert json.loads(store.read_raw(record))["message"]["content"] == "old archived text"
        original = record_source(store.home, record, include_content=True)
        assert original["status"] == "available" and "old archived text" in original["content"]
        assert store.verify()["integrity"] == "ok"


def test_archive_to_native_keeps_cumulative_observation_history(tmp_path):
    root = tmp_path / "hermes"
    root.mkdir()
    path = root / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY); INSERT INTO sessions VALUES('s');"
            "CREATE TABLE session_model_usage(session_id TEXT,model TEXT,input_tokens INTEGER,last_seen REAL,PRIMARY KEY(session_id,model));"
            "INSERT INTO session_model_usage VALUES('s','model',10,100);"
        )
    with Store(tmp_path / "data") as store:
        source = store.add_source("hermes", root)
        store.capture_stream(
            source, "state.db", sqlite_rows(path, "hermes"), format_name="sqlite_rows"
        )
        store.rebuild()
        with sqlite3.connect(path) as db:
            db.execute("UPDATE session_model_usage SET input_tokens=20,last_seen=200")
        service, request = ImportService(store), ImportRequest("hermes", root)
        service.import_source(request)
        observations = [
            json.loads(r[0])["reported"]["input_tokens"]
            for r in store.db.execute(
                "SELECT attrs FROM event WHERE kind='model.usage' ORDER BY ts"
            )
        ]
        assert observations == [10, 20]
        assert service.import_source(request)["changed"] == 0
        assert store.db.execute("SELECT COUNT(*) FROM usage_snapshot").fetchone()[0] == 2
        assert store.verify()["integrity"] == "ok"


@pytest.mark.parametrize("v5_variant", ["inventory", "source_reference"])
def test_both_v5_variants_migrate_without_losing_data(tmp_path, v5_variant):
    home = tmp_path / "data"
    home.mkdir()
    with sqlite3.connect(home / "tandem.db") as db:
        for name in ("001.sql", "002.sql", "003.sql", "004.sql"):
            db.executescript(files("tandem_data").joinpath("migrations/" + name).read_text())
        db.execute(
            "INSERT INTO source(source_id,agent,root_path,discovered_at) VALUES('s','pi','/synthetic',0)"
        )
        db.commit()
        if v5_variant == "inventory":
            db.executescript(files("tandem_data").joinpath("migrations/005.sql").read_text())
            db.execute(
                "INSERT INTO inventory_scan VALUES(1,'root','pi','/synthetic','global',NULL,1,'test','{}','[]')"
            )
            db.execute(
                "INSERT INTO inventory_item VALUES(1,'item','skill','test','/synthetic/SKILL.md','root',1,'file','{}','hash')"
            )
        else:
            db.executescript(files("tandem_data").joinpath("migrations/006.sql").read_text())
            db.execute("PRAGMA user_version=5")
            db.execute("UPDATE schema_manifest SET schema_version=5")
            db.execute("INSERT INTO source_scan VALUES('s',1,'full',0,0,0,0)")
    with Store(home) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
        if v5_variant == "inventory":
            assert store.db.execute("SELECT name FROM inventory_item").fetchone()[0] == "test"
        else:
            assert store.db.execute("SELECT selection FROM source_scan").fetchone()[0] == "full"
        store.rebuild()
        bundle = read_analysis(home, AnalysisScope("UTC"))
        assert bundle["db_schema_version"] == 6
        assert "inventory" in bundle["coverage"]
        assert "source_scans" in bundle["coverage"]
