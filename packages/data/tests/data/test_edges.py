import hashlib
import json
import sqlite3

import pytest
import zstandard

from tandem_data.analysis_input import AnalysisLimitExceeded, AnalysisScope, read_analysis
from tandem_data.bridge import import_connector
from tandem_data.contract import canonical
from tandem_data.schema_export import table_schemas
from tandem_data.store import Store, readonly_connection


def stream(store, agent, root, rows, filename="fixture.jsonl", format_name="jsonl"):
    source = store.add_source(agent, root)
    store.capture_stream(
        source,
        filename,
        [(canonical(row) + "\n").encode() for row in rows],
        format_name=format_name,
    )
    return source


def pi_rows():
    return [
        {"type": "session", "id": "s", "cwd": "/missing/example"},
        {
            "type": "message",
            "id": "u",
            "timestamp": "2026-10-02T00:00:00Z",
            "message": {"role": "user", "content": "task"},
        },
        {
            "type": "message",
            "id": "a",
            "parentId": "u",
            "timestamp": "2026-10-02T00:00:01Z",
            "message": {
                "role": "assistant",
                "model": "test",
                "content": [{"type": "text", "text": "中" * 4000}],
                "usage": {"input": 10, "output": 2},
            },
        },
    ]


def test_pretruncation_lengths_redaction_scope_and_empty_selection(tmp_path):
    with Store(tmp_path / "data") as store:
        stream(store, "pi", tmp_path / "source", pi_rows())
        store.rebuild()
        event = store.db.execute("SELECT * FROM event WHERE kind='message.assistant'").fetchone()
        attrs = json.loads(event["attrs"])
        assert attrs["original_chars"] == 4000 and event["text_truncated"] == 1
        assert len(event["text"].encode()) <= 8192
        assert attrs["writing_measurements"]["reply"]["complete"]
        bundle = read_analysis(store.home, AnalysisScope("Asia/Shanghai", model_ids=("test",)))
        assert any(e["kind"] == "message.user" for e in bundle["events"])
        assert len(bundle["model_calls"]) == 1
        assert not read_analysis(store.home, AnalysisScope("Asia/Shanghai", project_ids=()))[
            "events"
        ]
        source = store.add_source("pi", tmp_path / "source")
        store.capture_stream(source, "new.jsonl", [b'{"type":"session","id":"new"}\n'])
        with pytest.raises(ValueError, match="pending"):
            read_analysis(store.home, AnalysisScope("Asia/Shanghai"))


def test_verified_pi_fork_is_not_new_behavior(tmp_path):
    with Store(tmp_path / "data") as store:
        rows = pi_rows()
        stream(store, "pi", tmp_path / "source", rows, "z-parent.jsonl")
        fork = [{"type": "session", "id": "s2", "parentSession": "z-parent.jsonl"}, *rows[1:]]
        stream(store, "pi", tmp_path / "source", fork, "a-fork.jsonl")
        store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM v_human_message").fetchone()[0] == 1
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM raw_record WHERE disposition='replayed'"
            ).fetchone()[0]
            == 2
        )
        assert store.verify()["unparsed"] == 0


def test_analysis_byte_budget_is_checked_before_event_decoding(tmp_path, monkeypatch):
    from tandem_data import analysis_input

    decoded_events = []
    original = analysis_input.decoded

    def track_decoding(row):
        if "event_uid" in row.keys():
            decoded_events.append(row["event_uid"])
        return original(row)

    monkeypatch.setattr(analysis_input, "decoded", track_decoding)
    with Store(tmp_path / "data") as store:
        stream(store, "pi", tmp_path / "source", pi_rows())
        store.rebuild()
        with pytest.raises(AnalysisLimitExceeded, match="byte budget"):
            read_analysis(store.home, AnalysisScope("UTC"), max_bytes=8192)
        assert decoded_events == []
        empty = read_analysis(
            store.home, AnalysisScope("UTC", project_ids=()), max_events=0, max_bytes=0
        )
        assert empty["events"] == []


