"""Source-shaped regression corpus: no real user content or credentials."""

import json
import sqlite3
import threading
from pathlib import Path

import pytest
import zstandard

from tandem_data import SCHEMA_VERSION
from tandem_data.contract import canonical
from tandem_data.service import ImportRequest, ImportService, event_page
from tandem_data.store import Store, readonly_connection

T = 1790900000000
ISO = "2026-10-02T00:00:00Z"


def capture(store, tmp_path, agent, rows, path="sessions/demo.jsonl", fmt="jsonl"):
    source = store.add_source(agent, tmp_path / agent)
    store.capture_stream(
        source, path, [(canonical(row) + "\n").encode() for row in rows], format_name=fmt
    )
    return source


def rows(store, table):
    return [dict(r) for r in store.db.execute(f"SELECT * FROM {table}")]


def sqlrow(table, row):
    return {"table": table, "key": {"id": row.get("id", row.get("session_id"))}, "row": row}


def assert_sound(store):
    assert store.verify()["unparsed"] == 0
    assert not store.db.execute(
        "SELECT * FROM v_raw_record_ledger WHERE disposition IN ('mapped','folded','duplicate','replayed') AND event_count=0"
    ).fetchall()
    first = [(r["event_uid"], r["seq"], r["text"]) for r in rows(store, "event")]
    store.rebuild()
    assert first == [(r["event_uid"], r["seq"], r["text"]) for r in rows(store, "event")]


@pytest.mark.parametrize("unchanged", [False, True])
def test_successful_capture_resolves_only_its_own_path(tmp_path, unchanged):
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", tmp_path / "source")
        raw = (canonical({"type": "session", "id": "s"}) + "\n").encode()
        if unchanged:
            store.capture_stream(source, "healthy.jsonl", [raw])
        for path in ("healthy.jsonl", "broken.jsonl"):
            store.issue(source, "capture_failed", stage="l1", detail={"path": path})
        store.capture_stream(source, "healthy.jsonl", [raw])
        issues = {
            detail["path"]: detail.get("status")
            for row in store.db.execute(
                "SELECT detail FROM ingest_issue WHERE code='capture_failed'"
            )
            if (detail := json.loads(row[0]))
        }
        assert issues == {"healthy.jsonl": "resolved", "broken.jsonl": None}
        store.capture_stream(source, "broken.jsonl", [raw])
        assert all(
            json.loads(row[0])["status"] == "resolved"
            for row in store.db.execute(
                "SELECT detail FROM ingest_issue WHERE code='capture_failed'"
            )
        )


def test_capture_stat_cache_resolves_recovered_path(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    path = source_root / "session.jsonl"
    path.write_text(canonical({"type": "session", "id": "s"}) + "\n")
    with Store(tmp_path / "data") as store:
        source = store.add_source("pi", source_root)
        store.capture_file(source, path)
        store.issue(source, "capture_failed", stage="l1", detail={"path": path.name})
        result = store.capture_file(source, path)
        assert result["changed"] is False
        detail = store.db.execute("SELECT detail FROM ingest_issue").fetchone()[0]
        assert json.loads(detail)["status"] == "resolved"


@pytest.mark.parametrize("created_at", [None, T - 1000])
def test_dsh_session_preserves_reported_header_time(tmp_path, created_at):
    header = {"type": "session", "id": "s", "version": 4, "time": T}
    if created_at is not None:
        header["createdAt"] = created_at
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "dsh", [header])
        store.rebuild()
        event = store.db.execute("SELECT ts,attrs FROM event WHERE kind='session.meta'").fetchone()
        assert event["ts"] == (T if created_at is None else created_at)
        reported = json.loads(event["attrs"])["time"]["reported"]
        assert reported["time"] == T
        if created_at is not None:
            assert reported["createdAt"] == created_at


def test_claude_denial_interruption_split_usage_and_sidechain(tmp_path):
    common = {"sessionId": "s", "timestamp": ISO, "cwd": "/fixture", "promptId": "p"}
    records = [
        {**common, "type": "user", "uuid": "u", "message": {"content": "Do a check"}},
        {
            **common,
            "type": "assistant",
            "uuid": "a",
            "message": {
                "id": "r",
                "model": "test",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "c",
                        "name": "Bash",
                        "input": {"command": "git status"},
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        },
        {
            **common,
            "type": "assistant",
            "uuid": "a2",
            "message": {
                "id": "r",
                "content": [{"type": "text", "text": "Checking"}],
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        },
        {
            **common,
            "type": "user",
            "uuid": "t",
            "toolDenialKind": "user-rejected",
            "toolUseResult": {"durationMs": 9},
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "c",
                        "content": "Denied",
                        "is_error": True,
                    }
                ]
            },
        },
        {
            **common,
            "type": "user",
            "uuid": "i",
            "message": {"content": "[Request interrupted by user]"},
        },
        {
            **common,
            "type": "user",
            "uuid": "inject",
            "message": {"content": "<command-name>/help</command-name>"},
        },
        {**common, "type": "future-event", "uuid": "f", "new_field": {"number": 12}},
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "claude_code", records)
        store.rebuild()
        assert len(rows(store, "model_call")) == 1
        call = rows(store, "tool_call")[0]
        assert (call["status"], call["duration_ms"]) == ("declined", 9)
        assert len(rows(store, "v_human_message")) == 1
        assert rows(store, "turn")[0]["status"] == "interrupted"
        unknown = store.db.execute("SELECT ext FROM event WHERE kind='unknown'").fetchone()[0]
        assert json.loads(unknown)["native"]["new_field"] == {"number": 12}
        assert_sound(store)


