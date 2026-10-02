"""Fictional in-memory records only; never discover or import local histories."""

import pytest


@pytest.fixture
def make_event():
    def make(uid="u", seq=1, kind="message.user", sid="s", ts=100, text="新增导出按钮", **attrs):
        return {"event_uid": uid, "session_uid": sid, "turn_uid": "turn-1", "seq": seq,
                "kind": kind, "actor": "human" if kind == "message.user" else "assistant",
                "ts": ts, "text": text, "attrs": {"origin": "human", "task_uid": "task-1", **attrs}}
    return make


@pytest.fixture
def make_call():
    def make(uid="c", **values):
        return {"call_uid": uid, "session_uid": "s", "turn_uid": "turn-1", "task_uid": "task-1",
                "seq": 1, "name_raw": "exec_command", "kind": "shell", "call_event_uid": uid,
                "result_event_uid": "r-" + uid, "status": "success", "status_scope": "command",
                "started_at": 100, "ended_at": 200, **values}
    return make


@pytest.fixture
def make_session():
    def make(sid="s", **values):
        return {"session_uid": sid, "root_uid": "s", "kind": "main", "project_id": "p",
                "started_at": 0, **values}
    return make
