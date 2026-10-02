"""Small synthetic sessions in native storage layouts for the one-command demo."""

import sqlite3
from pathlib import Path

from tandem_data.contract import canonical

AGENTS = ("claude_code", "opencode", "dsh", "pi", "hermes", "kimi")
T = 1790900000000
ISO = "2026-10-02T00:00:00Z"


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")
    path.chmod(0o600)


def create_sources(folder: Path) -> dict[str, Path]:
    roots = {agent: folder / agent for agent in AGENTS}
    common = {"sessionId": "demo", "cwd": "/tandem-demo", "timestamp": ISO}
    _jsonl(
        roots["claude_code"] / "projects/demo/demo.jsonl",
        [
            {**common, "type": "user", "uuid": "u", "message": {"content": "检查仓库状态"}},
            {
                **common,
                "type": "assistant",
                "uuid": "a",
                "message": {
                    "id": "r",
                    "model": "fixture-model",
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "c",
                            "name": "Bash",
                            "input": {"command": "git status"},
                        }
                    ],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 10,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
            {
                **common,
                "type": "user",
                "uuid": "o",
                "toolUseResult": {"durationMs": 8},
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "c",
                            "content": "clean",
                            "is_error": False,
                        }
                    ]
                },
            },
        ],
    )
    _jsonl(
        roots["pi"] / "sessions/demo/demo.jsonl",
        [
            {
                "type": "session",
                "id": "demo",
                "version": 3,
                "timestamp": ISO,
                "cwd": "/tandem-demo",
            },
            {
                "type": "message",
                "id": "u",
                "timestamp": ISO,
                "message": {"role": "user", "content": "检查仓库状态"},
            },
            {
                "type": "message",
                "id": "a",
                "parentId": "u",
                "timestamp": ISO,
                "message": {
                    "role": "assistant",
                    "provider": "fixture",
                    "model": "fixture-model",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "c",
                            "name": "bash",
                            "arguments": {"command": "git status"},
                        }
                    ],
                    "usage": {
                        "input": 20,
                        "output": 5,
                        "cacheRead": 10,
                        "cacheWrite": 0,
                        "cost": {"total": 0.01},
                    },
                },
            },
            {
                "type": "message",
                "id": "o",
                "parentId": "a",
                "timestamp": ISO,
                "message": {
                    "role": "toolResult",
                    "toolCallId": "c",
                    "toolName": "bash",
                    "isError": False,
                    "content": [{"type": "text", "text": "clean"}],
                },
            },
        ],
    )
    _jsonl(
        roots["dsh"] / "sessions/demo/demo/session.v4.jsonl",
        [
            {"type": "session", "id": "demo", "version": 4, "createdAt": T, "cwd": "/tandem-demo"},
            {"type": "turn/start", "seq": 0, "time": T, "data": {"turn": 1}},
            {
                "type": "user/message",
                "seq": 1,
                "time": T,
                "data": {
                    "role": "user",
                    "source": {"kind": "user"},
                    "content": [{"type": "text", "text": "检查仓库状态"}],
                },
            },
            {
                "type": "assistant/message",
                "seq": 2,
                "time": T + 1,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "message": {
                        "role": "assistant",
                        "source": {"provider": "fixture", "model": "fixture-model"},
                        "content": [{"type": "text", "text": "开始检查"}],
                    },
                    "usage": {
                        "inputTokens": 20,
                        "outputTokens": 5,
                        "cacheReadTokens": 10,
                        "cacheWriteTokens": 0,
                    },
                },
            },
            {
                "type": "tool/call",
                "seq": 3,
                "time": T + 2,
                "data": {
                    "turn": 1,
                    "callId": "c",
                    "name": "bash",
                    "arguments": '{"command":"git status"}',
                },
            },
            {
                "type": "tool/result",
                "seq": 4,
                "time": T + 10,
                "data": {
                    "turn": 1,
                    "message": {
                        "role": "tool",
                        "toolCallId": "c",
                        "isError": False,
                        "content": [{"type": "text", "text": "clean"}],
                    },
                },
            },
            {
                "type": "turn/end",
                "seq": 5,
                "time": T + 11,
                "data": {"turn": 1, "reason": {"kind": "completed"}},
            },
        ],
    )
    _jsonl(
        roots["kimi"] / "sessions/wd_demo/demo/agents/main/wire.jsonl",
        [
            {"type": "metadata", "protocol_version": "1.5", "created_at": T},
            {"type": "turn.prompt", "agentId": "main", "turnId": 1, "origin": "user", "time": T},
            {
                "type": "context.append_message",
                "agentId": "main",
                "time": T,
                "message": {
                    "id": "u",
                    "role": "user",
                    "origin": {"kind": "user"},
                    "content": [{"type": "text", "text": "检查仓库状态"}],
                    "toolCalls": [],
                },
            },
            {
                "type": "context.append_loop_event",
                "time": T + 1,
                "event": {
                    "type": "tool.call",
                    "stepUuid": "r",
                    "toolCallId": "c",
                    "name": "Shell",
                    "args": {"command": "git status"},
                },
            },
            {
                "type": "context.append_loop_event",
                "time": T + 9,
                "event": {
                    "type": "tool.result",
                    "toolCallId": "c",
                    "result": {"output": "clean", "isError": False, "durationMs": 8},
                },
            },
            {
                "type": "usage.record",
                "model": "fixture-model",
                "usageScope": "turn",
                "time": T + 10,
                "usage": {
                    "inputOther": 20,
                    "output": 5,
                    "inputCacheRead": 10,
                    "inputCacheCreation": 0,
                },
            },
            {"type": "turn.ended", "turnId": 1, "reason": "completed", "time": T + 11},
        ],
    )
    roots["opencode"].mkdir(parents=True, exist_ok=True)
    path = roots["opencode"] / "opencode.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE session(id TEXT PRIMARY KEY,directory TEXT,title TEXT); CREATE TABLE session_message(id TEXT PRIMARY KEY,session_id TEXT,seq INTEGER,type TEXT,data TEXT);"
        )
        db.execute("INSERT INTO session VALUES(?,?,?)", ("demo", "/tandem-demo", "OpenCode demo"))
        db.execute(
            "INSERT INTO session_message VALUES(?,?,?,?,?)",
            ("u", "demo", 0, "user", canonical({"text": "检查仓库状态", "time": {"created": T}})),
        )
        db.execute(
            "INSERT INTO session_message VALUES(?,?,?,?,?)",
            (
                "a",
                "demo",
                1,
                "assistant",
                canonical(
                    {
                        "model": {"id": "fixture-model", "providerID": "fixture"},
                        "time": {"created": T + 1},
                        "content": [
                            {
                                "type": "tool",
                                "id": "c",
                                "name": "bash",
                                "time": {"created": T + 1, "ran": T + 2, "completed": T + 10},
                                "state": {
                                    "status": "completed",
                                    "input": {"command": "git status"},
                                    "content": [{"type": "text", "text": "clean"}],
                                    "structured": {},
                                },
                            }
                        ],
                        "tokens": {
                            "input": 20,
                            "output": 3,
                            "reasoning": 2,
                            "cache": {"read": 10, "write": 0},
                        },
                        "cost": 0.01,
                    }
                ),
            ),
        )
    path.chmod(0o600)
    roots["hermes"].mkdir(parents=True, exist_ok=True)
    path = roots["hermes"] / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY,cwd TEXT,model TEXT,started_at REAL); CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,message_uid TEXT,role TEXT,content TEXT,tool_calls TEXT,tool_call_id TEXT,timestamp REAL); CREATE TABLE session_model_usage(session_id TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,cache_read_tokens INTEGER,cache_write_tokens INTEGER,last_seen REAL,PRIMARY KEY(session_id,model));"
        )
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            ("demo", "/tandem-demo", "fixture-model", T / 1000),
        )
        db.executemany(
            "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
            [
                (1, "demo", "u", "user", "检查仓库状态", None, None, T / 1000),
                (
                    2,
                    "demo",
                    "a",
                    "assistant",
                    "开始检查",
                    canonical(
                        [
                            {
                                "id": "c",
                                "function": {
                                    "name": "terminal",
                                    "arguments": '{"command":"git status"}',
                                },
                            }
                        ]
                    ),
                    None,
                    T / 1000 + 1,
                ),
                (3, "demo", "o", "tool", "clean", None, "c", T / 1000 + 2),
            ],
        )
        db.execute(
            "INSERT INTO session_model_usage VALUES(?,?,?,?,?,?,?)",
            ("demo", "fixture-model", 20, 5, 10, 0, T / 1000 + 3),
        )
    path.chmod(0o600)
    return roots
