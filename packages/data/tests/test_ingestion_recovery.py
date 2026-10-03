"""Discovery boundaries and bounded recovery, using synthetic sources only."""

import json
import sqlite3

import pytest

from orbit_data import indexing
from orbit_data.discovery import inputs
from orbit_data.service import ImportRequest, ImportService
from orbit_data.source_reader import SourceUnavailable
from orbit_data.store import Store


def test_codex_discovers_indexed_rollouts_within_enabled_root(tmp_path):
    root = tmp_path / "codex"
    root.mkdir()
    outside = tmp_path / "rollout-outside.jsonl"
    outside.write_text("{}\n")
    paths = [root / "custom/rollout-indexed.jsonl", root / "sessions/rollout-standard.jsonl"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    (root / "rollout-link.jsonl").symlink_to(outside)
    with sqlite3.connect(root / "state_5.sqlite") as db:
        db.execute("CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT)")
        pointers = [
            str(paths[0]),
            "sessions/rollout-standard.jsonl",
            str(outside),
            "../rollout-outside.jsonl",
            "rollout-link.jsonl",
            "auth.json",
        ]
        db.executemany("INSERT INTO threads VALUES(?,?)", enumerate(pointers))
    found = list(inputs("codex", root))
    assert {item.path for item in found if item.role == "transcript"} == set(paths)
    assert len(found) == 3


def test_unavailable_codex_index_keeps_transcripts_and_index_for_failure_accounting(tmp_path):
    root = tmp_path / "codex"
    (root / "sessions").mkdir(parents=True)
    (root / "sessions/rollout-synthetic.jsonl").write_text("{}\n")
    (root / "state_5.sqlite").write_bytes(b"invalid database")
    assert {item.role for item in inputs("codex", root)} == {"transcript", "state_index"}


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("persistent", [False, True])
def test_capture_race_retries_once_and_reports_per_file_outcome(
    tmp_path, monkeypatch, workers, persistent
):
    root = tmp_path / "claude"
    path = root / "projects/p/session.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "synthetic",
                "uuid": "u",
                "message": {"content": "synthetic prompt"},
            }
        )
        + "\n"
    )
    real = indexing.index_file
    attempts = []

    def raced(*args, **kwargs):
        attempts.append(1)
        if persistent or len(attempts) == 1:
            raise SourceUnavailable("changed", "private source text must not reach logs")
        return real(*args, **kwargs)

    monkeypatch.setattr(indexing, "index_file", raced)
    monkeypatch.setattr("orbit_data.parallel.index_file", raced)
    updates = []
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=workers, maintenance="off", progress=updates.append)
        result = service.import_source(ImportRequest("claude_code", root))
        service.close()
        assert len(attempts) == 2
        assert result["capture_errors"] == int(persistent)
        assert len([u for u in updates if u["stage"] == "capture_retry"]) == 1
        outcome = next(u for u in updates if u.get("status") in ("failed", "captured"))
        assert outcome["attempts"] == 2
        assert outcome["path"] == "projects/p/session.jsonl"
        assert "private source text" not in json.dumps(updates)
        issues = store.db.execute(
            "SELECT detail FROM ingest_issue WHERE code='capture_failed'"
        ).fetchall()
        assert len(issues) == int(persistent)
        if persistent:
            assert json.loads(issues[0][0])["attempts"] == 2
        else:
            assert (
                store.db.execute("SELECT COUNT(*) FROM event WHERE kind='message.user'").fetchone()[
                    0
                ]
                == 1
            )


def test_opencode_malformed_tool_preserves_neighboring_answer_and_healthy_tool(tmp_path):
    from orbit_data.contract import canonical

    blocks = [
        {"type": "text", "text": "synthetic answer"},
        {"type": "tool", "name": "broken"},
        {
            "type": "tool",
            "id": "ok",
            "name": "compute",
            "state": {"status": "completed", "content": 0},
            "time": {},
        },
    ]
    rows = [
        {"table": "session", "row": {"id": "s"}},
        {
            "table": "session_message",
            "row": {
                "id": "m",
                "session_id": "s",
                "type": "assistant",
                "data": json.dumps({"content": blocks}),
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("opencode", tmp_path / "opencode")
        store.capture_stream(source, "opencode.db", [(canonical(r) + "\n").encode() for r in rows])
        store.rebuild()
        events = [dict(row) for row in store.db.execute("SELECT kind,text FROM event")]
        assert {"kind": "message.assistant", "text": "synthetic answer"} in events
        assert {"kind": "tool.result", "text": "0"} in events
        assert sum(e["kind"] == "unknown" for e in events) == 1
        assert store.db.execute("SELECT COUNT(*) FROM tool_call").fetchone()[0] == 1
        assert store.verify()["unparsed"] == 0


@pytest.mark.parametrize("value, expected", [(0, "0"), (False, "false"), (3.5, "3.5")])
def test_scalar_tool_output_is_preserved(value, expected):
    from orbit_data.connectors.base import text_content

    assert text_content(value) == expected
    assert text_content(["prefix", {"content": value}]) == "prefix\n" + expected


def test_same_native_ids_and_filenames_across_sources_remain_separate_and_idempotent(tmp_path):
    from orbit_data.contract import canonical

    with Store(tmp_path / "data") as store:
        for root, text in [("account1", "first"), ("account2", "second")]:
            source = store.add_source("claude_code", tmp_path / root)
            row = {
                "type": "user",
                "sessionId": "same",
                "uuid": "same-message",
                "message": {"content": text},
            }
            store.capture_stream(
                source, "projects/p/session.jsonl", [(canonical(row) + "\n").encode()]
            )
        store.rebuild()
        before = [
            tuple(row)
            for row in store.db.execute("SELECT event_uid,text FROM event ORDER BY event_uid")
        ]
        assert store.db.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 2
        assert {row[1] for row in before if row[1]} == {"first", "second"}
        store.rebuild()
        assert before == [
            tuple(row)
            for row in store.db.execute("SELECT event_uid,text FROM event ORDER BY event_uid")
        ]
