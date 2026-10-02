"""Cross-turn evidence and role preservation at the canonical application boundary."""

from tandem_data.analysis_input import AnalysisScope, read_analysis
from tandem_data.contract import canonical
from tandem_data.store import Store


def test_later_turn_tool_result_cannot_leak_into_historical_snapshot(tmp_path):
    rows = [
        {"type": "session", "id": "s", "timestamp": "2026-01-01T00:00:00Z"},
        {
            "type": "message",
            "id": "u1",
            "timestamp": "2026-01-01T00:00:01Z",
            "message": {"role": "user", "content": "start background work"},
        },
        {
            "type": "message",
            "id": "a1",
            "timestamp": "2026-01-01T00:00:02Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": "c",
                        "name": "bash",
                        "arguments": {"command": "work"},
                    }
                ],
            },
        },
        {
            "type": "message",
            "id": "u2",
            "timestamp": "2026-01-01T00:00:03Z",
            "message": {"role": "user", "content": "another turn"},
        },
        {
            "type": "message",
            "id": "r",
            "timestamp": "2026-01-01T00:00:04Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "c",
                "toolName": "bash",
                "isError": False,
                "content": "done",
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", tmp_path / "source")
        store.capture_stream(
            source, "session.jsonl", [(canonical(r) + "\n").encode() for r in rows]
        )
        store.rebuild()
        call = dict(store.db.execute("SELECT * FROM tool_call").fetchone())
        assert call["status"] == "completed"
        result_turn = store.db.execute(
            "SELECT turn_uid FROM event WHERE event_uid=?", (call["result_event_uid"],)
        ).fetchone()[0]
        assert result_turn != call["turn_uid"]
        bundle = read_analysis(store.home, AnalysisScope("UTC", until_ts=1767225602500))
        bounded = bundle["tool_calls"][0]
        assert bounded["status"] == "unknown"
        assert all(
            bounded[key] is None
            for key in ("result_event_uid", "exit_code", "ended_at", "duration_ms")
        )
        assert call["result_event_uid"] not in {e["event_uid"] for e in bundle["events"]}


def test_kimi_child_output_stays_assistant_while_prompt_is_context(tmp_path):
    rows = [
        {"type": "metadata", "protocol_version": "1.5", "created_at": 1767225600000},
        {
            "type": "context.append_message",
            "agentId": "child",
            "time": 1767225601000,
            "message": {
                "id": "u",
                "role": "user",
                "origin": {"kind": "user"},
                "content": [{"type": "text", "text": "delegated task"}],
            },
        },
        {
            "type": "context.append_message",
            "agentId": "child",
            "time": 1767225602000,
            "message": {
                "id": "a",
                "role": "assistant",
                "content": [{"type": "text", "text": "child answer"}],
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("kimi", tmp_path / "source")
        store.capture_stream(
            source,
            "sessions/w/s/agents/child/wire.jsonl",
            [(canonical(r) + "\n").encode() for r in rows],
        )
        store.rebuild()
        texts = {
            row["text"]: row["kind"]
            for row in store.db.execute("SELECT kind,text FROM event")
            if row["text"]
        }
        assert texts["child answer"] == "message.assistant"
        assert texts["delegated task"] == "context.inject"
        assert store.verify()["unparsed"] == 0
