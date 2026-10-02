"""Synthetic connector regressions: subagent linkage, origins, record destinations."""

import json

from tandem_data.contract import canonical
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store

ISO = "2026-10-02T00:00:0{}Z"


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows))


def stream(store, agent, root, rows, filename):
    source = store.add_source(agent, root)
    store.capture_stream(
        source, filename, [(canonical(row) + "\n").encode() for row in rows], format_name="jsonl"
    )
    return source


def one(store, sql, *args):
    return store.db.execute(sql, args).fetchone()


def claude_context(i=0):
    return {"sessionId": "s1", "timestamp": ISO.format(i), "cwd": "/synthetic/repo"}


def test_claude_agent_call_links_to_child_session_both_ways(tmp_path):
    root = tmp_path / "claude"
    base = root / "projects/-synthetic-repo"
    write_jsonl(
        base / "s1.jsonl",
        [
            {
                **claude_context(0),
                "type": "user",
                "uuid": "u1",
                "message": {"role": "user", "content": "delegate"},
            },
            {
                **claude_context(1),
                "type": "assistant",
                "uuid": "a1",
                "message": {
                    "id": "m1",
                    "content": [
                        {"type": "tool_use", "id": "toolu_1", "name": "Agent", "input": {}},
                        {"type": "tool_use", "id": "toolu_2", "name": "Agent", "input": {}},
                    ],
                },
            },
            {
                **claude_context(2),
                "type": "user",
                "uuid": "r1",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}],
                },
                "toolUseResult": {"agentId": "aaa", "status": "async_launched"},
            },
            {
                **claude_context(3),
                "type": "user",
                "uuid": "r2",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "toolu_2", "content": "ok"}],
                },
                "toolUseResult": {"status": "completed"},
            },
        ],
    )
    for agent in ("aaa", "bbb"):
        write_jsonl(
            base / f"s1/subagents/agent-{agent}.jsonl",
            [
                {
                    **claude_context(4),
                    "type": "user",
                    "uuid": f"c-{agent}",
                    "isSidechain": True,
                    "agentId": agent,
                    "message": {"role": "user", "content": "child task"},
                }
            ],
        )
    # The second child is linked from its own sidecar (toolUseId), not the parent result.
    (base / "s1/subagents/agent-bbb.meta.json").write_text(
        json.dumps({"agentType": "general", "toolUseId": "toolu_2"})
    )
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("claude_code", root))
        calls = {
            row["native_call_id"]: row
            for row in store.db.execute(
                "SELECT * FROM tool_call WHERE native_call_id LIKE 'toolu%'"
            )
        }
        children = {
            row["native_id"]: row
            for row in store.db.execute(
                "SELECT s.*, i.native_id FROM session s JOIN session_identity i USING(session_uid)"
                " WHERE s.kind='subagent'"
            )
        }
        assert set(children) == {"s1:agent-aaa", "s1:agent-bbb"}
        for call, child in (("toolu_1", "s1:agent-aaa"), ("toolu_2", "s1:agent-bbb")):
            assert calls[call]["subagent_session_uid"] == children[child]["session_uid"]
            assert children[child]["spawn_call_uid"] == calls[call]["call_uid"]


def codex_parent():
    return [
        {"type": "session_meta", "timestamp": ISO.format(0), "payload": {"id": "parent"}},
        {
            "type": "event_msg",
            "timestamp": ISO.format(1),
            "payload": {"type": "task_started", "turn_id": "t"},
        },
        {
            "type": "response_item",
            "timestamp": ISO.format(2),
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "call_id": "call_spawn",
                "arguments": "{}",
            },
        },
        {
            "type": "event_msg",
            "timestamp": ISO.format(3),
            "payload": {
                "type": "item_completed",
                "turn_id": "t",
                "item": {
                    "type": "SubAgentActivity",
                    "id": "call_spawn",
                    "agent_thread_id": "child",
                    "agent_path": "/root/worker",
                    "kind": "started",
                },
            },
        },
    ]


def test_codex_spawn_agent_call_links_to_child_thread(tmp_path):
    child = [
        {
            "type": "session_meta",
            "timestamp": ISO.format(4),
            "payload": {
                "id": "child",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
            },
        },
        {
            "type": "event_msg",
            "timestamp": ISO.format(5),
            "payload": {"type": "user_message", "message": "work on the worker task"},
        },
    ]
    with Store(tmp_path / "data") as store:
        stream(store, "codex", tmp_path / "source", codex_parent(), "parent.jsonl")
        stream(store, "codex", tmp_path / "source", child, "child.jsonl")
        store.rebuild()
        call = one(store, "SELECT * FROM tool_call WHERE native_call_id='call_spawn'")
        session = one(
            store,
            "SELECT s.* FROM session s JOIN session_identity i USING(session_uid)"
            " WHERE i.native_id='child'",
        )
        assert session["kind"] == "subagent"
        assert call["subagent_session_uid"] == session["session_uid"]
        assert session["spawn_call_uid"] == call["call_uid"]


def origins(store, native):
    return [
        (row["actor"], json.loads(row["attrs"]).get("origin"))
        for row in store.db.execute(
            "SELECT e.* FROM event e JOIN session_identity i USING(session_uid)"
            " WHERE i.native_id=? AND e.kind='message.user'",
            (native,),
        )
    ]


