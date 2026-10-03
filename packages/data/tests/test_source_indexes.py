import hashlib
import json
import sqlite3

import pytest
import zstandard

from orbit_data.analysis_input import AnalysisScope, read_analysis
from orbit_data.contract import canonical
from orbit_data.discovery import inputs
from orbit_data.query import event_page, trajectory_page
from orbit_data.service import ImportRequest, ImportService
from orbit_data.source_reader import SourceUnavailable, record_source
from orbit_data.store import Store
from orbit_data.validation.fixtures import create_sources

LONG = "完整正文🙂\n" * 9000


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows))


def codex_rows():
    return [
        {"type": "session_meta", "payload": {"id": "s", "cwd": "/synthetic"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": LONG}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": LONG}},
        {
            "type": "event_msg",
            "payload": {
                "type": "exec_command_end",
                "call_id": "tool",
                "aggregated_output": LONG,
                "exit_code": 0,
            },
        },
    ]


@pytest.mark.parametrize(
    "agent", ["claude_code", "codex", "dsh", "pi", "hermes", "opencode", "kimi"]
)
def test_seven_native_agents_index_without_copying_and_return_full_text(tmp_path, agent):
    roots = create_sources(tmp_path / "sources")
    roots["codex"] = tmp_path / "sources/codex"
    write_rows(roots["codex"] / "sessions/rollout-s.jsonl", codex_rows())
    root = roots[agent]
    # Put the same long user/tool text in each actual native storage layout.
    for item in inputs(agent, root):
        if item.path.suffix == ".jsonl":
            item.path.write_text(
                item.path.read_text().replace("检查仓库状态", LONG.replace("\n", "\\n"))
            )
        elif item.path.suffix == ".db":
            with sqlite3.connect(item.path) as db:
                for table in ("messages", "part", "session_message"):
                    columns = list(db.execute(f'PRAGMA table_info("{table}")'))
                    for column in ("content", "data"):
                        if column in {r[1] for r in columns}:
                            replacement = LONG if column == "content" else LONG.replace("\n", "\\n")
                            db.execute(
                                f'UPDATE "{table}" SET "{column}"=replace("{column}",?,?)',
                                ("检查仓库状态", replacement),
                            )
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest(agent, root))
        assert result["current_unparsed"] == result["capture_errors"] == 0
        assert store.db.execute("SELECT COUNT(*) FROM archive_blob").fetchone()[0] == 0
        assert not list(store.raw_dir.iterdir())
        assert store.db.execute("SELECT COUNT(*) FROM source_reference").fetchone()[0] > 0
        assert not store.db.execute("SELECT 1 FROM event WHERE text_truncated<>0").fetchone()
        events = store.db.execute("SELECT * FROM event WHERE kind='message.user'").fetchall()
        assert any(row["text"] == LONG for row in events), [
            (r["kind"], len(r["text"] or "")) for r in events
        ]
        selected = next(row for row in events if row["text"] == LONG)
        original = store.read_raw(selected["record_uid"])
        source = record_source(store.home, selected["record_uid"], include_content=True)
        assert source["status"] == "available"
        assert source["content"].encode() == original
        assert hashlib.sha256(original).hexdigest() == source["sha256"]
        assert event_page(store.home, selected["session_uid"], limit=1000)
        verified = store.verify()
        assert verified["integrity"] == "ok"
        assert verified["source_references_verified"] > 0
        assert verified["record_hashes_verified"] > 0


def test_index_shift_rewrite_delete_and_full_original_access(tmp_path):
    root = tmp_path / "codex"
    path = root / "sessions/rollout-s.jsonl"
    rows = codex_rows()
    write_rows(path, rows)
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("codex", root))
        record = store.db.execute(
            "SELECT record_uid FROM event WHERE kind='message.assistant'"
        ).fetchone()[0]
        original = store.read_raw(record)
        rows[0]["payload"]["extra"] = "a shifted header"
        write_rows(path, rows)
        assert record_source(store.home, record)["status"] == "changed"
        service.import_source(ImportRequest("codex", root))
        assert store.read_raw(record) == original  # unchanged row, updated offset
        rows[2]["payload"]["message"] = "replaced reply"
        write_rows(path, rows)
        with pytest.raises(SourceUnavailable):
            store.read_raw(record)
        service.import_source(ImportRequest("codex", root))
        assert record_source(store.home, record)["status"] == "changed"
        path.unlink()
        assert record_source(store.home, record)["status"] == "missing"
        assert store.verify()["integrity"] == "partial"
        assert (
            store.db.execute("SELECT text FROM event WHERE kind='message.assistant'").fetchone()[0]
            == "replaced reply"
        )


def test_compressed_index_and_incomplete_frame_do_not_copy_or_replace_tables(tmp_path):
    root = tmp_path / "codex"
    path = root / "sessions/rollout-s.jsonl.zst"
    path.parent.mkdir(parents=True)
    data = "".join(canonical(r) + "\n" for r in codex_rows()).encode()
    frame = zstandard.ZstdCompressor().compress(data)
    path.write_bytes(frame)
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("codex", root))
        record = store.db.execute(
            "SELECT record_uid FROM event WHERE kind='message.assistant'"
        ).fetchone()[0]
        assert json.loads(store.read_raw(record))["payload"]["message"] == LONG
        count = store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        path.write_bytes(frame[:-3])
        result = service.import_source(ImportRequest("codex", root))
        assert result["capture_errors"] == 1
        assert store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0] == count
        assert store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0] == 1
        assert not list(store.raw_dir.iterdir())