def test_real_sqlite_reader_is_readonly_and_preserves_versions(tmp_path):
    root = tmp_path / "agent"
    root.mkdir()
    path = root / "state.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY,started_at REAL,cwd TEXT); CREATE TABLE session_model_usage(session_id TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER, PRIMARY KEY(session_id,model));"
        )
        connection.execute("INSERT INTO sessions VALUES('s',1.234,'/missing/example')")
        connection.execute("INSERT INTO session_model_usage VALUES('s','test',20,5)")
    before = path.read_bytes()
    with Store(tmp_path / "data") as store:
        source = store.add_source("hermes", root)
        store.capture_file(source, path)
        store.rebuild()
        assert path.read_bytes() == before
        with readonly_connection(path) as connection, pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM sessions")
        assert store.db.execute("SELECT COUNT(*) FROM usage_snapshot").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] == 0
        assert store.verify()["unparsed"] == 0


def test_opencode_v1_step_usage_and_native_tool_bounds(tmp_path):
    def row(table, key, data):
        return {"table": table, "key": {"id": key}, "row": data}

    rows = [
        row("session", "s", {"id": "s", "directory": "/missing/example", "time_created": 1000}),
        row(
            "message",
            "u",
            {
                "id": "u",
                "session_id": "s",
                "time_created": 1000,
                "data": canonical({"role": "user"}),
            },
        ),
        row(
            "message",
            "a",
            {
                "id": "a",
                "session_id": "s",
                "time_created": 1100,
                "data": canonical(
                    {"role": "assistant", "parentID": "u", "providerID": "p", "modelID": "test"}
                ),
            },
        ),
        row(
            "part",
            "p1",
            {
                "id": "p1",
                "session_id": "s",
                "message_id": "u",
                "data": canonical({"type": "text", "text": "task"}),
            },
        ),
        row(
            "part",
            "p2",
            {
                "id": "p2",
                "session_id": "s",
                "message_id": "a",
                "data": canonical(
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call",
                        "state": {
                            "status": "completed",
                            "input": {"command": "git status"},
                            "output": "ok",
                            "time": {"start": 1200, "end": 1500},
                        },
                    }
                ),
            },
        ),
        row(
            "part",
            "p3",
            {
                "id": "p3",
                "session_id": "s",
                "message_id": "a",
                "data": canonical(
                    {
                        "type": "step-finish",
                        "tokens": {
                            "input": 10,
                            "output": 4,
                            "reasoning": 2,
                            "cache": {"read": 5, "write": 0},
                        },
                        "cost": 0.01,
                    }
                ),
            },
        ),
    ]
    with Store(tmp_path / "data") as store:
        stream(store, "opencode", tmp_path / "source", rows, "opencode.db", "sqlite_rows")
        store.rebuild()
        assert store.db.execute("SELECT output_tokens FROM model_call").fetchone()[0] == 6
        assert store.db.execute("SELECT duration_ms,duration_source FROM tool_call").fetchone()[
            :
        ] == (300, "native_bounds")
        assert store.verify()["unparsed"] == 0


def test_truncated_zstd_preserves_l0_and_previous_projection(tmp_path):
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        full = zstandard.ZstdCompressor().compress(b'{"type":"session","id":"s","version":4}\n')
        store.capture_stream(source, "session.jsonl.zstd", [full], format_name="jsonl_zstd")
        store.rebuild()
        old = store.db.execute("SELECT event_uid FROM event").fetchone()[0]
        broken = full[:-3]
        with pytest.raises(ValueError, match="Incomplete"):
            store.capture_stream(source, "session.jsonl.zstd", [broken], format_name="jsonl_zstd")
        assert store.db.execute("SELECT COUNT(*) FROM archive_blob").fetchone()[0] == 2
        assert store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0] == 1
        assert store.db.execute("SELECT event_uid FROM event").fetchone()[0] == old
        assert store.db.execute("SELECT status FROM source_file").fetchone()[0] == "error"
        store.capture_stream(source, "session.jsonl.zstd", [full], format_name="jsonl_zstd")
        issue = store.db.execute(
            "SELECT detail FROM ingest_issue WHERE code='invalid_source_archive'"
        ).fetchone()
        assert json.loads(issue[0])["status"] == "resolved"