def test_codex_review_and_subagent_prompts_are_not_human(tmp_path):
    def thread(native, source, text):
        return [
            {
                "type": "session_meta",
                "timestamp": ISO.format(0),
                "payload": {"id": native, "source": source},
            },
            {
                "type": "event_msg",
                "timestamp": ISO.format(1),
                "payload": {"type": "user_message", "message": text},
            },
        ]

    with Store(tmp_path / "data") as store:
        root = tmp_path / "source"
        stream(store, "codex", root, thread("main", "cli", "my own request"), "main.jsonl")
        stream(
            store,
            "codex",
            root,
            thread("review", {"subagent": {"other": "guardian"}}, "Review this action"),
            "review.jsonl",
        )
        stream(
            store,
            "codex",
            root,
            thread("worker", {"subagent": {"thread_spawn": {"parent_thread_id": "main"}}}, "do X"),
            "worker.jsonl",
        )
        store.rebuild()
        assert origins(store, "main") == [("human", "human")]
        assert origins(store, "review") == [("system", "automation")]
        assert origins(store, "worker") == [("system", "peer")]
        assert [row["text"] for row in store.db.execute("SELECT text FROM v_human_message")] == [
            "my own request"
        ]


def test_claude_subagent_prompt_is_peer_not_human(tmp_path):
    root = tmp_path / "claude"
    base = root / "projects/-synthetic-repo"
    write_jsonl(
        base / "s1.jsonl",
        [
            {
                **claude_context(0),
                "type": "user",
                "uuid": "u1",
                "message": {"role": "user", "content": "person"},
            }
        ],
    )
    write_jsonl(
        base / "s1/subagents/agent-aaa.jsonl",
        [
            {
                **claude_context(1),
                "type": "user",
                "uuid": "c1",
                "isSidechain": True,
                "message": {"role": "user", "content": "parent prompt"},
            }
        ],
    )
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("claude_code", root))
        assert origins(store, "s1") == [("human", "human")]
        assert origins(store, "s1:agent-aaa") == [("system", "peer")]


def test_claude_result_relocated_and_continued_in_have_destinations(tmp_path):
    root = tmp_path / "claude"
    base = root / "projects/-synthetic-repo"
    write_jsonl(
        base / "s1.jsonl",
        [
            {
                **claude_context(0),
                "type": "user",
                "uuid": "u1",
                "message": {"role": "user", "content": "hi"},
            },
            {"type": "relocated", "sessionId": "s1", "relocatedCwd": "/synthetic/moved"},
            {
                "type": "continued-in",
                "sessionId": "s1",
                "timestamp": ISO.format(2),
                "continuedInSessionId": "s2",
            },
            {
                "type": "result",
                "sessionId": "s1",
                "subtype": "success",
                "duration_ms": 1200,
                "result": "done",
                "usage": {"input_tokens": 1},
            },
        ],
    )
    write_jsonl(
        base / "s1/subagents/workflows/wf_1/journal.jsonl",
        [
            {"type": "started", "key": "k", "agentId": "w1", "label": "step"},
            {"type": "result", "key": "k", "agentId": "w1", "result": "agent summary"},
        ],
    )
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("claude_code", root))
        assert not store.db.execute("SELECT * FROM event WHERE kind='unknown'").fetchall()
        assert not store.db.execute(
            "SELECT * FROM ingest_issue WHERE code='unknown_native_type'"
        ).fetchall()
        paths = {
            row["event_path"]: row
            for row in store.db.execute(
                "SELECT * FROM event WHERE event_path IN"
                " ('relocated','continued-in','result','agent.result')"
            )
        }
        assert paths["relocated"]["kind"] == "setting.change"
        assert json.loads(paths["relocated"]["attrs"])["relocated_cwd"] == "/synthetic/moved"
        assert paths["result"]["kind"] == "turn.end"
        assert paths["agent.result"]["kind"] == "subagent.result"
        assert paths["agent.result"]["text"] == "agent summary"
        target = one(store, "SELECT session_uid FROM session_identity WHERE native_id='s2'")[0]
        link = one(store, "SELECT * FROM link WHERE kind='continued_in'")
        assert link["ref"] == target
        # The relocation is recorded, but the session keeps the cwd it started in.
        cwd = one(
            store,
            "SELECT s.cwd FROM session s JOIN session_identity i USING(session_uid)"
            " WHERE i.native_id='s1'",
        )[0]
        assert cwd == "/synthetic/repo"


def test_codex_background_exec_startup_has_no_fake_zero_duration(tmp_path):
    T = 1790900000000

    def command(native, started, completed, duration):
        return {
            "type": "event_msg",
            "timestamp": ISO.format(1),
            "payload": {
                "type": "item_completed",
                "turn_id": "t",
                "started_at_ms": started,
                "completed_at_ms": completed,
                "item": {
                    "type": "CommandExecution",
                    "id": native,
                    "command": ["rg", "x"],
                    "status": "completed",
                    "exit_code": 0,
                    "process_id": "1",
                    "source": "unified_exec_startup",
                    "duration": duration,
                },
            },
        }

    rows = [
        {"type": "session_meta", "timestamp": ISO.format(0), "payload": {"id": "s"}},
        command("background", T, T, {"secs": 0, "nanos": 1459}),
        command("measured", T, T + 3000, {"secs": 3, "nanos": 0}),
    ]
    with Store(tmp_path / "data") as store:
        stream(store, "codex", tmp_path / "source", rows, "s.jsonl")
        store.rebuild()
        calls = {
            row["native_call_id"]: row
            for row in store.db.execute(
                "SELECT native_call_id, duration_ms, duration_source, duration_quality"
                " FROM tool_call"
            )
        }
        assert calls["background"]["duration_ms"] is None
        assert calls["background"]["duration_quality"] == "missing"
        assert calls["measured"]["duration_ms"] == 3000
        assert calls["measured"]["duration_quality"] == "reported"
