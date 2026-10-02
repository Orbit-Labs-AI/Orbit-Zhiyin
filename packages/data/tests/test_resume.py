import os
import sqlite3
import subprocess

import pytest

from tandem_data.resume import AGENTS, resume_template, session_resume
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store
from tandem_data.validation.fixtures import create_sources

SEVEN = {"claude_code", "codex", "opencode", "pi", "hermes", "dsh", "kimi"}


@pytest.fixture
def no_processes(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("resume must not start a process")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in ("system", "execv", "execvp", "execvpe", "spawnv", "posix_spawn", "fork"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, forbidden)
    yield calls
    assert calls == []


def test_every_agent_has_a_template_or_reason(no_processes):
    assert set(AGENTS) == SEVEN
    for agent in SEVEN:
        result = resume_template(agent, "abc-123", cwd="/work/x y", session_file="/data/pi/s.jsonl")
        assert result["supported"], (agent, result["reason"])
        assert result["evidence"]
        assert not result["disabled"]
        assert "abc-123" in result["command"] or "/data/pi/s.jsonl" in result["command"]
    unknown = resume_template("other", "abc")
    assert not unknown["supported"] and "no resume entry" in unknown["reason"]
    assert resume_template("kimi", "a", cwd="/w")["verified"] is False


def test_running_sessions_are_disabled_but_still_described(no_processes):
    result = resume_template("claude_code", "abc", status="active", cwd="/w")
    assert result["supported"] and result["disabled"]
    assert result["reason"] == "session is still running"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"native_id": "--dangerous", "cwd": "/w"}, "not safe"),
        ({"native_id": "a\nb", "cwd": "/w"}, "not safe"),
        ({"native_id": None, "cwd": "/w"}, "unavailable"),
        ({"native_id": "abc"}, "working directory"),
        ({"native_id": "abc", "cwd": "/w", "kind": "subagent"}, "root session"),
    ],
)
def test_unsupported_reasons(no_processes, kwargs, reason):
    native_id = kwargs.pop("native_id")
    result = resume_template("claude_code", native_id, **kwargs)
    assert not result["supported"] and reason in result["reason"]
    assert result["command"] is None


def test_shell_quoting_of_cwd(no_processes):
    result = resume_template("codex", "id1", cwd="/work/it's here")
    assert result["command"] == "cd '/work/it'\"'\"'s here' && codex resume id1"
    assert result["argv"] == ["codex", "resume", "id1"]


def test_projected_sessions(tmp_path, no_processes):
    roots = create_sources(tmp_path / "fixtures")
    home = tmp_path / "home"
    with Store(home) as store:
        service = ImportService(store)
        for agent, root in roots.items():
            service.import_source(ImportRequest(agent, root))
        sessions = dict(
            store.db.execute(
                "SELECT src.agent, s.session_uid FROM session s JOIN source src USING(source_id)"
            )
        )
    for agent, session_uid in sessions.items():
        result = session_resume(home, session_uid)
        assert result["session_uid"] == session_uid and result["agent"] == agent
        assert result["supported"] or result["reason"], agent
    pi = session_resume(home, sessions["pi"])
    assert pi["supported"] and pi["argv"][-1].endswith(".jsonl")
    assert pi["argv"][-1].startswith(str(roots["pi"].resolve()))
    db = sqlite3.connect(home / "tandem.db")
    db.execute("UPDATE session SET status='active' WHERE session_uid=?", (sessions["claude_code"],))
    db.commit()
    db.close()
    running = session_resume(home, sessions["claude_code"])
    assert running["disabled"] and running["status"] == "active"
    with pytest.raises(KeyError):
        session_resume(home, "session_missing")
    with pytest.raises(FileNotFoundError):
        session_resume(tmp_path / "empty", "x")
