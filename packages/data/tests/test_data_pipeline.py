import pytest
import zstandard

from tandem_data.connectors import MAPPERS
from tandem_data.connectors.base import BaseMapper, Mapping
from tandem_data.contract import canonical
from tandem_data.store import Store


def capture(store, agent, root, rows, filename="fixture.jsonl", format_name="jsonl"):
    source = store.add_source(agent, root / "source")
    raw = "".join(canonical(row) + "\n" for row in rows).encode()
    store.capture_stream(source, filename, [raw], format_name=format_name)
    return source


def claude_rows():
    common = {
        "sessionId": "session-a",
        "cwd": "/missing/demo",
        "version": "synthetic-v1",
        "timestamp": "2026-10-02T02:00:00Z",
    }
    return [
        {
            **common,
            "type": "user",
            "uuid": "u",
            "message": {"role": "user", "content": "test prompt"},
        },
        {
            **common,
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u",
            "new_source_key": "kept",
            "message": {
                "id": "response",
                "model": "test-model",
                "content": [
                    {"type": "thinking", "thinking": "synthetic reasoning", "signature": "opaque"}
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        },
        {
            **common,
            "type": "assistant",
            "uuid": "a2",
            "parentUuid": "a1",
            "message": {
                "id": "response",
                "model": "test-model",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call",
                        "name": "Bash",
                        "input": {"command": "git status"},
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        },
        {
            **common,
            "type": "user",
            "uuid": "result",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call", "content": "done"}],
            },
        },
    ]


def test_claude_split_usage_idempotence_and_provenance(tmp_path):
    with Store(tmp_path / "data") as store:
        capture(store, "claude_code", tmp_path, claude_rows())
        first = store.rebuild()
        calls = store.db.execute("SELECT * FROM model_call").fetchall()
        assert len(calls) == 1 and calls[0]["input_tokens"] == 10
        assert store.db.execute("SELECT COUNT(*) FROM tool_call").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM v_human_message").fetchone()[0] == 1
        assert store.db.execute("SELECT attrs FROM event WHERE kind='reasoning'").fetchone()
        assert (
            "new_source_key"
            in store.db.execute("SELECT ext FROM event WHERE kind='reasoning'").fetchone()[0]
        )
        before = [
            (r["event_uid"], r["seq"]) for r in store.db.execute("SELECT * FROM event ORDER BY seq")
        ]
        capture(store, "claude_code", tmp_path, claude_rows())
        second = store.rebuild()
        assert first == second
        assert before == [
            (r["event_uid"], r["seq"]) for r in store.db.execute("SELECT * FROM event ORDER BY seq")
        ]
        assert store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0] == 1
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
        assert store.verify()["unparsed"] == 0


def test_codex_human_views_call_usage_and_cumulative_separate(tmp_path):
    rows = [
        {
            "type": "session_meta",
            "payload": {
                "id": "s",
                "session_id": "s",
                "cwd": "/missing/demo",
                "model_provider": "openai",
            },
        },
        {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "t", "started_at": 1790900000},
        },
        {"type": "turn_context", "payload": {"turn_id": "t", "model": "test-model"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "injected",
                "role": "user",
                "content": [{"type": "input_text", "text": "injected environment"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "turn_id": "t",
                "item": {
                    "type": "UserMessage",
                    "id": "human",
                    "content": [{"type": "text", "text": "synthetic task"}],
                },
            },
        },
        {
            "type": "token_usage_record",
            "payload": {
                "response_id": "r",
                "turn_id": "t",
                "usage": {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 10},
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 20,
                        "output_tokens": 10,
                    },
                    "last_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 20,
                        "output_tokens": 10,
                    },
                },
            },
        },
        {
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": "t", "completed_at": 1790900001},
        },
    ]
    with Store(tmp_path / "data") as store:
        capture(store, "codex", tmp_path, rows)
        store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM usage_snapshot").fetchone()[0] == 1
        assert store.db.execute("SELECT input_tokens FROM v_session_call_usage").fetchone()[0] == 80
        assert store.db.execute("SELECT COUNT(*) FROM v_human_message").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM turn").fetchone()[0] == 1


