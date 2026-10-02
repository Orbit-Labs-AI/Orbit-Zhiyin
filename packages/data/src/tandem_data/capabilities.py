"""DT-22 source version and capability matrix (offline, cached for 24 h in the data home).

The static matrix records what each Agent CLI supports, with the evidence used. The
dynamic part is read from the projection: the latest ``harness_version`` per source and
what was actually observed (MCP / skill tool calls, subagent sessions, hook events).
Nothing here touches the network or Agent directories.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tandem_data.store import readonly_connection

CACHE_TTL_MS = 24 * 3600 * 1000
CACHE_FILE = "cache/capabilities.json"
CAPABILITY_VERSION = "1"
FEATURES = ("hooks", "skills", "mcp", "subagents", "headless")
# Values: supported | partial | unsupported | unknown.
MATRIX: dict[str, dict] = {
    "claude_code": {
        "hooks": "supported",
        "skills": "supported",
        "mcp": "supported",
        "subagents": "supported",
        "headless": "supported",
        "evidence": "Claude Code settings hooks, SKILL.md, mcpServers, Task subagents, `claude -p`",
    },
    "codex": {
        "hooks": "partial",
        "skills": "supported",
        "mcp": "supported",
        "subagents": "partial",
        "headless": "supported",
        "evidence": "third_party/codex: hooks in codex-rs/core, SKILL.md loader, mcp_servers, spawn_agent (experimental), `codex exec`",
    },
    "opencode": {
        "hooks": "partial",
        "skills": "supported",
        "mcp": "supported",
        "subagents": "supported",
        "headless": "supported",
        "evidence": "third_party/opencode: plugin events as hooks, SKILL.md, mcp config, task subagents, `opencode run`",
    },
    "pi": {
        "hooks": "partial",
        "skills": "supported",
        "mcp": "partial",
        "subagents": "partial",
        "headless": "supported",
        "evidence": "third_party/pi: extension events, SKILL.md, MCP and subagents only via extensions, `pi -p`",
    },
    "hermes": {
        "hooks": "supported",
        "skills": "supported",
        "mcp": "supported",
        "subagents": "supported",
        "headless": "supported",
        "evidence": "third_party/hermes-agent: hooks, skills, mcp_servers, delegate_task, `hermes -z`",
    },
    "dsh": {
        "hooks": "supported",
        "skills": "supported",
        "mcp": "supported",
        "subagents": "supported",
        "headless": "unknown",
        "evidence": "third_party/deepseek-harness: hook, SKILL.md, MCP and subagent modules; headless entry not confirmed",
    },
    "kimi": {
        "hooks": "unknown",
        "skills": "unknown",
        "mcp": "unknown",
        "subagents": "unknown",
        "headless": "unknown",
        "evidence": "Kimi CLI source is not vendored; capabilities are not confirmed offline",
    },
}


def capabilities(home: str | Path, *, refresh: bool = False, now_ms: int | None = None) -> dict:
    """Return the capability report, reusing ``home/cache/capabilities.json`` within 24 h."""
    home = Path(home).expanduser()
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    db_path = home / "tandem.db"
    fingerprint = _fingerprint(db_path)
    cache_path = home / CACHE_FILE
    if not refresh:
        cached = _read_cache(cache_path)
        if (
            cached
            and cached.get("fingerprint") == fingerprint
            and 0 <= now_ms - cached.get("generated_at", -CACHE_TTL_MS) < CACHE_TTL_MS
        ):
            return {**cached, "cache": "hit"}
    report = {
        "version": CAPABILITY_VERSION,
        "generated_at": now_ms,
        "fingerprint": fingerprint,
        "features": list(FEATURES),
        "agents": {agent: dict(values) for agent, values in MATRIX.items()},
        "sources": _sources(db_path) if db_path.is_file() else [],
    }
    _write_cache(home, cache_path, report)
    return {**report, "cache": "miss"}


def _fingerprint(db_path: Path) -> str:
    if not db_path.is_file():
        return "empty"
    with readonly_connection(db_path) as db:
        run = db.execute("SELECT MAX(run_id) FROM projection_run").fetchone()[0]
        sources = db.execute("SELECT COUNT(*), MAX(discovered_at) FROM source").fetchone()
        inventory = _optional(db, "SELECT MAX(scan_id) FROM inventory_scan")
    return f"run={run};sources={sources[0]}:{sources[1]};inventory={inventory}"


def _optional(db, sql):
    try:
        return db.execute(sql).fetchone()[0]
    except Exception:  # table absent in an older/foreign layout
        return None


def _sources(db_path: Path) -> list[dict]:
    with readonly_connection(db_path) as db:
        rows = db.execute(
            "SELECT source_id, agent, label, enabled FROM source ORDER BY agent, source_id"
        ).fetchall()
        result = []
        for row in rows:
            latest = db.execute(
                "SELECT harness_version, started_at FROM session WHERE source_id=? "
                "AND harness_version IS NOT NULL ORDER BY started_at DESC, session_uid DESC LIMIT 1",
                (row["source_id"],),
            ).fetchone()
            sessions = db.execute(
                "SELECT COUNT(*) AS n, SUM(kind='subagent') AS subagents, MAX(started_at) AS last "
                "FROM session WHERE source_id=?",
                (row["source_id"],),
            ).fetchone()
            calls = db.execute(
                "SELECT SUM(t.mcp_server IS NOT NULL) AS mcp, SUM(t.skill IS NOT NULL) AS skills "
                "FROM tool_call t JOIN session s USING(session_uid) WHERE s.source_id=?",
                (row["source_id"],),
            ).fetchone()
            hooks = db.execute(
                "SELECT COUNT(*) FROM event e JOIN session s USING(session_uid) "
                "WHERE s.source_id=? AND e.actor='hook'",
                (row["source_id"],),
            ).fetchone()[0]
            versions = [
                item[0]
                for item in db.execute(
                    "SELECT DISTINCT harness_version FROM session WHERE source_id=? "
                    "AND harness_version IS NOT NULL ORDER BY harness_version",
                    (row["source_id"],),
                )
            ]
            result.append(
                {
                    "source_id": row["source_id"],
                    "agent": row["agent"],
                    "label": row["label"],
                    "enabled": bool(row["enabled"]),
                    "harness_version": latest["harness_version"] if latest else None,
                    "harness_versions": versions,
                    "sessions": sessions["n"],
                    "last_session_at": sessions["last"],
                    "observed": {
                        "hooks": hooks,
                        "skills": calls["skills"] or 0,
                        "mcp": calls["mcp"] or 0,
                        "subagents": sessions["subagents"] or 0,
                    },
                    "matrix": dict(MATRIX.get(row["agent"], {f: "unknown" for f in FEATURES})),
                }
            )
    return result


def _read_cache(path: Path) -> dict | None:
    try:
        if path.is_symlink():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            data if isinstance(data, dict) and data.get("version") == CAPABILITY_VERSION else None
        )
    except (OSError, ValueError):
        return None


def _write_cache(home: Path, path: Path, report: dict) -> None:
    if not home.is_dir():
        return  # never create a data home just to cache
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(home.resolve()):
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True)
    os.replace(temporary, path)