def test_claude_result_without_error_flag_is_completed(tmp_path):
    # Synthetic: Claude Code omits is_error on success; only explicit errors are failures.
    common = {"sessionId": "s", "timestamp": ISO, "cwd": "/fixture", "promptId": "p"}
    records = [{**common, "type": "user", "uuid": "u", "message": {"content": "Edit files"}}]
    for i in range(4):
        records.append(
            {
                **common,
                "type": "assistant",
                "uuid": f"a{i}",
                "message": {
                    "id": f"r{i}",
                    "model": "test",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "content": [{"type": "tool_use", "id": f"c{i}", "name": "Edit", "input": {}}],
                },
            }
        )
        block = {"type": "tool_result", "tool_use_id": f"c{i}", "content": "ok"}
        if i == 3:
            block["is_error"] = True
        records.append({**common, "type": "user", "uuid": f"t{i}", "message": {"content": [block]}})
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "claude_code", records)
        store.rebuild()
        statuses = sorted(r["status"] for r in rows(store, "tool_call"))
        assert statuses == ["completed"] * 3 + ["failed"]
        assert {r["status_scope"] for r in rows(store, "tool_call")} == {"tool_protocol"}


@pytest.mark.parametrize("version", [0, 1, 2, 3, 4])
def test_dsh_generations_stream_and_tool_result(version, tmp_path):
    message = {
        "role": "tool",
        "toolCallId": "c",
        "isError": False,
        "content": [{"type": "text", "text": "ok"}],
    }
    if version < 4:
        message = {
            "role": "tool",
            "content": [
                {
                    "type": "tool-result",
                    "toolCallId": "c",
                    "isError": False,
                    "content": [{"type": "text", "text": "ok"}],
                }
            ],
        }
    records = [
        {"type": "session", "version": version, "id": "s", "createdAt": T, "cwd": "/fixture"},
        {"type": "turn/start", "seq": 0, "time": T, "data": {"turn": 1}},
        {
            "type": "request/header",
            "seq": 1,
            "time": T,
            "data": {"header": {"config": {"provider": "deepseek", "model": "fixture"}}},
        },
        {
            "type": "user/message",
            "seq": 2,
            "time": T,
            "data": {
                "role": "user",
                "source": {"kind": "user"},
                "content": [{"type": "text", "text": "check"}],
            },
        },
    ]
    if version < 2:
        records += [
            {
                "type": "text-chunks",
                "seq0": 3,
                "time0": T + 1,
                "data": {"turn": 1, "step": 1, "index": 0, "texts": ["a", "b", "c"], "dt": [1, 1]},
            }
        ]
    records += [
        {
            "type": "assistant/message",
            "seq": 6,
            "time": T + 5,
            "data": {
                "turn": 1,
                "step": 1,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "abc"},
                        {"type": "tool-call", "id": "c", "name": "bash", "arguments": "{}"},
                    ],
                },
                "usage": {
                    "inputTokens": 10,
                    "outputTokens": 3,
                    "cacheReadTokens": 2,
                    "cacheWriteTokens": 0,
                },
            },
        },
        {
            "type": "tool/call",
            "seq": 7,
            "time": T + 6,
            "data": {
                "turn": 1,
                "step": 1,
                "callId": "c",
                "name": "bash",
                "arguments": '{"command":"pwd"}',
            },
        },
        {
            "type": "tool/result",
            "seq": 8,
            "time": T + 10,
            "data": {"turn": 1, "step": 1, "message": message},
        },
        {
            "type": "turn/end",
            "seq": 9,
            "time": T + 11,
            "data": {"turn": 1, "reason": {"kind": "completed"}},
        },
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "dsh", records)
        store.rebuild()
        assert len(rows(store, "tool_call")) == 1
        assert rows(store, "tool_call")[0]["status"] == "completed"
        assert rows(store, "tool_call")[0]["duration_quality"] == "estimated"
        assert len(rows(store, "model_call")) == 1
        assert len(rows(store, "v_human_message")) == 1
        assert_sound(store)


def test_dsh_incomplete_stream_has_provenance_and_no_fabricated_success(tmp_path):
    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "dsh",
            [
                {"type": "session", "version": 0, "id": "s", "createdAt": T},
                {"type": "turn/start", "seq": 0, "time": T, "data": {"turn": 1}},
                {
                    "type": "text-chunks",
                    "seq0": 1,
                    "time0": T + 1,
                    "data": {
                        "turn": 1,
                        "step": 1,
                        "index": 0,
                        "texts": ["partial", " reply"],
                        "dt": [1],
                    },
                },
            ],
        )
        store.rebuild()
        assert (
            store.db.execute("SELECT text FROM event WHERE kind='message.assistant'").fetchone()[0]
            == "partial reply"
        )
        assert rows(store, "turn")[0]["status"] != "completed"
        assert_sound(store)


