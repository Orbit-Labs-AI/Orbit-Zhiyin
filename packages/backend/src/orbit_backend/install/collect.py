"""Orbit's own revocable collection (IN-07 / DT-16) as an ordinary install.

``plan({"type": "collect"})`` builds one ``collect`` spec; its targets go through the same
preview → apply → revert path as any other install, so undo restores the agent files byte
for byte. What it lands:

* Claude Code: ``orbit_collect.py`` (package data) under ``~/.claude/hooks/orbit/``; read-only
  hooks that append one JSON line per event to ``$ORBIT_HOME/hooks/events.jsonl``; a
  status line wrapper that still runs the user's own status line; a ``cleanupPeriodDays``
  guard so transcripts are not pruned before ingest.
* Codex: the same script as the ``notify`` program, a root-level block at the top of
  ``config.toml``. Refused when the user already has a ``notify`` program.

The realtime reader (``realtime/hooks.py``) turns the events into approval waits and
context pressure.
"""

from __future__ import annotations

import json
import shlex
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

from . import store
from .env import display
from .targets import check_path, reason_text, render_hook_entry

SPEC_ID = "orbit-collect"
SCRIPT_NAME = "orbit_collect.py"
EVENTS_REL = "hooks/events.jsonl"
GUARD_DAYS = 365  # 待验证: keep transcripts at least this long so ingest never misses them
# (event, matcher). PostToolUse / UserPromptSubmit only close an approval wait.
CLAUDE_EVENTS = (("Notification", None), ("PermissionRequest", "*"), ("PostToolUse", "*"),
                 ("UserPromptSubmit", None), ("Stop", None), ("PreCompact", None))


def script_text() -> str:
    return files("orbit_backend.install").joinpath("assets", SCRIPT_NAME).read_text("utf-8")


def events_path(home: Path | str) -> Path:
    return Path(home) / EVENTS_REL


def spec(home: Path | str, python: str | None = None) -> dict:
    return {"kind": "collect", "id": SPEC_ID, "title": "Orbit 实时采集",
            "payload": {"events_path": str(events_path(home)), "python": python or sys.executable or "python3"},
            "source": {"type": "collect", "id": SPEC_ID, "template": None, "license": None, "sha256": None}}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_toml(path: Path) -> dict | None:
    try:
        return tomllib.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _settings_patch(settings: dict, status_cmd: str) -> tuple[dict, list[str]]:
    """statusLine wrapper + cleanup guard, given the current settings.json."""
    patch, notes = {}, []
    current = settings.get("statusLine")
    if isinstance(current, dict) and SCRIPT_NAME in str(current.get("command") or ""):
        pass  # already wrapped
    elif current is None:
        patch["statusLine"] = {"type": "command", "command": status_cmd}
    elif isinstance(current, dict) and current.get("type") == "command" and isinstance(current.get("command"), str):
        wrapped = f"{status_cmd} --wrap {shlex.quote(current['command'])}"
        patch["statusLine"] = {**current, "command": wrapped}
    else:
        notes.append("statusline_not_wrappable")
    days = settings.get("cleanupPeriodDays")
    if days is None or (isinstance(days, int) and 0 < days < GUARD_DAYS):
        patch["cleanupPeriodDays"] = GUARD_DAYS
    elif days == 0:
        notes.append("cleanup_disabled_by_user")  # 0 turns transcripts off: respect it
    return patch, notes


def resolve_targets(spec: dict, env_info: dict, *, env=None) -> list[dict]:
    payload = spec["payload"]
    events, python = payload["events_path"], payload.get("python") or "python3"
    home = Path(env_info.get("home") or (env.home if env else Path.home()))
    infos = {a["agent"]: a for a in env_info.get("agents", [])}
    out: list[dict] = []
    script = script_text()

    def add(agent: str, path: str, action: str, content, *, pointer=None, write_mode="add", note=None,
            **extra) -> None:
        reason = check_path(path, env, env_info, None)
        row = {"idx": len(out), "agent": agent, "kind": "collect", "path": path}
        if reason:
            out.append({**row, "mappable": False, "reason": f"path_policy:{reason}",
                        "reason_text": reason_text(f"path_policy:{reason}")})
            return
        out.append({**row, "scope": "user", "display": display(path, home), "action": action, "pointer": pointer,
                    "content": content, "write_mode": write_mode if action == "merge_json" else "set",
                    "file_mode": None, "block_id": "orbit:collect" if action == "toml_block" else None,
                    "requires_trust": False, "mappable": True, "reason": None, "note": note,
                    "group": f"collect:{agent}", "shared_layer": False, **extra})

    for agent in spec.get("agents") or []:
        info = infos.get(agent)
        lander = LANDERS.get(agent)
        if not info or info.get("install_support") != "full":
            reason = (info or {}).get("unsupported_reason") or "agent_not_supported_v1"
            out.append({"idx": len(out), "agent": agent, "kind": "collect", "mappable": False,
                        "reason": reason, "reason_text": reason_text(reason)})
            continue
        if lander is None:  # installable agent, but no collector of ours exists for it yet
            out.append({"idx": len(out), "agent": agent, "kind": "collect", "mappable": False,
                        "reason": "collect_not_available", "reason_text": reason_text("collect_not_available")})
            continue
        root = Path(info["root_abs"])
        script_path = str(root / "hooks" / "orbit" / SCRIPT_NAME)
        argv = [python, script_path]
        lander(add, out, agent, root, script, script_path, argv, events)
    return out


def _land_claude(add, out, agent, root, script, script_path, argv, events) -> None:
    base = " ".join(shlex.quote(a) for a in argv)
    add(agent, script_path, "create_file", script, file_mode=0o755)
    hook_cmd = f"{base} hook --agent claude_code --out {shlex.quote(events)}"
    for event, matcher in CLAUDE_EVENTS:
        add(agent, str(root / "settings.json"), "merge_json",
            render_hook_entry({"matcher": matcher}, hook_cmd), pointer=f"/hooks/{event}")
    patch, notes = _settings_patch(_read_json(root / "settings.json"),
                                   f"{base} statusline --agent claude_code --out {shlex.quote(events)}")
    if patch:
        add(agent, str(root / "settings.json"), "merge_json", patch, pointer="", write_mode="set",
            note=",".join(notes) or None)


def _land_codex(add, out, agent, root, script, script_path, argv, events) -> None:
    config = _read_toml(root / "config.toml")
    if config is None or "notify" in config:
        reason = "codex_config_unparsable" if config is None else "codex_notify_in_use"
        out.append({"idx": len(out), "agent": agent, "kind": "collect", "mappable": False,
                    "path": str(root / "config.toml"), "reason": reason, "reason_text": reason_text(reason)})
        return
    add(agent, script_path, "create_file", script, file_mode=0o755)
    notify = [*argv, "notify", "--agent", "codex", "--out", events]
    body = "notify = [" + ", ".join(json.dumps(a, ensure_ascii=False) for a in notify) + "]"
    add(agent, str(root / "config.toml"), "toml_block", body, position="top")


# Agents Orbit can land its collector in (the script's ``--agent`` modes). Every other agent gets
# an unmappable row: its own unsupported_reason, or collect_not_available when it is installable.
LANDERS = {"claude_code": _land_claude, "codex": _land_codex}


def status(service) -> dict:
    """Whether collection is installed and how much it has written."""
    active = store.find_active(service.appdb, "collect", SPEC_ID)
    path = events_path(service.home)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {"installed": active is not None, "install_id": active and active["install_id"],
            "state": active and active["state"], "events_path": str(path), "events_bytes": size}