def test_sqlite_cumulative_row_versions_and_counter_rollback(tmp_path):
    session = {
        "table": "sessions",
        "key": {"id": "s"},
        "row": {"id": "s", "cwd": "/missing/demo", "started_at": 1790900000},
    }

    def rows(n):
        return [
            session,
            {
                "table": "session_model_usage",
                "key": {"session_id": "s", "model": "test"},
                "row": {
                    "session_id": "s",
                    "model": "test",
                    "billing_provider": "test",
                    "input_tokens": n,
                    "output_tokens": 3,
                },
            },
        ]

    with Store(tmp_path / "data") as store:
        for n in (100, 150, 100):
            capture(store, "hermes", tmp_path, rows(n), "state.db", "sqlite_rows")
            store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM usage_snapshot").fetchone()[0] == 3
        assert store.db.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] == 0
        assert store.db.execute("SELECT input_tokens,ts FROM v_latest_usage_snapshot").fetchone()[
            :
        ] == (100, None)
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM ingest_issue WHERE code='cumulative_counter_decreased'"
            ).fetchone()[0]
            == 1
        )
        assert store.verify()["unparsed"] == 0


def test_multiple_zstd_frames_and_dsh_fold(tmp_path):
    rows = [
        {"type": "session", "id": "s", "version": 0},
        {
            "type": "assistant/chunk",
            "seq": 0,
            "time": 1000,
            "data": {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "text": "part"}},
        },
        {
            "type": "assistant/message",
            "seq": 1,
            "time": 2000,
            "sourceEventSeqs": [0],
            "data": {
                "turn": 1,
                "step": 1,
                "message": {
                    "id": "msg",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "whole"}],
                },
                "usage": {"inputTokens": 10, "outputTokens": 3},
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("dsh", tmp_path / "source")
        compressor = zstandard.ZstdCompressor()
        compressed = b"".join(compressor.compress((canonical(row) + "\n").encode()) for row in rows)
        store.capture_stream(source, "session.jsonl.zstd", [compressed], format_name="jsonl_zstd")
        store.rebuild()
        assert store.db.execute("SELECT COUNT(*) FROM model_call").fetchone()[0] == 1
        assert (
            store.db.execute(
                "SELECT disposition FROM raw_record WHERE native_type='assistant/chunk'"
            ).fetchone()[0]
            == "folded"
        )
        assert store.verify()["unparsed"] == 0


def test_rebuild_is_atomic_when_connector_contract_breaks(tmp_path, monkeypatch):
    with Store(tmp_path / "data") as store:
        capture(store, "claude_code", tmp_path, claude_rows())
        store.rebuild()
        old = [tuple(row) for row in store.db.execute("SELECT * FROM event ORDER BY seq")]

        class BrokenMapper(BaseMapper):
            def map(self, record):
                self.session_uid = store.identity(record.source_id, "bad")
                return Mapping([self.make(record, "invalid.kind", "bad")])

        monkeypatch.setitem(MAPPERS, "claude_code", BrokenMapper)
        from jsonschema import ValidationError

        with pytest.raises(ValidationError):
            store.rebuild(mapper_version="2")
        assert [tuple(row) for row in store.db.execute("SELECT * FROM event ORDER BY seq")] == old
        assert store.verify()["integrity"] == "ok"


def test_tandem_ai_sessions_are_excluded(tmp_path):
    from tandem_data.pipeline import TANDEM_AI_MARKER

    with Store(tmp_path / "data") as store:
        marked = claude_rows()
        for row in marked:
            row["sessionId"] = "session-marker"
            row["uuid"] = "m-" + row["uuid"]
            if "parentUuid" in row:
                row["parentUuid"] = "m-" + row["parentUuid"]
        marked[0]["message"]["content"] = f"{TANDEM_AI_MARKER} task=facet.session job=aj_1]\nhi"
        in_cwd = claude_rows()
        for row in in_cwd:
            row["sessionId"] = "session-cwd"
            row["cwd"] = str(store.home / "agent-cwd")
        capture(store, "claude_code", tmp_path, claude_rows())
        capture(store, "claude_code", tmp_path, marked, filename="marker.jsonl")
        capture(store, "claude_code", tmp_path, in_cwd, filename="cwd.jsonl")
        result = store.rebuild()
        natives = [r[0] for r in store.db.execute("SELECT native_id FROM session")]
        assert natives == ["session-a"] and result["sessions"] == 1
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM raw_record WHERE json_extract(note,'$.reason')='tandem_ai_session'"
            ).fetchone()[0]
            > 0
        )
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