def test_sqlite_primary_key_read_and_cumulative_observations_survive_updates(tmp_path):
    root = tmp_path / "hermes"
    root.mkdir()
    path = root / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY); INSERT INTO sessions VALUES('s');"
            "CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT);"
            "INSERT INTO messages VALUES(1,'s','user','original');"
            "CREATE TABLE session_model_usage(session_id TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,last_seen REAL,PRIMARY KEY(session_id,model));"
            "INSERT INTO session_model_usage VALUES('s','model',10,2,100);"
        )
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("hermes", root))
        record = store.db.execute(
            "SELECT record_uid FROM event WHERE kind='message.user'"
        ).fetchone()[0]
        assert json.loads(store.read_raw(record))["row"]["content"] == "original"
        with sqlite3.connect(path) as db:
            db.execute("UPDATE messages SET content='changed'")
            db.execute("UPDATE session_model_usage SET input_tokens=20,last_seen=200")
        assert record_source(store.home, record)["status"] == "changed"
        service.import_source(ImportRequest("hermes", root))
        assert store.db.execute("SELECT COUNT(*) FROM usage_snapshot").fetchone()[0] == 2
        assert store.db.execute("SELECT COUNT(*) FROM archive_blob").fetchone()[0] == 0


def test_complete_trajectory_includes_ignored_invalid_unknown_and_paginates(tmp_path):
    root = tmp_path / "claude"
    path = root / "projects/p/session.jsonl"
    write_rows(
        path,
        [
            {"type": "user", "sessionId": "s", "message": {"content": "prompt"}},
            {"type": "last-prompt", "text": "ignored record"},
            {"type": "future_native_type", "payload": "still indexed"},
        ],
    )
    with path.open("a") as handle:
        handle.write("broken-json\n")
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("claude_code", root))
        session = store.db.execute("SELECT session_uid FROM session").fetchone()[0]
        page = trajectory_page(store.home, session, limit=2)
        assert page["total"] == 4
        next_page = trajectory_page(
            store.home, session, after=page["next_after"], run_id=page["run_id"], limit=2
        )
        assert next_page["next_after"] is None
        records = page["items"] + next_page["items"]
        assert {r["disposition"] for r in records} >= {"mapped", "ignored", "unparsed"}
        assert [json.loads(store.read_raw(r["record_uid"])) for r in records[:3]]
        store.rebuild()
        with pytest.raises(ValueError, match="publication changed"):
            trajectory_page(store.home, session, run_id=page["run_id"])


def test_full_text_in_fields_analysis_and_original_secrets_remain_local(tmp_path):
    root = tmp_path / "codex"
    rows = codex_rows()
    rows[2]["payload"]["message"] = LONG + "\napi_key=sk-" + "x" * 32
    write_rows(root / "sessions/rollout-s.jsonl", rows)
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        bundle = read_analysis(store.home, AnalysisScope("UTC"))
        reply = next(e for e in bundle["events"] if e["kind"] == "message.assistant")
        assert reply["text"].startswith(LONG) and reply["text_truncated"] == 0
        assert "sk-" + "x" * 32 not in reply["text"]
        assert (
            "sk-" + "x" * 32
            in record_source(store.home, reply["record_uid"], include_content=True)["content"]
        )
        assert next(e for e in bundle["events"] if e["kind"] == "tool.result")["text"] == LONG


def test_archive_move_and_compressed_replacement_keep_record_identity(tmp_path):
    root = tmp_path / "codex"
    path = root / "sessions/rollout-s.jsonl"
    write_rows(path, codex_rows())
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        request = ImportRequest("codex", root)
        service.import_source(request)
        record = store.db.execute(
            "SELECT record_uid FROM event WHERE kind='message.assistant'"
        ).fetchone()[0]
        original = store.read_raw(record)
        moved = root / "archived_sessions/rollout-s.jsonl"
        moved.parent.mkdir()
        path.rename(moved)
        assert service.import_source(request)["changed"] == 0
        assert store.read_raw(record) == original
        compressed = moved.with_suffix(".jsonl.zst")
        compressed.write_bytes(zstandard.ZstdCompressor().compress(moved.read_bytes()))
        moved.unlink()
        assert service.import_source(request)["changed"] == 0
        assert store.read_raw(record) == original
        assert service.import_source(request)["changed"] == 0
        assert store.db.execute("SELECT COUNT(*) FROM source_file").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0] == 1
        assert record_source(store.home, record)["path"] == str(compressed)
        assert store.verify()["integrity"] == "ok"


def test_trajectory_page_uses_session_indexes_not_full_record_scan(tmp_path, monkeypatch):
    """Large homes made each trajectory page scan every current file_record row."""
    import contextlib
    import re

    import orbit_data.query as query

    root = tmp_path / "claude"
    write_rows(
        root / "projects/p/target.jsonl",
        [
            {"type": "user", "sessionId": "target", "message": {"content": "prompt"}},
            {"type": "last-prompt", "text": "ignored record"},
        ],
    )
    for index in range(3):
        write_rows(
            root / f"projects/p/other-{index}.jsonl",
            [{"type": "user", "sessionId": f"other-{index}", "message": {"content": "x"}}],
        )
    statements = []
    original = query.readonly_connection

    @contextlib.contextmanager
    def traced(path):
        with original(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(query, "readonly_connection", traced)
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("claude_code", root))
        session = store.db.execute(
            "SELECT session_uid FROM session WHERE native_id='target'"
        ).fetchone()[0]
        page = trajectory_page(store.home, session, limit=10)
        assert page["total"] == 2 and len(page["items"]) == 2
        scans = []
        for sql in statements:
            if "selected" not in sql:
                continue
            for row in store.db.execute("EXPLAIN QUERY PLAN " + sql):
                detail = row[3]
                if re.match(r"SCAN (file_record|raw_record|source_file|[rcf])\b", detail):
                    scans.append(detail)
        assert scans == []
