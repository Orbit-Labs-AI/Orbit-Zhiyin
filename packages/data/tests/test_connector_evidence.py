"""Connector evidence: request boundaries, MCP identity, failure and approval records.

Constructed source-shaped samples (no real sessions). Expected values are derived by hand
from the upstream formats cited in each connector, not copied from mapper output.
"""

import json

from test_native_connectors import T, capture, rows, sqlrow

from tandem_data.contract import canonical
from tandem_data.inventory import InventoryRequest, scan_inventory
from tandem_data.store import Store


def kinds(store, kind):
    return [
        dict(r) for r in store.db.execute("SELECT * FROM event WHERE kind=? ORDER BY seq", (kind,))
    ]


def calls(store):
    return {r["native_call_id"]: r for r in rows(store, "tool_call")}


# --- dsh -------------------------------------------------------------------------------


def test_dsh_step_records_are_reported_request_boundaries(tmp_path):
    usage = {"inputTokens": 4, "outputTokens": 1, "cacheReadTokens": 0, "cacheWriteTokens": 0}
    records = [
        {"type": "session", "version": 4, "id": "s", "createdAt": T, "cwd": "/fixture"},
        {"type": "turn/start", "seq": 0, "time": T, "data": {"turn": 1}},
        {
            "type": "assistant/attempt",
            "seq": 3,
            "time": T + 1,
            "data": {"turn": 1, "step": 1, "usage": usage},
        },
        {
            "type": "assistant/message",
            "seq": 6,
            "time": T + 2,
            "data": {
                "turn": 1,
                "step": 1,
                "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                "usage": usage,
            },
        },
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "dsh", records)
        store.rebuild()
        got = {(r["request_id"], r["boundary_quality"]) for r in rows(store, "model_call")}
        # The failed attempt and the final message are two LLM requests (seq 3 and 6).
        assert got == {("seq:3", "reported"), ("seq:6", "reported")}


# --- kimi ------------------------------------------------------------------------------


def _kimi(store, tmp_path, records, version="1.5", path="sessions/wd/s/agents/main/wire.jsonl"):
    capture(
        store,
        tmp_path,
        "kimi",
        [{"type": "metadata", "protocol_version": version, "created_at": T}, *records],
        path,
    )
    store.rebuild()


def test_kimi_step_uuid_and_usage_record_are_reported_boundaries(tmp_path):
    step = {
        "type": "context.append_loop_event",
        "agentId": "main",
        "event": {"type": "step.end", "uuid": "step-1", "usage": {"inputOther": 3, "output": 1}},
        "time": T + 1,
    }
    record = {
        "type": "usage.record",
        "agentId": "main",
        "model": "m",
        "usageScope": "turn",
        "usage": {"inputOther": 3, "output": 1},
        "time": T + 2,
    }
    with Store(tmp_path / "a") as store:
        _kimi(store, tmp_path, [step])
        ((request_id, quality),) = [
            (r["request_id"], r["boundary_quality"]) for r in rows(store, "model_call")
        ]
        assert (request_id, quality) == ("step-1", "reported")
    with Store(tmp_path / "b") as store:
        # usage.record suppresses the step.end mirror; one request, named by position.
        _kimi(store, tmp_path, [step, record])
        (call,) = rows(store, "model_call")
        assert call["boundary_quality"] == "reported"
        assert call["request_id"].startswith("usage.record:")


def test_kimi_tasks_are_not_subagent_spawns(tmp_path):
    def task(typ, info, offset):
        return {"type": typ, "agentId": "main", "info": info, "time": T + offset}

    agent = {"taskId": "t1", "kind": "agent", "agentId": "sub", "status": "running"}
    process = {"taskId": "t2", "kind": "process", "command": "sleep 1", "pid": 9}
    records = [
        task("task.started", agent, 1),
        task("task.terminated", {**agent, "status": "completed"}, 2),
        task("task.started", {**process, "status": "running", "exitCode": None}, 3),
        task("task.terminated", {**process, "status": "failed", "exitCode": 2}, 4),
    ]
    with Store(tmp_path / "data") as store:
        _kimi(store, tmp_path, records)
        assert kinds(store, "subagent.spawn") == []
        assert kinds(store, "subagent.result") == []
        assert len(kinds(store, "subagent.activity")) == 2
        ended = [json.loads(e["attrs"]) for e in kinds(store, "ui.state")]
        assert [a.get("exit_code") for a in ended] == [None, 2]


def test_kimi_protocol_versions_beyond_verified_range(tmp_path):
    def issues(store):
        return {
            (r["code"], r["severity"])
            for r in store.db.execute("SELECT code, severity FROM ingest_issue")
            if r["code"].endswith("native_version")
        }

    for version, expected in (
        ("1.5", set()),
        ("1.7", {("untested_native_version", "info")}),
        ("2.0", {("unsupported_native_version", "warning")}),
    ):
        with Store(tmp_path / version) as store:
            _kimi(store, tmp_path, [], version)
            assert issues(store) == expected, version