def test_typescript_connector_archive_bridge_and_record_crosswalk(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "raw").mkdir()
    source_root = tmp_path / "source"
    raw = (
        canonical({"type": "session_meta", "payload": {"id": "s", "session_id": "s"}}) + "\n"
    ).encode()
    sha = hashlib.sha256(raw).hexdigest()
    chunk = staging / "raw" / (sha + ".zst")
    chunk.write_bytes(zstandard.ZstdCompressor().compress(raw))
    with sqlite3.connect(staging / "tandem.db") as connection:
        connection.executescript(
            "CREATE TABLE source(source_id TEXT,agent TEXT,root_path TEXT,label TEXT); CREATE TABLE source_file(file_id TEXT,source_id TEXT,path TEXT,role TEXT,format TEXT,status TEXT); CREATE TABLE archive_chunk(file_id TEXT,generation INTEGER,offset INTEGER,byte_len INTEGER,sha256 TEXT,path TEXT); CREATE TABLE raw_record(record_uid TEXT,file_id TEXT,generation INTEGER,line_no INTEGER,sha256 TEXT);"
        )
        connection.execute(
            "INSERT INTO source VALUES('source','codex',?,NULL)", (str(source_root),)
        )
        connection.execute(
            "INSERT INTO source_file VALUES('file','source',?,'transcript','jsonl','active')",
            (str(source_root / "rollout.jsonl"),),
        )
        connection.execute(
            "INSERT INTO archive_chunk VALUES('file',0,0,?,?,?)", (len(raw), sha, str(chunk))
        )
        connection.execute("INSERT INTO raw_record VALUES('external-record','file',0,1,?)", (sha,))
    before = (staging / "tandem.db").read_bytes()
    with Store(tmp_path / "data") as store:
        assert import_connector(store, staging)["imported_revisions"] == 1
        store.rebuild()
        assert import_connector(store, staging)["imported_revisions"] == 0
        record_uid = store.db.execute("SELECT record_uid FROM connector_record_link").fetchone()[0]
        assert store.read_raw(record_uid) == raw
        assert (staging / "tandem.db").read_bytes() == before
        assert store.verify()["unparsed"] == 0


def test_generated_table_schema_matches_actual_ddl():
    from importlib.resources import files

    saved = json.loads(files("tandem_data").joinpath("schemas/tables-v1.schema.json").read_text())
    assert saved == table_schemas()
    assert "is_wrapper" in saved["$defs"]["tool_call"]["properties"]


def test_redaction_before_projection_leaves_raw_bytes_intact(tmp_path):
    with Store(tmp_path / "data") as store:
        token = "sk-" + "a" * 24
        rows = [
            {"type": "session", "id": "s"},
            {"type": "message", "id": "u", "message": {"role": "user", "content": token}},
        ]
        stream(store, "pi", tmp_path / "source", rows)
        store.rebuild()
        event = store.db.execute("SELECT * FROM event WHERE kind='message.user'").fetchone()
        assert token not in event["text"] and "redacted" in event["text"]
        assert token.encode() in store.read_raw(event["record_uid"])