def test_pi_fork_and_unrelated_id_collision(tmp_path):
    parent = [
        {"type": "session", "id": "p", "version": 3, "timestamp": ISO, "cwd": "/fixture"},
        {
            "type": "message",
            "id": "same",
            "timestamp": ISO,
            "message": {"role": "user", "content": "parent prompt"},
        },
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "pi", parent, "sessions/a.jsonl")
        capture(
            store,
            tmp_path,
            "pi",
            [
                {
                    "type": "session",
                    "id": "q",
                    "parentSession": "sessions/a.jsonl",
                    "timestamp": ISO,
                },
                parent[1],
                {
                    "type": "message",
                    "id": "own",
                    "timestamp": ISO,
                    "message": {"role": "user", "content": "child prompt"},
                },
            ],
            "sessions/b.jsonl",
        )
        capture(
            store,
            tmp_path,
            "pi",
            [
                {"type": "session", "id": "z", "timestamp": ISO},
                {**parent[1], "message": {"role": "user", "content": "independent prompt"}},
            ],
            "sessions/c.jsonl",
        )
        store.rebuild()
        assert len(rows(store, "v_human_message")) == 3
        assert sum(r["disposition"] == "replayed" for r in rows(store, "raw_record")) == 1
        child = next(s for s in rows(store, "session") if s["native_id"] == "q")
        assert child["forked_from"] is not None
        assert_sound(store)


def test_opencode_v2_native_sequence_tools_and_usage(tmp_path):
    records = [
        sqlrow("session", {"id": "s", "directory": "/fixture", "title": "fixture"}),
        sqlrow(
            "session_message",
            {
                "id": "z-user",
                "session_id": "s",
                "seq": 1,
                "type": "user",
                "data": canonical({"text": "check", "time": {"created": T}}),
            },
        ),
        sqlrow(
            "session_message",
            {
                "id": "a-assistant",
                "session_id": "s",
                "seq": 2,
                "type": "assistant",
                "data": canonical(
                    {
                        "model": {"id": "model", "providerID": "provider"},
                        "time": {"created": T + 1},
                        "tokens": {
                            "input": 8,
                            "output": 4,
                            "reasoning": 2,
                            "cache": {"read": 3, "write": 0},
                        },
                        "cost": 0,
                        "content": [
                            {"type": "text", "id": "text", "text": "Checking"},
                            {
                                "type": "tool",
                                "id": "c",
                                "name": "bash",
                                "time": {"created": T + 2, "ran": T + 3, "completed": T + 9},
                                "state": {
                                    "status": "completed",
                                    "input": {"command": "pwd"},
                                    "content": [{"type": "text", "text": "ok"}],
                                    "structured": {},
                                },
                            },
                        ],
                    }
                ),
            },
        ),
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "opencode", records, "opencode.db", "sqlite_rows")
        store.rebuild()
        assert rows(store, "tool_call")[0]["duration_ms"] == 6
        assert rows(store, "tool_call")[0]["status"] == "completed"
        assert rows(store, "model_call")[0]["output_tokens"] == 6
        assert rows(store, "model_call")[0]["cost_usd"] == 0
        assert store.db.execute("SELECT kind FROM event WHERE kind='message.assistant'").fetchone()
        assert_sound(store)


def test_sqlite_wal_updates_deletions_and_multiple_sessions(tmp_path):
    root = tmp_path / "opencode"
    root.mkdir()
    db = sqlite3.connect(root / "opencode.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        "CREATE TABLE session(id TEXT PRIMARY KEY,directory TEXT,title TEXT); CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,time_created INTEGER,data TEXT); CREATE TABLE part(id TEXT PRIMARY KEY,session_id TEXT,message_id TEXT,data TEXT);"
    )
    db.executemany(
        "INSERT INTO session VALUES(?,?,?)", [("s", "/one", "one"), ("q", "/two", "two")]
    )
    db.execute(
        "INSERT INTO message VALUES(?,?,?,?)",
        (
            "m",
            "s",
            T,
            canonical({"role": "assistant", "modelID": "model", "providerID": "provider"}),
        ),
    )
    part = {
        "type": "tool",
        "callID": "c",
        "tool": "bash",
        "state": {"status": "running", "input": {"command": "pwd"}, "time": {"start": T}},
    }
    db.execute("INSERT INTO part VALUES(?,?,?,?)", ("p", "s", "m", canonical(part)))
    db.commit()
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        request = ImportRequest("opencode", root)
        service.import_source(request)
        assert len(rows(store, "session")) == 2
        assert rows(store, "tool_call")[0]["status"] == "running"
        part["state"].update(status="error", error="failed", time={"start": T, "end": T + 8})
        db.execute("UPDATE part SET data=?", (canonical(part),))
        db.commit()
        service.import_source(request)
        assert len(rows(store, "tool_call")) == 1
        assert rows(store, "tool_call")[0]["status"] == "failed"
        db.execute("DELETE FROM part")
        db.commit()
        service.import_source(request)
        assert not rows(store, "tool_call")
        assert (
            store.db.execute("SELECT COUNT(*) FROM raw_record WHERE version>1").fetchone()[0] >= 1
        )
        assert_sound(store)
    db.close()