def test_kimi_approval_links_to_its_tool_call(tmp_path):
    def loop(event, offset):
        return {
            "type": "context.append_loop_event",
            "agentId": "main",
            "event": event,
            "time": T + offset,
        }

    records = [
        loop({"type": "tool.call", "toolCallId": "c", "name": "Shell", "args": {}}, 1),
        {
            "type": "interaction.request",
            "agentId": "main",
            "id": "i1",
            "kind": "approval",
            "toolCallId": "c",
            "request": {},
            "time": T + 2,
        },
        {
            "type": "interaction.resolved",
            "agentId": "main",
            "id": "i1",
            "response": {"decision": "rejected"},
            "time": T + 7,
        },
        loop(
            {
                "type": "tool.result",
                "toolCallId": "c",
                "result": {"output": "rejected", "isError": True},
            },
            8,
        ),
        # A question interaction is not a permission prompt.
        {
            "type": "interaction.request",
            "agentId": "main",
            "id": "q1",
            "kind": "question",
            "request": {},
            "time": T + 9,
        },
    ]
    with Store(tmp_path / "data") as store:
        _kimi(store, tmp_path, records)
        call = calls(store)["c"]
        # Wait = resolved (T+7) - request (T+2).
        assert (call["approval"], call["approval_wait_ms"]) == ("rejected", 5)
        assert call["failure_kind"] == "permission_denied"
        assert len(kinds(store, "permission.request")) == 1


# --- opencode --------------------------------------------------------------------------


def _opencode_inventory(store, tmp_path):
    config = tmp_path / "opencode-config"
    config.mkdir()
    (config / "opencode.json").write_text(
        json.dumps({"mcp": {"my-server": {"type": "local", "command": ["x"]}}})
    )
    scan_inventory(store, InventoryRequest("opencode", config))


def test_opencode_v1_settings_mcp_exit_and_permission(tmp_path):
    def message(id_, offset, **data):
        return sqlrow(
            "message",
            {"id": id_, "session_id": "s", "time_created": T + offset, "data": canonical(data)},
        )

    def part(id_, offset, **data):
        return sqlrow(
            "part",
            {
                "id": id_,
                "message_id": "m2",
                "session_id": "s",
                "time_created": T + offset,
                "data": canonical(data),
            },
        )

    def tool(id_, name, offset, **state):
        return part(
            id_,
            offset,
            type="tool",
            callID=id_,
            tool=name,
            state={"input": {}, "time": {"start": T + offset, "end": T + offset + 1}, **state},
        )

    records = [
        sqlrow("session", {"id": "s", "directory": "/fixture"}),
        message("m1", 0, role="user"),
        message("m2", 1, role="assistant", modelID="a", providerID="p"),
        message("m3", 2, role="assistant", modelID="a", providerID="p"),
        message("m4", 3, role="assistant", modelID="b", providerID="p"),
        tool("c-mcp", "my-server_search", 4, status="completed", output="hit", metadata={}),
        tool("c-other", "other_search", 6, status="completed", output="x", metadata={}),
        tool("c-exit", "bash", 8, status="completed", output="", metadata={"exit": 2}),
        tool(
            "c-denied",
            "bash",
            10,
            status="error",
            error="The user rejected permission to use this specific tool call.",
        ),
        tool(
            "c-abort",
            "bash",
            12,
            status="error",
            error="Tool execution aborted",
            metadata={"interrupted": True},
        ),
        part(
            "p-step",
            14,
            type="step-finish",
            tokens={"input": 1, "output": 1, "cache": {"read": 0, "write": 0}},
        ),
    ]
    with Store(tmp_path / "data") as store:
        _opencode_inventory(store, tmp_path)
        capture(store, tmp_path, "opencode", records, "opencode.db", "sqlite_rows")
        store.rebuild()
        # Session row is the only header; m2 (first model) and m4 (switch) are changes.
        assert len(kinds(store, "session.meta")) == 1
        changes = [json.loads(e["attrs"])["model_raw"] for e in kinds(store, "setting.change")]
        assert changes == ["a", "b"]
        got = calls(store)
        assert (got["c-mcp"]["kind"], got["c-mcp"]["mcp_server"], got["c-mcp"]["mcp_tool"]) == (
            "mcp",
            "my-server",
            "search",
        )
        assert got["c-other"]["mcp_server"] is None
        assert (got["c-exit"]["exit_code"], got["c-exit"]["failure_kind"]) == (2, "nonzero_exit")
        assert (got["c-denied"]["approval"], got["c-denied"]["failure_kind"]) == (
            "denied",
            "permission_denied",
        )
        assert (got["c-abort"]["status"], got["c-abort"]["failure_kind"]) == (
            "interrupted",
            "interrupted",
        )
        ((request_id, quality),) = [
            (r["request_id"], r["boundary_quality"]) for r in rows(store, "model_call")
        ]
        assert (request_id, quality) == ("p-step", "reported")


