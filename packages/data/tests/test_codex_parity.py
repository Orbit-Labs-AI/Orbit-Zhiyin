"""Canonical ingestion must preserve the history semantics of both entry points."""

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tandem_data.bridge import import_connector
from tandem_data.discovery import inputs
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store


def write_rows(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(
                {
                    "type": kind,
                    "payload": payload,
                    "ordinal": n,
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            )
            + "\n"
            for n, (kind, payload) in enumerate(records)
        )
    )


def rollback_rows():
    rows = [("session_meta", {"id": "rollback", "history_mode": "legacy"})]
    for turn in ("keep", "remove"):
        rows += [
            ("event_msg", {"type": "task_started", "turn_id": turn}),
            ("event_msg", {"type": "user_message", "message": turn}),
            (
                "token_usage_record",
                {
                    "response_id": turn,
                    "turn_id": turn,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            ),
            ("event_msg", {"type": "task_complete", "turn_id": turn}),
        ]
    return rows + [("event_msg", {"type": "thread_rolled_back", "num_turns": 1})]


def test_rollback_direct_and_archive_bridge_agree(tmp_path):
    root = tmp_path / "codex"
    write_rows(root / "sessions/rollout-main.jsonl", rollback_rows())
    cli = Path(__file__).resolve().parents[2] / "connectors/dist/cli.js"
    # The ordinary direct path is always exercised; CI builds the staging producer first.
    with Store(tmp_path / "direct") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        assert store.db.execute("SELECT count(*) FROM event WHERE text='remove'").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM model_call").fetchone()[0] == 1
        assert store.verify()["unparsed"] == 0
    if not cli.is_file():
        pytest.fail("Build TypeScript staging producer before bridge parity")
    subprocess.run(
        [
            "node",
            str(cli),
            "ingest",
            "--codex-home",
            str(root),
            "--data-dir",
            str(tmp_path / "staging"),
        ],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(root)
    with Store(tmp_path / "bridged") as store:
        import_connector(store, tmp_path / "staging")
        store.rebuild()
        assert store.db.execute("SELECT count(*) FROM event WHERE text='remove'").fetchone()[0] == 0
        assert store.db.execute("SELECT count(*) FROM model_call").fetchone()[0] == 1
        assert store.verify()["unparsed"] == 0


def test_index_discovery_is_allowlisted_and_current_branch_wins(tmp_path):
    root = tmp_path / "codex"
    write_rows(
        root / "sessions/rollout-root.jsonl",
        [
            ("session_meta", {"id": "s"}),
            ("event_msg", {"type": "user_message", "message": "keep"}),
            ("event_msg", {"type": "user_message", "message": "undone"}),
        ],
    )
    for name in ("active", "z-sibling"):
        write_rows(
            root / f"sessions/rollout-{name}.jsonl",
            [
                (
                    "session_meta",
                    {"id": "s", "history_base": {"thread_id": "root", "end_ordinal_exclusive": 2}},
                ),
                ("event_msg", {"type": "user_message", "message": name}),
            ],
        )
    with sqlite3.connect(root / "state_5.sqlite") as db:
        db.execute("CREATE TABLE threads(id TEXT, rollout_path TEXT, name TEXT, creator_id TEXT)")
        db.execute(
            "INSERT INTO threads VALUES(?,?,?,?)",
            ("s", str(root / "sessions/rollout-active.jsonl"), "Actual title", "private-identity"),
        )
    (root / "session_index.jsonl").write_text(
        json.dumps({"id": "s", "thread_name": "Older title"}) + "\n"
    )
    assert "index_db" in {i.role for i in inputs("codex", root)}
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        texts = {r[0] for r in store.db.execute("SELECT text FROM event WHERE kind='message.user'")}
        assert texts == {"keep", "active"}
        assert store.db.execute("SELECT title FROM session").fetchone()[0] == "Actual title"
        assert all(
            "private-identity" not in str(r.data)
            for f in store.db.execute("SELECT file_id FROM source_file")
            for r in store.iter_file(f[0])
        )


def test_archived_copy_does_not_double_count(tmp_path):
    root = tmp_path / "codex"
    write_rows(root / "sessions/rollout-a.jsonl", rollback_rows()[:5])
    write_rows(root / "archived_sessions/rollout-a.jsonl", rollback_rows()[:5])
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        assert (
            store.db.execute("SELECT count(*) FROM event WHERE kind='message.user'").fetchone()[0]
            == 1
        )
        assert store.db.execute("SELECT count(*) FROM source_revision").fetchone()[0] == 2