def test_hermes_cumulative_snapshots_and_per_session_context(tmp_path):
    records = [
        sqlrow("sessions", {"id": "a", "model": "A", "started_at": 1790900000.25}),
        sqlrow("sessions", {"id": "b", "model": "B", "started_at": 1790900000.75}),
        sqlrow(
            "messages",
            {
                "id": 1,
                "session_id": "a",
                "message_uid": "u",
                "role": "user",
                "content": "check",
                "active": 1,
                "timestamp": 1790900001,
            },
        ),
        sqlrow(
            "messages",
            {
                "id": 2,
                "session_id": "a",
                "message_uid": "a",
                "role": "assistant",
                "content": "ok",
                "active": 1,
                "tool_calls": canonical(
                    [
                        {
                            "id": "c",
                            "function": {"name": "terminal", "arguments": '{"command":"pwd"}'},
                        }
                    ]
                ),
                "timestamp": 1790900002,
            },
        ),
        sqlrow(
            "messages",
            {
                "id": 3,
                "session_id": "a",
                "message_uid": "t",
                "role": "tool",
                "content": "stopped",
                "tool_call_id": "c",
                "active": 1,
                "display_metadata": canonical({"interrupted": True}),
                "timestamp": 1790900003,
            },
        ),
        sqlrow(
            "session_model_usage",
            {
                "session_id": "a",
                "model": "A",
                "task": "main",
                "input_tokens": 10,
                "output_tokens": 4,
                "last_seen": 1790900004,
            },
        ),
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "hermes", records, "state.db", "sqlite_rows")
        store.rebuild()
        assert len(rows(store, "session")) == 2
        assert not rows(store, "model_call")
        assert len(rows(store, "usage_snapshot")) == 1
        assert rows(store, "tool_call")[0]["status"] == "interrupted"
        session = next(s for s in rows(store, "session") if s["native_id"] == "a")
        assert session["started_at"] == 1790900000250
        assert_sound(store)


def test_kimi_wire_loop_message_usage_mirror_and_all_metadata(tmp_path):
    records = [
        {"type": "metadata", "protocol_version": "1.5", "created_at": T},
        {
            "type": "config.update",
            "agentId": "main",
            "modelAlias": "model",
            "thinkingEffort": "high",
            "time": T,
        },
        {
            "type": "turn.prompt",
            "agentId": "main",
            "turnId": 1,
            "origin": "user",
            "input": [{"type": "text", "text": "check"}],
            "time": T,
        },
        {
            "type": "context.append_message",
            "agentId": "main",
            "message": {
                "id": "u",
                "role": "user",
                "origin": {"kind": "user"},
                "content": [{"type": "text", "text": "check"}],
                "toolCalls": [],
            },
            "time": T,
        },
        {
            "type": "context.append_loop_event",
            "agentId": "main",
            "event": {
                "type": "tool.call",
                "stepUuid": "st",
                "toolCallId": "c",
                "name": "Shell",
                "args": {"command": "pwd"},
            },
            "time": T + 1,
        },
        {
            "type": "context.append_loop_event",
            "agentId": "main",
            "event": {
                "type": "tool.result",
                "toolCallId": "c",
                "result": {"output": "ok", "isError": False, "durationMs": 3},
            },
            "time": T + 4,
        },
        {
            "type": "context.append_loop_event",
            "agentId": "main",
            "event": {
                "type": "step.end",
                "uuid": "st",
                "usage": {
                    "inputOther": 5,
                    "output": 2,
                    "inputCacheRead": 1,
                    "inputCacheCreation": 0,
                },
            },
            "time": T + 5,
        },
        {
            "type": "usage.record",
            "agentId": "main",
            "model": "model",
            "usageScope": "turn",
            "usage": {"inputOther": 5, "output": 2, "inputCacheRead": 1, "inputCacheCreation": 0},
            "time": T + 6,
        },
        {"type": "turn.ended", "turnId": 1, "reason": "completed", "time": T + 7},
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "kimi", records, "sessions/wd_fixture/s/agents/main/wire.jsonl")
        store.rebuild()
        assert len(rows(store, "model_call")) == 1
        assert rows(store, "model_call")[0]["input_tokens"] == 5
        assert len(rows(store, "v_human_message")) == 1
        assert rows(store, "tool_call")[0]["status"] == "completed"
        assert rows(store, "tool_call")[0]["duration_ms"] == 3
        assert_sound(store)


def test_import_service_idempotence_cancellation_pagination_and_allowlist(tmp_path):
    root = tmp_path / "pi"
    (root / "sessions").mkdir(parents=True)
    file = root / "sessions/demo.jsonl"
    file.write_text(
        canonical({"type": "session", "id": "s", "timestamp": ISO})
        + "\n"
        + canonical({"type": "message", "id": "m", "message": {"role": "user", "content": "Hello"}})
        + "\n"
    )
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        request = ImportRequest("pi", root)
        assert service.import_source(request)["changed"] == 1
        assert "projection" not in service.import_source(request)
        session = rows(store, "session")[0]["session_uid"]
        page = event_page(store.home, session, limit=1)
        assert len(page) == 1
        assert event_page(store.home, session, after_seq=page[0]["seq"])
        stop = threading.Event()
        stop.set()
        assert service.import_source(request, stop)["cancelled"]
        with pytest.raises(ValueError, match="allowlisted"):
            service.import_source(ImportRequest("pi", root, files=(Path("auth.json"),)))
        assert_sound(store)


def test_unterminated_tail_and_concatenated_zstd_are_retried(tmp_path):
    root = tmp_path / "dsh"
    (root / "sessions/p/s").mkdir(parents=True)
    path = root / "sessions/p/s/session.jsonl.zstd"
    header = (canonical({"type": "session", "id": "s", "version": 4}) + "\n").encode()
    row = (
        canonical({"type": "session/title", "seq": 0, "time": T, "data": {"title": "fixture"}})
        + "\n"
    ).encode()
    compressor = zstandard.ZstdCompressor()
    first = compressor.compress(header)
    second = compressor.compress(row)
    path.write_bytes(first + second[:5])
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        request = ImportRequest("dsh", root)
        assert service.import_source(request)["capture_errors"] == 1
        path.write_bytes(first + second)
        assert service.import_source(request)["changed"] == 1
        assert rows(store, "session")[0]["title"] == "fixture"
        assert_sound(store)