def test_opencode_mcp_without_inventory_stays_unresolved(tmp_path):
    records = [
        sqlrow("session", {"id": "s", "directory": "/fixture"}),
        sqlrow(
            "part",
            {
                "id": "p",
                "message_id": "m",
                "session_id": "s",
                "time_created": T,
                "data": canonical(
                    {"type": "tool", "callID": "c", "tool": "my-server_search", "state": {}}
                ),
            },
        ),
    ]
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "opencode", records, "opencode.db", "sqlite_rows")
        store.rebuild()
        assert calls(store)["c"]["mcp_server"] is None


# --- hermes ----------------------------------------------------------------------------


def test_hermes_legacy_mcp_names_errors_and_approvals(tmp_path):
    config = tmp_path / "hermes-home"
    config.mkdir()
    (config / "config.yaml").write_text("mcp_servers:\n  my_srv:\n    command: x\n")
    names = {
        "c-mcp": "mcp_my_srv_list_items",
        "c-deny": "terminal",
        "c-ok": "terminal",
        "c-err": "web_search",
    }
    results = {
        "c-mcp": {"items": []},
        "c-deny": {
            "output": "",
            "exit_code": -1,
            "error": "Command denied: rm. Use the approval prompt to allow it.",
            "status": "blocked",
        },
        "c-ok": {
            "output": "done",
            "exit_code": 0,
            "approval": "Command required approval (rm) and was approved by the user.",
        },
        "c-err": {"error": "network unreachable"},
    }
    records = [
        sqlrow("sessions", {"id": "a", "model": "A", "started_at": 1790900000}),
        sqlrow(
            "messages",
            {
                "id": 1,
                "session_id": "a",
                "message_uid": "m",
                "role": "assistant",
                "content": "",
                "active": 1,
                "tool_calls": canonical(
                    [
                        {"id": call_id, "function": {"name": name, "arguments": "{}"}}
                        for call_id, name in names.items()
                    ]
                ),
                "timestamp": 1790900001,
            },
        ),
    ]
    for index, (call_id, content) in enumerate(results.items()):
        records.append(
            sqlrow(
                "messages",
                {
                    "id": 2 + index,
                    "session_id": "a",
                    "message_uid": f"r{index}",
                    "role": "tool",
                    "content": canonical(content),
                    "tool_call_id": call_id,
                    "active": 1,
                    "timestamp": 1790900002 + index,
                },
            )
        )
    with Store(tmp_path / "data") as store:
        scan_inventory(store, InventoryRequest("hermes", config))
        capture(store, tmp_path, "hermes", records, "state.db", "sqlite_rows")
        store.rebuild()
        got = calls(store)
        assert (got["c-mcp"]["mcp_server"], got["c-mcp"]["mcp_tool"]) == ("my_srv", "list_items")
        deny = got["c-deny"]
        assert (deny["approval"], deny["error_class"], deny["failure_kind"]) == (
            "denied",
            "permission_refused",
            "permission_denied",
        )
        ok = got["c-ok"]
        assert (ok["approval"], ok["status"], ok["failure_kind"]) == ("approved", "completed", None)
        err = got["c-err"]
        assert (err["status"], err["error_class"], err["failure_kind"]) == (
            "failed",
            "tool_error",
            "harness_error",
        )


# --- pi --------------------------------------------------------------------------------


def test_pi_bash_status_line_gives_exit_code_and_interrupt(tmp_path):
    texts = {
        "c-exit": "fatal: not a repo\n\nCommand exited with code 128",
        "c-abort": "partial\n\nCommand aborted",
        "c-timeout": "Command timed out after 30 seconds",
        # Not the trailing status line: no exit code may be read from it.
        "c-plain": "Command exited with code 3 was printed by the script\nthen it failed",
    }
    records = [{"type": "session", "id": "s", "timestamp": "2026-10-02T00:00:00Z"}]
    records.append(
        {
            "type": "message",
            "id": "a",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "toolCall", "id": cid, "name": "bash", "arguments": {}}
                    for cid in texts
                ],
            },
        }
    )
    for index, (cid, text) in enumerate(texts.items()):
        records.append(
            {
                "type": "message",
                "id": f"r{index}",
                "parentId": "a",
                "message": {
                    "role": "toolResult",
                    "toolCallId": cid,
                    "toolName": "bash",
                    "content": [{"type": "text", "text": text}],
                    "isError": True,
                },
            }
        )
    with Store(tmp_path / "data") as store:
        capture(store, tmp_path, "pi", records)
        store.rebuild()
        got = {
            cid: (r["status"], r["exit_code"], r["error_class"], r["failure_kind"])
            for cid, r in calls(store).items()
        }
        assert got == {
            "c-exit": ("failed", 128, None, "nonzero_exit"),
            "c-abort": ("interrupted", None, None, "interrupted"),
            "c-timeout": ("failed", None, "timeout", "harness_error"),
            "c-plain": ("failed", None, None, None),
        }
