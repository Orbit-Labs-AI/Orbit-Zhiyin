import json
import sqlite3

from tandem_data.contract import canonical
from tandem_data.query import trajectory_page
from tandem_data.service import ImportRequest, ImportService
from tandem_data.source_reader import record_source
from tandem_data.store import Store


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows))


def test_codex_legacy_response_pairs_control_tools_and_unknown_provenance(tmp_path):
    root = tmp_path / "codex"
    rows = [{"type": "session_meta", "payload": {"id": "s"}}]
    rows += [
        {"type": "event_msg", "payload": {"type": "turn_started", "turn_id": "t"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "ask"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "ask"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "answer"}],
            },
        },
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "answer"}},
        {"type": "event_msg", "payload": {"type": "agent_reasoning", "text": "reasoning"}},
        {
            "type": "event_msg",
            "payload": {"type": "exec_command_begin", "call_id": "c", "command": ["pwd"]},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "exec_command_end",
                "call_id": "c",
                "aggregated_output": "output",
                "exit_code": 0,
            },
        },
        {"type": "event_msg", "payload": {"type": "exec_approval_request", "call_id": "c"}},
        {
            "type": "event_msg",
            "payload": {"type": "exec_approval_response", "call_id": "c", "decision": "approved"},
        },
        {"type": "event_msg", "payload": {"type": "plan_update", "plan": []}},
        {"type": "event_msg", "payload": {"type": "turn_complete", "turn_id": "t"}},
        {"type": "new_protocol_type", "payload": "must remain indexed"},
    ]
    write(root / "sessions/rollout-s.jsonl", rows)
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("codex", root))
        assert result["unknown_events"] == 1 and result["current_unparsed"] == 0
        assert (
            store.db.execute("SELECT COUNT(*) FROM event WHERE kind='message.user'").fetchone()[0]
            == 1
        )
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM event WHERE kind='message.assistant'"
            ).fetchone()[0]
            == 1
        )
        assert store.db.execute("SELECT status FROM tool_call").fetchone()[0] == "completed"
        kinds = {r[0] for r in store.db.execute("SELECT kind FROM event")}
        assert {
            "reasoning",
            "turn.start",
            "turn.end",
            "permission.request",
            "permission.decision",
            "plan.update",
        } <= kinds
        sid = store.db.execute("SELECT session_uid FROM session").fetchone()[0]
        assert trajectory_page(store.home, sid)["total"] == len(rows)
        unknown = store.db.execute(
            "SELECT record_uid,ext FROM event WHERE kind='unknown'"
        ).fetchone()
        assert "must remain indexed" not in unknown["ext"]
        assert json.loads(store.read_raw(unknown["record_uid"])) == rows[-1]


def test_codex_indexes_latest_state_titles_and_reverted_history(tmp_path):
    root = tmp_path / "codex"
    old, new = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    write(
        root / f"sessions/rollout-{old}.jsonl",
        [
            {"ordinal": 0, "type": "session_meta", "payload": {"id": "logical"}},
            {
                "ordinal": 1,
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "kept"},
            },
            {
                "ordinal": 2,
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "reverted"},
            },
        ],
    )
    write(
        root / f"sessions/rollout-{new}.jsonl",
        [
            {
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "id": "logical",
                    "history_base": {"thread_id": old, "end_ordinal_exclusive": 2},
                },
            },
            {
                "ordinal": 2,
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "current"},
            },
        ],
    )
    write(root / "session_index.jsonl", [{"id": "logical", "thread_name": "Title"}])
    with sqlite3.connect(root / "state_5.sqlite") as db:
        db.execute(
            "CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,creator_account_id TEXT)"
        )
        db.execute(
            "INSERT INTO threads VALUES(?,?,?)",
            ("logical", str(root / f"sessions/rollout-{new}.jsonl"), "private-account"),
        )
    with sqlite3.connect(root / "state_4.sqlite") as db:
        db.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("codex", root))
        assert result["files"] == 4
        assert result["current_unparsed"] == 0
        assert [
            r[0] for r in store.db.execute("SELECT text FROM event WHERE kind='message.assistant'")
        ] == ["current"]
        assert store.db.execute("SELECT title FROM session").fetchone()[0] == "Title"
        index = store.db.execute(
            "SELECT record_uid FROM raw_record WHERE native_type='table:threads'"
        ).fetchone()[0]
        assert "private-account" not in store.read_raw(index).decode()
        sid = store.db.execute("SELECT session_uid FROM session").fetchone()[0]
        assert trajectory_page(store.home, sid)["total"] == 7


def test_claude_lifecycle_and_string_messages(tmp_path):
    root = tmp_path / "claude"
    write(
        root / "projects/p/s.jsonl",
        [
            {"sessionId": "s", "type": "user", "message": "prompt"},
            {"type": "started", "agentId": "child", "key": "task", "phase": "working"},
            {"type": "failed", "agentId": "child", "key": "task"},
            {"sessionId": "s", "type": "assistant", "message": "reply"},
        ],
    )
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("claude_code", root))
        assert result["unknown_events"] == result["current_unparsed"] == 0
        assert {r[0] for r in store.db.execute("SELECT kind FROM event")} >= {
            "subagent.spawn",
            "subagent.result",
            "message.user",
            "message.assistant",
        }


def test_legacy_archive_original_access_without_new_copy(tmp_path):
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", tmp_path / "absent")
        raw = b'{"type":"session","id":"s"}\n'
        store.capture_stream(source, "sessions/s.jsonl", [raw])
        record = store.db.execute("SELECT record_uid FROM raw_record").fetchone()[0]
        before = sorted(store.raw_dir.iterdir())
        result = record_source(store.home, record, include_content=True)
        assert result["status"] == "available" and result["content"].encode() == raw
        assert before == sorted(store.raw_dir.iterdir())