def test_claude_final_usage_replaces_placeholder_and_nullable_details(tmp_path):
    common = {"type": "assistant", "sessionId": "s", "timestamp": ISO, "isSidechain": True}
    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "claude_code",
            [
                {
                    **common,
                    "uuid": "a",
                    "message": {
                        "id": "r",
                        "content": [{"type": "text", "text": "a"}],
                        "stop_reason": None,
                        "usage": {
                            "input_tokens": 2,
                            "output_tokens": 7,
                            "output_tokens_details": None,
                        },
                    },
                },
                {
                    **common,
                    "uuid": "b",
                    "message": {
                        "id": "r",
                        "content": [{"type": "text", "text": "b"}],
                        "stop_reason": "end_turn",
                        "usage": {
                            "input_tokens": 2,
                            "output_tokens": 305,
                            "output_tokens_details": {"thinking_tokens": 199},
                        },
                    },
                },
                {
                    **common,
                    "uuid": "err",
                    "isApiErrorMessage": True,
                    "message": {
                        "id": "synthetic",
                        "content": [{"type": "text", "text": "error"}],
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "output_tokens_details": None,
                        },
                    },
                },
            ],
        )
        store.rebuild()
        assert len(rows(store, "model_call")) == 1
        assert rows(store, "model_call")[0]["output_tokens"] == 305
        assert rows(store, "model_call")[0]["reasoning_tokens"] == 199
        assert not store.db.execute(
            "SELECT * FROM ingest_issue WHERE code='conflicting_request_usage'"
        ).fetchall()
        assert_sound(store)


def test_scoped_rebuild_preserves_other_sources_and_recovers_unpublished_capture(
    tmp_path, monkeypatch
):
    from tandem_data.connectors.pi import PiMapper

    pi_root = tmp_path / "pi"
    dsh_root = tmp_path / "dsh"
    (pi_root / "sessions").mkdir(parents=True)
    (dsh_root / "sessions/p/s").mkdir(parents=True)
    (pi_root / "sessions/a.jsonl").write_text(
        canonical({"type": "session", "id": "p", "timestamp": ISO}) + "\n"
    )
    file = dsh_root / "sessions/p/s/session.jsonl"
    file.write_text(canonical({"type": "session", "id": "d", "version": 4, "createdAt": T}) + "\n")
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("pi", pi_root))
        service.import_source(ImportRequest("dsh", dsh_root))

        def forbid(*_):
            raise AssertionError("Unchanged source should not be re-parsed")

        monkeypatch.setattr(PiMapper, "map", forbid)
        with file.open("a") as handle:
            handle.write(
                canonical({"type": "session/title", "seq": 0, "data": {"title": "changed"}}) + "\n"
            )
        result = service.import_source(ImportRequest("dsh", dsh_root, rebuild=False))
        assert result["changed"] == 1
        recovered = service.import_source(ImportRequest("dsh", dsh_root))
        assert "projection" in recovered and len(rows(store, "session")) == 2
        assert store.verify()["unparsed"] == 0


def test_claude_json_sidecar_exact_archive_and_subagent_lineage(tmp_path):
    root = tmp_path / "claude"
    folder = root / "projects/project/s/subagents"
    folder.mkdir(parents=True)
    (root / "projects/project/s.jsonl").write_text(
        canonical({"type": "user", "sessionId": "s", "uuid": "u", "message": {"content": "hi"}})
        + "\n"
    )
    (folder / "agent-child.jsonl").write_text(
        canonical(
            {"type": "assistant", "sessionId": "s", "uuid": "a", "message": {"content": "reply"}}
        )
        + "\n"
    )
    raw = b'{\n "agentType": "explore", "toolUseId": "c", "spawnDepth": 1\n}'
    (folder / "agent-child.meta.json").write_bytes(raw)
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("claude_code", root))
        assert len(rows(store, "session")) == 2
        record = store.db.execute(
            "SELECT record_uid FROM raw_record WHERE native_type='subagent_metadata'"
        ).fetchone()
        assert store.read_raw(record[0]) == raw
        assert_sound(store)


def test_incomplete_jsonl_tail_is_archived_and_retried(tmp_path):
    root = tmp_path / "pi"
    (root / "sessions").mkdir(parents=True)
    file = root / "sessions/s.jsonl"
    prefix = canonical({"type": "session", "id": "s", "timestamp": ISO}) + "\n"
    message = canonical(
        {"type": "message", "id": "m", "message": {"role": "user", "content": "hello"}}
    )
    file.write_text(prefix + message[:20])
    with Store(tmp_path / "data") as store:
        service = ImportService(store)
        service.import_source(ImportRequest("pi", root))
        assert store.verify()["unparsed"] == 0
        assert not rows(store, "v_human_message")
        file.write_text(prefix + message + "\n")
        service.import_source(ImportRequest("pi", root))
        assert len(rows(store, "v_human_message")) == 1
        assert_sound(store)


def test_verify_detects_broken_l1_provenance(tmp_path):
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "pi", [{"type": "session", "id": "s"}])
        store.rebuild()
        store.db.execute("DELETE FROM record_event")
        with pytest.raises(ValueError, match="evidence"):
            store.verify()


