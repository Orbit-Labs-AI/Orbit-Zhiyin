import shlex
import time

import pytest

from tandem_backend.sessionops import resume

NOW = 1_800_000_000_000
CWD = "/tmp/my proj/it's"


def row(**values):
    return {"session_uid": "s1", "agent": "claude_code", "native_id": "abc-1", "cwd": CWD,
            "status": "completed", "ended_at": 1, "last_event_ts": NOW - 600_000, **values}


# Expected argv written from each CLI's documented resume entry (not read from the template table).
EXPECTED = {
    "claude_code": (["claude", "--resume", "abc-1"], True, True),
    "codex": (["codex", "resume", "abc-1"], True, True),
    "opencode": (["opencode", "--session", "abc-1"], True, True),
    "pi": (["pi", "--session", "/s/pi/a b.jsonl"], True, True),
    "hermes": (["hermes", "--resume", "abc-1"], False, True),
    "dsh": (["dsh", "tui", "--resume", "abc-1"], True, True),
    "kimi": (["kimi", "--session", "abc-1"], True, False),
}


@pytest.mark.parametrize("agent", sorted(EXPECTED))
def test_seven_agents_have_copyable_commands(agent):
    argv, needs_cwd, verified = EXPECTED[agent]
    body = resume.build(row(agent=agent, session_file="/s/pi/a b.jsonl"), NOW)
    assert body["available"] and body["disabled_reason"] is None
    command = body["commands"][0]
    assert command["argv"] == argv and command["verified"] is verified and command["evidence"]
    expected_shell = ["cd", CWD, "&&", *argv] if needs_cwd else argv
    assert shlex.split(command["shell"]) == expected_shell
    assert (command["note"] is None) is verified


def test_hermes_needs_no_cwd_and_pi_needs_the_file():
    hermes = resume.build(row(agent="hermes", cwd=None), NOW)
    assert hermes["available"] and hermes["commands"][0]["shell"] == "hermes --resume abc-1"
    assert resume.build(row(agent="pi"), NOW)["disabled_reason"] == "unknown_session"


def test_disabled_reasons():
    other = resume.build(row(agent="gemini"), NOW)
    assert other["disabled_reason"] == "unsupported_agent" and not other["commands"]
    assert resume.build(row(cwd=None), NOW)["disabled_reason"] == "no_cwd"
    assert resume.build(row(native_id=None), NOW)["disabled_reason"] == "unknown_session"
    assert resume.build(row(native_id="--evil"), NOW)["disabled_reason"] == "unsafe_session_id"
    assert resume.build(row(kind="subagent"), NOW)["disabled_reason"] == "not_root_session"
    running = resume.build(row(last_event_ts=NOW - 60_000), NOW)
    assert running["running"] and not running["available"]
    assert running["disabled_reason"] == "running" and running["commands"]
    active = resume.build(row(status="active", ended_at=None, last_event_ts=None), NOW)
    assert active["disabled_reason"] == "running"


def test_resume_endpoint(tandem, client):
    tandem.session("s1", cwd=CWD)
    tandem.event("s1", ts=int(time.time() * 1000))
    tandem.session("s2", agent="gemini")
    tandem.session("s3", agent="opencode")
    tandem.session("s4", agent="pi")
    tandem.raw_file("s4", "pi", "2026/s4.jsonl")
    tandem.session("s5", agent="hermes", cwd=None)
    body = client.get("/v1/sessions/s1/resume").json()
    assert body["running"] and body["disabled_reason"] == "running"
    assert body["native_id"] == "native-s1" and body["cwd"] == CWD
    assert client.get("/v1/sessions/s2/resume").json()["disabled_reason"] == "unsupported_agent"
    opencode = client.get("/v1/sessions/s3/resume").json()
    assert opencode["available"] and opencode["commands"][0]["argv"] == ["opencode", "--session", "native-s3"]
    pi = client.get("/v1/sessions/s4/resume").json()
    assert pi["available"] and pi["commands"][0]["argv"][-1] == str(tandem.roots / "pi" / "2026/s4.jsonl")
    assert client.get("/v1/sessions/s5/resume").json()["commands"][0]["argv"] == ["hermes", "--resume",
                                                                                "native-s5"]
    assert client.get("/v1/sessions/zz/resume").status_code == 404
