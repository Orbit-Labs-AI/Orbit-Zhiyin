"""Inherited evidence must resolve even when child archives sort before their parents."""

import json

from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store


def test_paginated_reconstructed_history_is_context_not_another_execution(tmp_path):
    root = tmp_path / "codex"
    parent = [{"type": "session_meta", "payload": {"id": "parent"}}]
    child = [
        {
            "type": "session_meta",
            "payload": {
                "id": "child",
                "history_mode": "paginated",
                "subagent_history_start_ordinal": 4,
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
            },
        },
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "rollout-4"}},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": "rebuilt-call",
                "name": "shell",
                "arguments": "{}",
            },
        },
        {
            "type": "token_usage_record",
            "payload": {
                "turn_id": "rollout-4",
                "response_id": "inherited-usage",
                "usage": {"input_tokens": 10000, "output_tokens": 1000},
            },
        },
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "own-turn"}},
        {
            "type": "token_usage_record",
            "payload": {
                "turn_id": "own-turn",
                "response_id": "own-usage",
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        },
    ]
    for name, rows in [("sessions/parent.jsonl", parent), ("sessions/child.jsonl", child)]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        assert store.verify()["unparsed"] == 0
        assert (
            store.db.execute(
                "SELECT count(*) FROM event WHERE json_extract(attrs,'$.context_type')='inherited_history'"
            ).fetchone()[0]
            == 3
        )
        assert (
            store.db.execute(
                "SELECT count(*) FROM event WHERE json_extract(attrs,'$.inherited_prefix')=1 AND turn_uid IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert store.db.execute("SELECT count(*) FROM tool_call").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM model_call").fetchone()[0] == 1
        assert store.db.execute("SELECT count(*) FROM turn").fetchone()[0] == 1


def test_nested_spawn_parent_precedes_archived_child_and_resolves_mirrors(tmp_path):
    root = tmp_path / "codex"
    rows = [
        {"type": "session_meta", "payload": {"id": "parent", "source": "cli"}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "turn_id": "t",
                "content": [{"type": "input_text", "text": "the original request"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "turn_id": "t",
                "item": {
                    "type": "UserMessage",
                    "id": "user-1",
                    "content": [{"type": "input_text", "text": "the original request"}],
                },
            },
        },
    ]
    for ordinal, row in enumerate(rows):
        row.update(ordinal=ordinal, timestamp="2026-01-01T00:00:00Z")
    child = [
        {
            "type": "session_meta",
            "ordinal": 1,
            "payload": {
                "id": "child",
                "subagent_history_start_ordinal": 4,
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
            },
        },
        *rows[1:],
        {
            "type": "response_item",
            "ordinal": 4,
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "child reply"}],
            },
        },
    ]
    for name, data in [
        ("sessions/z-parent.jsonl", rows),
        ("archived_sessions/a-child.jsonl", child),
    ]:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("".join(json.dumps(row) + "\n" for row in data))
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("codex", root))
        assert result["current_unparsed"] == 0
        assert store.verify()["unparsed"] == 0
        assert (
            store.db.execute("SELECT count(*) FROM event WHERE kind='message.user'").fetchone()[0]
            == 1
        )
        assert store.db.execute("SELECT count(*) FROM session").fetchone()[0] == 2
        assert (
            store.db.execute(
                "SELECT count(*) FROM raw_record WHERE disposition='replayed'"
            ).fetchone()[0]
            == 3
        )