def test_kimi_contiguous_stream_is_one_response_block_with_all_evidence(tmp_path):
    records = [{"type": "metadata", "protocol_version": "1.5", "created_at": T}]
    for index, text in enumerate(["你", "好", "，世界"]):
        records.append(
            {
                "type": "context.append_loop_event",
                "time": T + index,
                "event": {
                    "type": "content.part",
                    "stepUuid": "step",
                    "part": {"type": "text", "text": text},
                },
            }
        )
    records.append(
        {
            "type": "context.append_loop_event",
            "time": T + 4,
            "event": {"type": "step.end", "uuid": "step"},
        }
    )
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "kimi", records, "sessions/w/s/agents/main/wire.jsonl")
        store.rebuild()
        event = store.db.execute("SELECT * FROM event WHERE kind='message.assistant'").fetchall()
        assert len(event) == 1 and event[0]["text"] == "你好，世界"
        assert json.loads(event[0]["attrs"])["partial"] is False
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM record_event WHERE event_uid=?", (event[0]["event_uid"],)
            ).fetchone()[0]
            == 3
        )
        assert_sound(store)


def test_inline_media_and_provider_signatures_are_opaque_but_raw_is_exact(tmp_path):
    data = {
        "type": "message",
        "id": "a",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "image", "data": "synthetic-inline-image", "mimeType": "image/png"},
                {
                    "type": "thinking",
                    "thinking": "reasoning",
                    "thoughtSignature": "synthetic-signature",
                },
                {
                    "type": "document",
                    "source": {"type": "base64", "data": "synthetic-inline-document"},
                },
            ],
        },
    }
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "pi", [{"type": "session", "id": "s"}, data])
        store.rebuild()
        projected = canonical(rows(store, "event"))
        assert "synthetic-inline-image" not in projected
        assert "synthetic-inline-document" not in projected
        assert "synthetic-signature" not in projected
        record = store.db.execute(
            "SELECT record_uid FROM raw_record WHERE native_type='message'"
        ).fetchone()[0]
        assert json.loads(store.read_raw(record)) == data
        assert_sound(store)


def test_malformed_native_text_does_not_abort_neighbouring_records(tmp_path):
    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "pi",
            [
                {"type": "session", "id": "s"},
                {
                    "type": "message",
                    "id": "bad",
                    "message": {"role": "user", "content": [{"type": "text", "text": False}]},
                },
                {"type": "message", "id": "good", "message": {"role": "user", "content": "valid"}},
            ],
        )
        store.rebuild()
        assert store.verify()["unparsed"] == 1
        assert store.db.execute("SELECT text FROM v_human_message").fetchone()[0] == "valid"


def test_invalid_json_sidecar_is_not_mistaken_for_an_incomplete_jsonl_tail(tmp_path):
    root = tmp_path / "claude"
    path = root / "projects/p/s/subagents/agent-c.meta.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad")
    with Store(tmp_path / "data") as store:
        result = ImportService(store).import_source(ImportRequest("claude_code", root))
        assert result["current_unparsed"] == 1
        assert store.verify()["unparsed"] == 1


@pytest.mark.parametrize(
    "key",
    [
        "DATABASE_PASSWORD",
        "AWS_SECRET_ACCESS_KEY",
        "client_secret",
        "clientSecret",
        "service.api-key",
        "GITHUB_TOKEN",
        "refreshToken",
    ],
)
def test_namespaced_credentials_are_redacted_in_objects_and_text(key):
    from tandem_data.privacy import redact, sanitize

    secret = "arbitrary credential with spaces"
    assert sanitize({"config": {key: secret}})["config"][key] == "<redacted:secret>"
    assert secret not in redact(canonical({key: secret}))
    assert secret not in redact(key + '="' + secret + '"')
    usage = {"input_tokens": 20, "cacheReadTokens": 10, "output_tokens": 5}
    assert sanitize(usage) == usage


@pytest.mark.parametrize("version_field", ["mapper_version", "reducer_version"])
def test_analysis_reader_rejects_obsolete_projection_without_new_input(tmp_path, version_field):
    from tandem_data.analysis_input import AnalysisScope, read_analysis

    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "pi",
            [
                {"type": "session", "id": "s"},
                {"type": "message", "id": "u", "message": {"role": "user", "content": "hello"}},
            ],
        )
        store.rebuild()
        assert read_analysis(store.home, AnalysisScope("Asia/Shanghai"))
        store.db.execute(f"UPDATE projection_run SET {version_field}='obsolete'")
        with pytest.raises(ValueError, match="obsolete"):
            read_analysis(store.home, AnalysisScope("Asia/Shanghai"))
        store.rebuild()
        assert read_analysis(store.home, AnalysisScope("Asia/Shanghai"))
        store.db.execute(
            "UPDATE source_file SET watermark=json_remove(watermark,'$.projected_revision')"
        )
        # An unpublished capture leaves the published run readable (pending, not obsolete).
        bundle = read_analysis(store.home, AnalysisScope("Asia/Shanghai"))
        latest = store.db.execute("SELECT MAX(run_id) FROM projection_run").fetchone()[0]
        assert bundle["projection_run_id"] == latest
        from tandem_data.query import current_projection

        with (
            readonly_connection(store.home / "tandem.db") as db,
            pytest.raises(ValueError, match="pending"),
        ):
            current_projection(db)