def test_historical_scope_does_not_leak_future_tool_status(tmp_path):
    rows = [
        {"type": "session", "id": "s"},
        {
            "type": "message",
            "id": "u",
            "timestamp": "2026-10-02T00:00:00Z",
            "message": {"role": "user", "content": "task"},
        },
        {
            "type": "message",
            "id": "a",
            "timestamp": "2026-10-02T00:00:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": "c",
                        "name": "bash",
                        "arguments": {"command": "test"},
                    }
                ],
            },
        },
        {
            "type": "message",
            "id": "r",
            "timestamp": "2026-10-02T00:00:03Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "c",
                "content": "failed later",
                "isError": True,
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        stream(store, "pi", tmp_path / "source", rows)
        store.rebuild()
        from tandem_data.contract import time_fields

        cutoff = time_fields("2026-10-02T00:00:02Z", "timestamp")[0]
        data = read_analysis(store.home, AnalysisScope("Asia/Shanghai", until_ts=cutoff))
        assert data["tool_calls"][0]["status"] == "unknown"
        assert data["tool_calls"][0]["result_event_uid"] is None
        assert not any(e["kind"] == "tool.result" for e in data["events"])


def test_historical_scope_does_not_use_unknown_time_tool_outcome(tmp_path):
    rows = [
        {"type": "session", "id": "s"},
        {
            "type": "message",
            "id": "u",
            "timestamp": "2026-10-02T00:00:00Z",
            "message": {"role": "user", "content": "task"},
        },
        {
            "type": "message",
            "id": "a",
            "timestamp": "2026-10-02T00:00:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": "c",
                        "name": "bash",
                        "arguments": {"command": "test"},
                    }
                ],
            },
        },
        {
            "type": "message",
            "id": "r",
            "message": {
                "role": "toolResult",
                "toolCallId": "c",
                "content": "failed later",
                "isError": True,
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        stream(store, "pi", tmp_path / "source", rows)
        store.rebuild()
        from tandem_data.contract import time_fields

        cutoff = time_fields("2026-10-02T00:00:02Z", "timestamp")[0]
        data = read_analysis(store.home, AnalysisScope("Asia/Shanghai", until_ts=cutoff))
        assert data["tool_calls"][0]["status"] == "unknown"
        assert data["tool_calls"][0]["result_event_uid"] is None
        assert not any(e["kind"] == "tool.result" for e in data["events"])


def test_native_prepare_failure_is_record_local(tmp_path):
    rows = [
        {
            "table": "session_message",
            "key": {"id": "bad"},
            "row": {"id": "bad", "type": "assistant", "data": "{}"},
        },
        {
            "table": "session_message",
            "key": {"id": "good"},
            "row": {
                "id": "good",
                "session_id": "s",
                "type": "user",
                "data": canonical({"text": "valid", "time": {"created": 1000}}),
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        stream(store, "opencode", tmp_path / "source", rows, "opencode.db", "sqlite_rows")
        store.rebuild()
        assert (
            store.db.execute("SELECT COUNT(*) FROM event WHERE kind='message.user'").fetchone()[0]
            == 1
        )
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM ingest_issue WHERE code='native_preparation_error'"
            ).fetchone()[0]
            == 1
        )
        assert store.verify()["unparsed"] == 1


def test_codex_root_trace_id_does_not_merge_threads_or_skip_guardian(tmp_path):
    own = [
        {"type": "session_meta", "ordinal": 0, "payload": {"id": "parent", "session_id": "parent"}},
        {"type": "turn_context", "ordinal": 1, "payload": {"turn_id": "t", "model": "test"}},
        {
            "type": "event_msg",
            "ordinal": 2,
            "payload": {
                "type": "item_completed",
                "turn_id": "t",
                "item": {
                    "type": "UserMessage",
                    "id": "u",
                    "content": [{"type": "text", "text": "parent task"}],
                },
            },
        },
        {
            "type": "token_usage_record",
            "ordinal": 3,
            "payload": {
                "response_id": "parent-response",
                "turn_id": "t",
                "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 2},
            },
        },
    ]
    child = [
        {
            "type": "session_meta",
            "ordinal": 0,
            "payload": {
                "id": "child",
                "session_id": "parent",
                "parent_thread_id": "parent",
                "source": {
                    "subagent": {"thread_spawn": {"parent_thread_id": "parent", "depth": 1}}
                },
                "subagent_history_start_ordinal": 4,
            },
        },
        *[{**r, "ordinal": i + 1} for i, r in enumerate(own[:3])],
        {
            "type": "token_usage_record",
            "ordinal": 4,
            "payload": {
                "response_id": "child-response",
                "usage": {"input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 1},
            },
        },
    ]
    guardian = [
        {
            "type": "session_meta",
            "ordinal": 0,
            "payload": {
                "id": "guardian",
                "session_id": "parent",
                "source": {"subagent": {"other": "guardian"}},
                "subagent_history_start_ordinal": 2,
            },
        },
        {
            "type": "token_usage_record",
            "ordinal": 1,
            "payload": {
                "response_id": "guardian-response",
                "usage": {"input_tokens": 3, "cached_input_tokens": 0, "output_tokens": 1},
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        stream(store, "codex", tmp_path / "source", child, "a-child.jsonl")
        stream(store, "codex", tmp_path / "source", own, "z-parent.jsonl")
        stream(store, "codex", tmp_path / "source", guardian, "b-guardian.jsonl")
        store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 3
        assert store.db.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] == 3
        assert store.db.execute("SELECT COUNT(*) FROM v_analysis_model_call").fetchone()[0] == 2
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM raw_record WHERE disposition='replayed'"
            ).fetchone()[0]
            == 3
        )
        assert store.verify()["unparsed"] == 0


def test_codex_assistant_mirrors_and_same_text_distinct_human_inputs(tmp_path):
    rows = [
        {"type": "session_meta", "payload": {"id": "s", "session_id": "s"}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t"}},
    ]
    for i in range(2):
        rows.extend(
            [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "id": f"raw-{i}",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "same task"}],
                        "internal_chat_message_metadata_passthrough": {"turn_id": "t"},
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "turn_id": "t",
                        "item": {
                            "type": "UserMessage",
                            "id": f"human-{i}",
                            "content": [{"type": "text", "text": "same task"}],
                        },
                    },
                },
            ]
        )
    rows.extend(
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "turn_id": "t",
                    "item": {
                        "type": "AgentMessage",
                        "id": "reply",
                        "content": [{"type": "Text", "text": "visible reply"}],
                    },
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": "reply",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "visible reply"}],
                    "internal_chat_message_metadata_passthrough": {"turn_id": "t"},
                },
            },
        ]
    )
    with Store(tmp_path / "data") as store:
        stream(store, "codex", tmp_path / "source", rows)
        store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM v_human_message").fetchone()[0] == 2
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM event WHERE kind='message.assistant'"
            ).fetchone()[0]
            == 1
        )
        assert (
            store.db.execute("SELECT COUNT(*) FROM event WHERE kind='context.inject'").fetchone()[0]
            == 0
        )


def test_legacy_codex_and_opencode_v2_assistant_remain_visible(tmp_path):
    with Store(tmp_path / "data") as store:
        stream(
            store,
            "codex",
            tmp_path / "codex",
            [
                {"type": "session_meta", "payload": {"id": "c", "session_id": "c"}},
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "id": "a",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "legacy reply"}],
                    },
                },
            ],
        )
        row = {
            "table": "session_message",
            "key": {"id": "a2"},
            "row": {
                "id": "a2",
                "session_id": "s2",
                "type": "assistant",
                "seq": 1,
                "data": canonical(
                    {
                        "content": [{"type": "text", "text": "v2 reply"}],
                        "model": {"id": "test", "providerID": "p"},
                        "time": {"created": 1234},
                    }
                ),
            },
        }
        stream(store, "opencode", tmp_path / "opencode", [row], "opencode.db", "sqlite_rows")
        store.rebuild()
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM event WHERE kind='message.assistant'"
            ).fetchone()[0]
            == 2
        )
