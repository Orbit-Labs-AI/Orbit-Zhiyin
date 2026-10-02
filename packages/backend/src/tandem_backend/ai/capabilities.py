"""Zero-token engine probes (version, help flags, login state), cached 24 h in ai_engine."""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import isolation
from .engines import API_MODELS, find_binary, has_flag

TTL_MS = 24 * 3600 * 1000
PROBE_TIMEOUT_S = 3.0
NAMES = {"claude_code": "Claude Code", "codex": "Codex", "api_key": "Anthropic API",
         "fake": "Fake"}
SLOTS = {"claude_code": {"cheap": "haiku", "main": "sonnet"},
         "codex": {"cheap": None, "main": None},
         "api_key": dict(API_MODELS)}
CLAUDE_FLAGS = ("--safe-mode", "--strict-mcp-config", "--max-budget-usd", "--model", "--effort",
                "--settings", "--max-turns", "--json-schema", "--no-session-persistence")
CODEX_FLAGS = ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--output-schema")


def _run(argv: list[str], home: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
                              cwd=isolation.cwd(home), env=isolation.env())
    except (OSError, subprocess.SubprocessError):
        return None


def _version(done: subprocess.CompletedProcess | None) -> str | None:
    if done is None or done.returncode != 0:
        return None
    line = (done.stdout or done.stderr).strip().splitlines()
    return line[0].strip() if line else None


def detect(engine_id: str, home: Path, engine=None) -> dict:
    """Probe one engine without calling a model."""
    info = {"id": engine_id, "name": NAMES.get(engine_id, engine_id), "available": False,
            "path": None, "version": None, "logged_in": None, "flags": [],
            "slots": SLOTS.get(engine_id, {"cheap": None, "main": None}),
            "quota": {"status": "unknown"}, "checked_at": int(time.time() * 1000)}
    static = getattr(engine, "info", None)
    if isinstance(static, dict):
        return {**info, **static}
    if engine_id == "api_key":
        present = bool(os.environ.get("ANTHROPIC_API_KEY"))
        return {**info, "available": present, "logged_in": present or None}
    binary = {"claude_code": "claude", "codex": "codex"}.get(engine_id)
    path = find_binary(binary) if binary else None
    if path is None:
        return info
    info.update(path=path, available=True)
    if engine_id == "claude_code":
        probes = ([path, "--version"], [path, "--help"], [path, "auth", "status", "--json"])
    else:
        probes = ([path, "--version"], [path, "exec", "--help"], [path, "login", "status"])
    with ThreadPoolExecutor(3) as pool:
        version, helped, login = pool.map(lambda argv: _run(argv, home), probes)
    info["version"] = _version(version)
    text = (helped.stdout + helped.stderr) if helped else ""
    wanted = CLAUDE_FLAGS if engine_id == "claude_code" else CODEX_FLAGS
    info["flags"] = [flag for flag in wanted if has_flag(text, flag)]
    if login is not None:
        if engine_id == "claude_code":
            try:
                info["logged_in"] = bool(json.loads(login.stdout).get("loggedIn"))
            except (json.JSONDecodeError, AttributeError):
                info["logged_in"] = None
        else:
            info["logged_in"] = login.returncode == 0
    return info


class Capabilities:
    def __init__(self, appdb, home: Path):
        self.appdb, self.home = appdb, Path(home)

    def get(self, engines: dict, refresh: bool = False) -> dict[str, dict]:
        """``{engine_id: info}`` for the registered engines; probes stale ones in parallel."""
        now = int(time.time() * 1000)
        cached: dict[str, dict] = {}
        if not refresh:
            with self.appdb.read() as db:
                for row in db.execute("SELECT engine, info, checked_at FROM ai_engine"):
                    if row["engine"] in engines and now - row["checked_at"] < TTL_MS:
                        cached[row["engine"]] = json.loads(row["info"])
        stale = [engine_id for engine_id in engines if engine_id not in cached]
        if stale:
            with ThreadPoolExecutor(max(1, len(stale))) as pool:
                fresh = dict(zip(stale, pool.map(
                    lambda e: detect(e, self.home, engines[e]), stale), strict=True))
            with self.appdb.write() as db:
                for engine_id, info in fresh.items():
                    db.execute("INSERT INTO ai_engine VALUES (?, ?, ?) ON CONFLICT(engine) DO "
                               "UPDATE SET info = excluded.info, checked_at = excluded.checked_at",
                               (engine_id, json.dumps(info, ensure_ascii=False), now))
            cached.update(fresh)
        return {engine_id: cached[engine_id] for engine_id in engines}

    def forget(self, engine_id: str) -> None:
        with self.appdb.write() as db:
            db.execute("DELETE FROM ai_engine WHERE engine = ?", (engine_id,))