def test_untimed_tool_result_does_not_enter_historical_analysis(tmp_path):
    from tandem_data.analysis_input import AnalysisScope, read_analysis
    from tandem_data.contract import time_fields

    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "pi",
            [
                {"type": "session", "id": "s", "timestamp": ISO},
                {
                    "type": "message",
                    "id": "u",
                    "timestamp": ISO,
                    "message": {"role": "user", "content": "check"},
                },
                {
                    "type": "message",
                    "id": "a",
                    "timestamp": ISO,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "id": "c",
                                "name": "bash",
                                "arguments": {"command": "pwd"},
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
                        "isError": False,
                        "content": "eventual result",
                    },
                },
                {
                    "type": "message",
                    "id": "late",
                    "timestamp": "2026-10-02T02:00:00Z",
                    "message": {"role": "assistant", "content": "later"},
                },
            ],
        )
        store.rebuild()
        until = time_fields("2026-10-02T01:00:00Z", "cutoff")[0]
        bounded = read_analysis(store.home, AnalysisScope("UTC", until_ts=until))
        assert bounded["tool_calls"][0]["status"] == "unknown"
        assert bounded["tool_calls"][0]["result_event_uid"] is None
        assert all(e["kind"] != "tool.result" for e in bounded["events"])
        assert (
            read_analysis(store.home, AnalysisScope("UTC"))["tool_calls"][0]["status"]
            == "completed"
        )


def test_selected_session_coverage_excludes_unrelated_broken_hermes_source(tmp_path):
    from tandem_data.analysis_input import AnalysisScope, read_analysis

    with Store(tmp_path / "data") as store:
        source = capture(
            store,
            tmp_path,
            "pi",
            [
                {"type": "session", "id": "s", "timestamp": ISO},
                {
                    "type": "message",
                    "id": "u",
                    "timestamp": ISO,
                    "message": {"role": "user", "content": "healthy"},
                },
            ],
        )
        other = store.add_source("hermes", tmp_path / "other")
        store.capture_stream(other, "broken.jsonl", [b"{bad\n"])
        store.issue(other, "capture_failed", stage="l1")
        store.rebuild()
        session = store.db.execute(
            "SELECT session_uid FROM session WHERE source_id=?", (source,)
        ).fetchone()[0]
        scoped = read_analysis(store.home, AnalysisScope("UTC", root_session_uids=(session,)))
        assert scoped["coverage"]["events"]["status"] == "available"
        assert scoped["coverage"]["model_call"]["status"] == "available"
        assert not scoped["diagnostics"]
        assert {s["agent"] for s in scoped["sample_boundary"]["sources"]} == {"pi"}
        assert (
            read_analysis(store.home, AnalysisScope("UTC"))["coverage"]["events"]["status"]
            == "partial"
        )


def test_touching_unchanged_file_refreshes_stat_cache_not_capture_provenance(tmp_path, monkeypatch):
    import os

    root = tmp_path / "pi"
    file = root / "sessions/s.jsonl"
    file.parent.mkdir(parents=True)
    file.write_text(canonical({"type": "session", "id": "s", "timestamp": ISO}) + "\n")
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=1)  # Observes the serial line indexer.
        request = ImportRequest("pi", root)
        service.import_source(request)
        captured_stat = store.db.execute("SELECT source_stat FROM source_revision").fetchone()[0]
        old = file.stat()
        os.utime(file, ns=(old.st_atime_ns, old.st_mtime_ns + 1000000))
        calls = []
        original = store._index_lines

        def counted(*args, **kwargs):
            calls.append(True)
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "_index_lines", counted)
        assert service.import_source(request)["changed"] == 0
        assert len(calls) == 1
        assert service.import_source(request)["changed"] == 0
        assert len(calls) == 1
        assert store.db.execute("SELECT COUNT(*) FROM source_revision").fetchone()[0] == 1
        assert (
            store.db.execute("SELECT source_stat FROM source_revision").fetchone()[0]
            == captured_stat
        )


def test_sqlite_blob_is_only_recoverable_from_l0(tmp_path):
    import base64

    root = tmp_path / "hermes"
    root.mkdir()
    value = b"synthetic binary attachment"
    with sqlite3.connect(root / "state.db") as db:
        db.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY,avatar BLOB)")
        db.execute("INSERT INTO sessions VALUES(?,?)", ("s", value))
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("hermes", root))
        encoded = base64.b64encode(value).decode()
        assert encoded not in canonical(rows(store, "event"))
        record = store.db.execute("SELECT record_uid FROM raw_record").fetchone()[0]
        native = json.loads(store.read_raw(record))
        assert base64.b64decode(native["row"]["avatar"]["$binary"]) == value
        assert_sound(store)


def test_historical_session_title_is_replayed_before_cutoff(tmp_path):
    from tandem_data.analysis_input import AnalysisScope, read_analysis
    from tandem_data.contract import time_fields

    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "pi",
            [
                {"type": "session", "id": "s", "timestamp": ISO, "cwd": "/fixture"},
                {"type": "session_info", "id": "early", "name": "before", "timestamp": ISO},
                {
                    "type": "message",
                    "id": "u",
                    "timestamp": ISO,
                    "message": {"role": "user", "content": "request"},
                },
                {
                    "type": "session_info",
                    "id": "late",
                    "name": "future",
                    "timestamp": "2026-10-02T02:00:00Z",
                },
            ],
        )
        store.rebuild()
        cutoff = time_fields("2026-10-02T01:00:00Z", "cutoff")[0]
        assert read_analysis(store.home, AnalysisScope("UTC"))["sessions"][0]["title"] == "future"
        historical = read_analysis(store.home, AnalysisScope("UTC", until_ts=cutoff))
        assert historical["sessions"][0]["title"] == "before"
        assert historical["sessions"][0]["status"] == "unknown"
        assert all(e["text"] != "future" for e in historical["events"])


