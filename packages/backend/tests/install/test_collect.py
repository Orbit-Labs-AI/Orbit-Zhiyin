"""IN-07 / DT-16: Orbit's own collection installs, records events and reverts byte for byte.

Fabricated agent homes and a tmp Orbit home only; hooks are replayed by running the
installed command with synthetic stdin, never a real agent.
"""

import json
import os
import subprocess
import tomllib

import pytest

from orbit_backend.appdb import AppDB
from orbit_backend.install import collect
from orbit_backend.install.service import InstallService

SETTINGS = json.dumps({
    "permissions": {"allow": []},
    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "afplay Glass.aiff"}]}]},
    "statusLine": {"type": "command", "command": "echo mine", "padding": 0},
    "cleanupPeriodDays": 30,
}, indent=2) + "\n"
CONFIG = 'model = "gpt-5"\n\n[mcp_servers.docs]\ncommand = "npx"\n'


@pytest.fixture
def svc(tmp_path, env):
    db = AppDB(tmp_path / "orbit" / "app.db")
    yield InstallService(db, tmp_path / "orbit", env=env)
    db.close()


def run(command: str, stdin: dict | None = None, *args: str) -> subprocess.CompletedProcess:
    data = json.dumps(stdin).encode() if stdin is not None else b""
    return subprocess.run(command + "".join(f" {a}" for a in args), shell=True, input=data,
                          capture_output=True, timeout=20, check=True)


def install(svc, agents=("claude_code", "codex")):
    plan = svc.plan({"type": "collect"}, agents=list(agents))
    assert plan["status"] == "ready" and plan["kind"] == "collect"
    preview = svc.preview(plan["plan_id"])
    assert not preview["conflicts"] and preview["risk"]["level"] != "dangerous"
    return plan, svc.apply(plan["plan_id"], preview["preview_digest"])


def test_install_replay_and_revert_bytes(svc, fake_home, tmp_path):
    settings_path, config_path = fake_home / ".claude/settings.json", fake_home / ".codex/config.toml"
    settings_path.write_text(SETTINGS)
    config_path.write_text(CONFIG)
    before = {p: p.read_bytes() for p in (settings_path, config_path)}

    plan, applied = install(svc)
    assert applied["state"] == "installed"
    events = tmp_path / "orbit" / "hooks" / "events.jsonl"

    settings = json.loads(settings_path.read_text())
    stop = settings["hooks"]["Stop"]
    assert stop[0]["hooks"][0]["command"] == "afplay Glass.aiff" and len(stop) == 2
    hook_cmd = settings["hooks"]["PermissionRequest"][0]["hooks"][0]["command"]
    assert "hook --agent claude_code" in hook_cmd and str(events) in hook_cmd
    assert settings["cleanupPeriodDays"] == collect.GUARD_DAYS
    status = settings["statusLine"]
    assert status["padding"] == 0 and status["command"].endswith("--wrap 'echo mine'")
    script = fake_home / ".claude/hooks/orbit/orbit_collect.py"
    assert os.access(script, os.X_OK)
    config = config_path.read_text()
    assert config.startswith("# >>> orbit:collect >>>") and config.endswith(CONFIG)
    notify = tomllib.loads(config)["notify"]
    assert notify[2] == "notify" and tomllib.loads(config)["mcp_servers"]["docs"]["command"] == "npx"

    # replay: hooks print nothing (read-only), the status line still shows the user's own
    assert run(hook_cmd, {"hook_event_name": "PermissionRequest", "session_id": "c1",
                          "tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}).stdout == b""
    shown = run(status["command"], {"session_id": "c1", "model": {"id": "claude-x"},
                                    "context_window": {"context_window_size": 200000,
                                                       "current_usage": {"input_tokens": 5,
                                                                         "cache_read_input_tokens": 150000}}})
    assert shown.stdout == b"mine\n"
    run(status["command"], {"session_id": "c1", "model": {"id": "claude-x"}})  # same line twice: one row
    run(status["command"], {"session_id": "c1", "model": {"id": "claude-x"}})
    run(hook_cmd, {"hook_event_name": "PostToolUse", "session_id": "c1", "tool_name": "Bash"})
    turn = json.dumps({"type": "agent-turn-complete", "thread-id": "x1", "cwd": "/p"})
    subprocess.run([*notify, turn], check=True, timeout=20)  # Codex appends the JSON as last argv
    rows = [json.loads(line) for line in events.read_text().splitlines()]
    assert [(r["agent"], r["event"]) for r in rows] == [
        ("claude_code", "PermissionRequest"), ("claude_code", "StatusLine"), ("claude_code", "StatusLine"),
        ("claude_code", "PostToolUse"), ("codex", "Stop")]
    assert rows[0]["command"] == "rm -rf build" and rows[1]["context"]["used_tokens"] == 150005
    assert rows[4]["session_id"] == "x1"

    assert collect.status(svc)["installed"] and collect.status(svc)["events_bytes"] > 0
    assert svc.plan({"type": "collect"}, agents=["claude_code", "codex"])["already_installed"]

    reverted = svc.revert(applied["install_id"])
    assert reverted["state"] == "reverted"
    assert {p: p.read_bytes() for p in before} == before
    assert not script.exists() and not collect.status(svc)["installed"]
    assert events.exists()  # collected data stays; only the agent files are restored


def test_fresh_home_without_statusline_or_config(svc, fake_home):
    (fake_home / ".codex/config.toml").unlink()
    plan, applied = install(svc)
    settings = json.loads((fake_home / ".claude/settings.json").read_text())
    assert "--wrap" not in settings["statusLine"]["command"]
    assert tomllib.loads((fake_home / ".codex/config.toml").read_text())["notify"]
    svc.revert(applied["install_id"])
    assert not (fake_home / ".codex/config.toml").exists()
    assert json.loads((fake_home / ".claude/settings.json").read_text()) == {"permissions": {"allow": []}}


def test_respects_user_choices(svc, fake_home):
    settings = {"cleanupPeriodDays": 0, "statusLine": {"type": "command", "command": "x orbit_collect.py y"}}
    (fake_home / ".claude/settings.json").write_text(json.dumps(settings))
    (fake_home / ".codex/config.toml").write_text('notify = ["say"]\n')
    plan = svc.plan({"type": "collect"}, agents=["claude_code", "codex"])
    codex = [t for t in plan["targets"] if t["agent"] == "codex"]
    assert codex == [{**codex[0], "mappable": False, "reason": "codex_notify_in_use"}]
    claude = [t for t in plan["targets"] if t["agent"] == "claude_code"]
    assert all(t["display"].endswith(("settings.json", "orbit_collect.py")) for t in claude)
    # no statusLine / cleanup target: already wrapped, and 0 (transcripts off) is the user's call
    assert len(claude) == 1 + len(collect.CLAUDE_EVENTS)
