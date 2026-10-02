import shlex
import time

from tandem_backend.sessionops import resume

NOW = 1_800_000_000_000
CWD = "/tmp/my proj/it's"


def row(**values):
    return {"session_uid": "s1", "agent": "claude_code", "native_id": "abc-1", "cwd": CWD,
            "status": "completed", "ended_at": 1, "last_event_ts": NOW - 600_000, **values}


def test_claude_and_codex_templates_quote_cwd():
    claude = resume.build(row(), NOW)
    assert claude["available"] and claude["disabled_reason"] is None
    command = claude["commands"][0]
    assert command["label"] == "在 Claude Code 中继续" and command["verified"] is False
    assert command["note"] == "参数待验证" and command["argv"] == ["claude", "--resume", "abc-1"]
    assert shlex.split(command["shell"]) == ["cd", CWD, "&&", "claude", "--resume", "abc-1"]
    codex = resume.build(row(agent="codex", native_id="x y"), NOW)["commands"][0]
    assert codex["label"] == "在 Codex 中继续"
    assert shlex.split(codex["shell"]) == ["cd", CWD, "&&", "codex", "resume", "x y"]


def test_disabled_reasons():
    other = resume.build(row(agent="gemini"), NOW)
    assert other["disabled_reason"] == "unsupported_agent" and not other["commands"]
    assert resume.build(row(cwd=None), NOW)["disabled_reason"] == "no_cwd"
    running = resume.build(row(last_event_ts=NOW - 60_000), NOW)
    assert running["running"] and not running["available"]
    assert running["disabled_reason"] == "running" and running["commands"]
    active = resume.build(row(status="active", ended_at=None, last_event_ts=None), NOW)
    assert active["disabled_reason"] == "running"


def test_resume_endpoint(tandem, client):
    tandem.session("s1", cwd=CWD)
    tandem.event("s1", ts=int(time.time() * 1000))
    tandem.session("s2", agent="gemini")
    body = client.get("/v1/sessions/s1/resume").json()
    assert body["running"] and body["disabled_reason"] == "running"
    assert body["native_id"] == "native-s1" and body["cwd"] == CWD
    assert client.get("/v1/sessions/s2/resume").json()["disabled_reason"] == "unsupported_agent"
    assert client.get("/v1/sessions/zz/resume").status_code == 404