@pytest.mark.parametrize("cwd", [None, "/deleted/worktree"])
def test_hermes_recorded_git_root_survives_missing_worktree(tmp_path, cwd):
    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "hermes",
            [sqlrow("sessions", {"id": "s", "cwd": cwd, "git_repo_root": "/recorded/main-repo"})],
            "state.db",
            "sqlite_rows",
        )
        store.rebuild()
        project = rows(store, "project")[0]
        assert project["key_type"] == "git_root" and project["key"] == "/recorded/main-repo"
        assert rows(store, "session")[0]["project_id"] == project["project_id"]
        assert rows(store, "event_context")[0]["project_id"] == project["project_id"]
        assert_sound(store)


def test_project_type_transition_migrates_existing_ids_and_overrides(tmp_path):
    from importlib.resources import files

    from tandem_data.reduce import project_for

    home = tmp_path / "data"
    home.mkdir()
    with sqlite3.connect(home / "tandem.db") as db:
        for migration in ["001.sql", "002.sql", "003.sql"]:
            db.executescript(files("tandem_data").joinpath("migrations/" + migration).read_text())
        db.execute("INSERT INTO project VALUES('old','path','/synthetic/repo','repo',NULL,'[]')")
        db.execute("INSERT INTO project_override VALUES('/synthetic/repo/*','old')")
        db.execute(
            "INSERT INTO source(source_id,agent,root_path,discovered_at) VALUES('source','pi','/source',0)"
        )
        db.execute("INSERT INTO session_identity VALUES('session','source','s','[\"s\"]')")
        db.execute(
            "INSERT INTO session(session_uid,source_id,native_id,kind,root_uid,project_id) VALUES('session','source','s','main','session','old')"
        )
    with Store(home) as store:
        new_id = project_for(store, None, recorded_root="/synthetic/repo")
        assert new_id != "old"
        assert len(rows(store, "project")) == 2
        assert rows(store, "project_override")[0]["project_id"] == "old"
        assert rows(store, "session")[0]["project_id"] == "old"
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()


def test_pi_empty_session_info_clears_title(tmp_path):
    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "pi",
            [
                {"type": "session", "id": "s", "timestamp": ISO},
                {"type": "session_info", "id": "one", "name": "old title", "timestamp": ISO},
                {"type": "session_info", "id": "two", "name": "", "timestamp": ISO},
            ],
        )
        store.rebuild()
        assert rows(store, "session")[0]["title"] == ""
        assert_sound(store)


def test_hermes_routing_identity_stays_in_raw_without_losing_lineage(tmp_path):
    private = "private-routing-sentinel"
    origin = canonical({"_delegate_from": "parent", "user_id": private})
    records = [
        sqlrow("sessions", {"id": "parent"}),
        sqlrow(
            "sessions",
            {
                "id": "child",
                "parent_session_id": "parent",
                "origin_json": origin,
                "user_id": private,
                "session_key": private,
                "chat_id": private,
                "display_name": private,
            },
        ),
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "hermes", records, "state.db", "sqlite_rows")
        store.rebuild()
        assert private not in canonical(rows(store, "event"))
        child = next(row for row in rows(store, "session") if row["native_id"] == "child")
        assert child["kind"] == "subagent" and child["parent_uid"] is not None
        originals = [
            json.loads(store.read_raw(row["record_uid"])) for row in rows(store, "raw_record")
        ]
        assert originals[1]["row"]["origin_json"] == origin
        assert_sound(store)


@pytest.mark.parametrize(
    "lead",
    [
        {"type": "queue-operation", "operation": "enqueue", "sessionId": "s1", "timestamp": ISO},
        {"type": "mode", "mode": "plan", "sessionId": "s1"},
        {"type": "custom-title", "customTitle": "t", "sessionId": "s1"},
        {"type": "ai-title", "aiTitle": "t", "sessionId": "s1"},
    ],
)
def test_claude_metadata_comes_from_later_records_when_first_line_lacks_cwd(tmp_path, lead):
    context = {
        "sessionId": "s1",
        "timestamp": ISO,
        "cwd": "/synthetic/repo",
        "gitBranch": "feature-x",
        "version": "9.9.9",
        "entrypoint": "cli",
    }
    with Store(tmp_path / "data") as store:
        capture(
            store,
            tmp_path,
            "claude_code",
            [
                lead,
                {
                    **context,
                    "type": "user",
                    "uuid": "u",
                    "message": {"role": "user", "content": "hi"},
                },
                {
                    **context,
                    "type": "assistant",
                    "uuid": "a",
                    "message": {"id": "m", "content": [{"type": "text", "text": "ok"}]},
                },
            ],
            path="projects/-synthetic-repo/s1.jsonl",
        )
        store.rebuild()
        (session,) = rows(store, "session")
        assert session["cwd"] == "/synthetic/repo"
        assert session["git_branch"] == "feature-x"
        assert session["harness_version"] == "9.9.9"
        assert session["client"] == "cli"
        assert session["project_id"] is not None
        assert {t["project_id"] for t in rows(store, "turn")} <= {session["project_id"]}
