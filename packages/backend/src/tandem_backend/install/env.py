"""Install environment (DT-22): where each local agent keeps its config, and what it can take.

Agent directories are only ``os.stat`` / ``os.scandir``-ed, except for a few small config files:
Claude's ``plugins/installed_plugins.json`` index (so the plugin count means installed plugins) and,
without an inventory scan, the JSON/TOML files holding MCP servers and hooks, parsed for counts. The
``--version`` probes run in a minimal environment (macOS GUI processes get a short PATH, so
binaries are found in fixed candidate dirs), in parallel, and are cached on
``(path, mtime_ns, size)`` for 24 h. A full answer is memoised in process for 2 s.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import tomllib
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

MANAGED_SETTINGS = Path("/Library/Application Support/ClaudeCode/managed-settings.json")
PROBE_TTL = 24 * 3600
FAILED_PROBE_TTL = 600  # a timed-out probe is retried sooner than a good one
MEMO_TTL = 2.0
PROJECT_LIMIT = 30
COUNT_KINDS = ("skill", "mcp", "hook", "plugin", "rule", "scheduled_task")
CAPABILITIES = ("skills", "hooks", "mcp", "plugins", "subagents", "commands", "rules", "permission_rules")

# agent -> (display name, binary name, default root relative to home)
AGENTS = {
    "claude_code": ("Claude Code", "claude", ".claude"),
    "codex": ("Codex", "codex", ".codex"),
    "dsh": ("dsh", "dsh", ".dsh"),
    "pi": ("Pi", "pi", ".pi/agent"),
    "hermes": ("Hermes", "hermes", ".hermes"),
    "opencode": ("OpenCode", "opencode", ".local/share/opencode"),
    "kimi": ("Kimi Code", "kimi", ".kimi-code"),
}
FULL_SUPPORT = {"claude_code", "codex"}
SUPPORTED = {
    "claude_code": set(CAPABILITIES),
    "codex": {"skills", "hooks", "mcp", "commands", "rules", "permission_rules"},
}
# Minimum versions per capability. 待验证：数值取自各 Agent 更新日志的大致时间点，未实测。
MIN_VERSIONS = {
    ("claude_code", "hooks"): "1.0.38",
    ("claude_code", "mcp"): "0.2.0",
    ("claude_code", "commands"): "0.2.0",
    ("claude_code", "subagents"): "1.0.60",
    ("claude_code", "skills"): "2.0.20",
    ("claude_code", "plugins"): "2.0.12",
    ("codex", "mcp"): "0.10.0",
    ("codex", "rules"): "0.10.0",
    ("codex", "commands"): "0.20.0",
    ("codex", "permission_rules"): "0.60.0",
    ("codex", "skills"): "0.60.0",
    ("codex", "hooks"): "0.70.0",
}


@dataclass
class Env:
    """Injectable view of the machine; tests pass a tmp home and a fake ``run``."""

    home: Path
    environ: Mapping[str, str] = field(default_factory=dict)
    search_dirs: list[Path] | None = None
    run: Callable | None = None
    now: Callable[[], float] = time.time


def build_env(home: Path | None = None, environ: Mapping[str, str] | None = None,
              run: Callable | None = None) -> Env:
    environ = dict(os.environ if environ is None else environ)
    if home is None:
        home = Path(environ["TANDEM_INSTALL_HOME"]) if environ.get("TANDEM_INSTALL_HOME") else Path.home()
    return Env(home=Path(home), environ=environ, run=run)


def display(path: Path | str, home: Path) -> str:
    text, base = str(path), str(home)
    if text == base:
        return "~"
    return "~" + text[len(base):] if text.startswith(base + os.sep) else text


# ---- binaries -----------------------------------------------------------------------------

def search_dirs(env: Env) -> list[Path]:
    if env.search_dirs is not None:
        return list(env.search_dirs)
    h = env.home
    dirs = [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), h / ".local/bin", h / ".claude/local",
            h / ".npm-global/bin", h / ".bun/bin", h / ".cargo/bin", h / ".volta/bin", h / ".asdf/shims",
            h / ".local/share/mise/shims"]
    try:
        nodes = [Path(e.path) / "bin" for e in os.scandir(h / ".nvm/versions/node") if e.is_dir()]
        if nodes:
            dirs.append(max(nodes, key=lambda p: _mtime(p)))
    except OSError:
        pass
    dirs += [Path(p) for p in env.environ.get("PATH", "").split(os.pathsep) if p]
    seen, unique = set(), []
    for d in dirs:
        if str(d) not in seen:
            seen.add(str(d))
            unique.append(d)
    return unique


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def find_binary(name: str, env: Env) -> str | None:
    for directory in search_dirs(env):
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def probe_version(binary: str, env: Env, timeout: float = 3.0) -> dict:
    """``<binary> --version`` without a shell; never raises."""
    minimal = {"PATH": os.pathsep.join(str(d) for d in search_dirs(env)), "HOME": str(env.home), "NO_COLOR": "1"}
    run = env.run or subprocess.run
    try:
        done = run([binary, "--version"], env=minimal, capture_output=True, text=True,
                   timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"version": None, "raw": None, "ok": False, "error": "timeout"}
    except OSError as error:
        return {"version": None, "raw": None, "ok": False, "error": type(error).__name__}
    raw = ((done.stdout or "") + (done.stderr or "")).strip()[:200]
    if done.returncode != 0:
        return {"version": None, "raw": raw, "ok": False, "error": f"exit_{done.returncode}"}
    match = re.search(r"\d+\.\d+\.\d+", raw)
    if not match:
        return {"version": None, "raw": raw, "ok": False, "error": "no_version"}
    return {"version": match[0], "raw": raw, "ok": True, "error": None}


def _probe_all(binaries: dict[str, str], env: Env, cache_dir: Path | None, refresh: bool) -> dict[str, dict]:
    cache_file = cache_dir / "probe.json" if cache_dir else None
    cache: dict = {}
    if cache_file and not refresh:
        try:
            cache = json.loads(cache_file.read_text("utf-8"))
            cache = cache if isinstance(cache, dict) else {}
        except (OSError, ValueError):
            cache = {}
    now, results, pending = env.now(), {}, {}
    for agent, binary in binaries.items():
        try:
            st = os.stat(binary)
        except OSError:
            continue
        key = f"{binary}|{st.st_mtime_ns}|{st.st_size}"
        hit = cache.get(key)
        ttl = PROBE_TTL if isinstance(hit, dict) and hit.get("ok") else FAILED_PROBE_TTL
        if isinstance(hit, dict) and now - hit.get("at", 0) < ttl:
            results[agent] = hit
        else:
            pending[agent] = key
    if pending:
        with ThreadPoolExecutor(max_workers=4) as pool:
            probed = dict(zip(pending, pool.map(lambda a: probe_version(binaries[a], env), pending), strict=True))
        for agent, result in probed.items():
            results[agent] = cache[pending[agent]] = {**result, "at": now}
        if cache_file:
            _atomic_json(cache_file, cache)
    return results


def _atomic_json(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(payload), "utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


# ---- capabilities -------------------------------------------------------------------------

def _vtuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version)[:3])


def capabilities(agent: str, version: str | None) -> dict:
    supported = SUPPORTED.get(agent, set())
    if not version:
        return {**{c: c in supported for c in CAPABILITIES}, "basis": "assumed"}
    caps = {}
    for c in CAPABILITIES:
        minimum = MIN_VERSIONS.get((agent, c))
        caps[c] = c in supported and (minimum is None or _vtuple(version) >= _vtuple(minimum))
    return {**caps, "basis": "probed"}


# ---- filesystem facts ---------------------------------------------------------------------

def _writable(path: Path) -> bool:
    probe = path
    while not probe.exists():
        if probe.parent == probe:
            return False
        probe = probe.parent
    return os.access(probe, os.W_OK)


def layer(layer_id: str, path: Path, home: Path, managed: bool = False) -> dict:
    try:
        st = path.stat()
        exists, size, mtime = True, st.st_size, int(st.st_mtime * 1000)
    except OSError:
        exists, size, mtime = False, None, None
    return {"id": layer_id, "path": str(path), "display": display(path, home), "exists": exists,
            "size": size, "mtime": mtime, "writable": (not managed) and _writable(path), "managed": managed}


def _entries(path: Path) -> int:
    return sum(1 for e in os.scandir(path) if not e.name.startswith("."))


def _skills(path: Path) -> int:
    """Skill folders only: entries (symlinks followed) holding a ``SKILL.md``."""
    return sum(1 for e in os.scandir(path) if not e.name.startswith(".") and (Path(e.path) / "SKILL.md").is_file())


def _plugins(path: Path) -> int:
    """Installed plugins per ``installed_plugins.json``; cache/marketplace folders are not plugins."""
    try:
        doc = json.loads((path / "installed_plugins.json").read_text("utf-8"))
    except (OSError, ValueError):
        return 0
    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    return len(plugins) if isinstance(plugins, dict) else 0


def dir_info(path: Path | None, home: Path, counter: Callable[[Path], int] = _entries) -> dict | None:
    if path is None:
        return None
    exists = path.is_dir()
    try:
        count = counter(path) if exists else 0
    except OSError:
        count = 0
    return {"path": str(path), "display": display(path, home), "exists": exists, "count": count}


def claude_json_path(env: Env) -> Path:
    custom = env.environ.get("CLAUDE_CONFIG_DIR")
    return Path(custom).expanduser() / ".claude.json" if custom else env.home / ".claude.json"


def agent_root(agent: str, env: Env) -> Path:
    variable = {"claude_code": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME"}.get(agent)
    if variable and env.environ.get(variable):
        return Path(env.environ[variable]).expanduser()
    if agent == "opencode" and env.environ.get("XDG_DATA_HOME"):
        return Path(env.environ["XDG_DATA_HOME"]) / "opencode"
    return env.home / AGENTS[agent][2]


def _claude(env: Env, root: Path) -> tuple[list, dict, list]:
    h = env.home
    layers = [layer("user_settings", root / "settings.json", h), layer("local_settings", root / "settings.local.json", h),
              layer("claude_md", root / "CLAUDE.md", h), layer("mcp_user", claude_json_path(env), h),
              layer("managed", MANAGED_SETTINGS, h, managed=True)]
    counters = {"skills": _skills, "plugins": _plugins}
    dirs = {name: dir_info(root / name, h, counters.get(name, _entries))
            for name in ("skills", "agents", "commands", "plugins", "hooks", "rules")}
    dirs["prompts"] = None
    profiles = []
    try:
        profiles = sorted(str(Path(e.path)) for e in os.scandir(h) if e.name.startswith(".claude-") and e.is_dir())
    except OSError:
        pass
    return layers, dirs, profiles


def _codex(env: Env, root: Path) -> tuple[list, dict, list]:
    h = env.home
    layers = [layer("config_toml", root / "config.toml", h), layer("agents_md", root / "AGENTS.md", h),
              layer("hooks_json", root / "hooks.json", h)]
    # 待验证 V6：Codex 的用户 skills 目录在 ~/.codex/skills 与 ~/.agents/skills 之间并不确定。
    options = [root / "skills", h / ".agents/skills"]
    chosen = next((p for p in options if p.is_dir()), options[1])
    skills = dir_info(chosen, h, _skills)
    skills["alternatives"] = [str(p) for p in options if p != chosen]
    dirs = {"skills": skills, "agents": None, "commands": None, "plugins": None,
            "hooks": dir_info(root / "hooks", h), "rules": dir_info(root / "rules", h),
            "prompts": dir_info(root / "prompts", h)}
    return layers, dirs, []


def _other_root(agent: str, env: Env) -> Path:
    try:
        from tandem_data.discovery import candidates

        for c in candidates(env.home):
            if c["agent"] == agent:
                return Path(c["root"])
    except Exception:  # noqa: BLE001 - discovery is a best-effort hint
        pass
    return agent_root(agent, env)


# ---- tandem.db reads ----------------------------------------------------------------------

LATEST_COUNTS = """
SELECT s.agent, i.type, COUNT(*) FROM inventory_item i JOIN inventory_scan s USING(scan_id)
WHERE s.scan_id IN (SELECT MAX(scan_id) FROM inventory_scan GROUP BY source_key)
  AND COALESCE(i.enabled, 1) = 1 GROUP BY 1, 2"""


def _query(reads, sql: str, params=()) -> list | None:
    if reads is None:
        return None
    try:
        with reads.read() as db:
            return [tuple(r) for r in db.execute(sql, params).fetchall()]
    except Exception:  # noqa: BLE001 - missing db/table/projection all mean "unknown"
        return None


def all_installed_counts(reads) -> dict[str, dict] | None:
    rows = _query(reads, LATEST_COUNTS)
    if not rows:  # no db, or a db whose inventory was never scanned: counts are unknown, not zero
        return None
    counts: dict[str, dict] = {}
    for agent, kind, n in rows:
        counts.setdefault(agent, dict.fromkeys(COUNT_KINDS, 0))[kind] = n
    return counts


def installed_counts(reads, agent: str) -> dict | None:
    counts = all_installed_counts(reads)
    if counts is None:
        return None
    return counts.get(agent, dict.fromkeys(COUNT_KINDS, 0))


def inventory_names(reads, agent: str | None = None, kind: str | None = None) -> set[str]:
    sql = ("SELECT i.name FROM inventory_item i JOIN inventory_scan s USING(scan_id) WHERE s.scan_id IN "
           "(SELECT MAX(scan_id) FROM inventory_scan GROUP BY source_key) AND (?1 IS NULL OR s.agent = ?1) "
           "AND (?2 IS NULL OR i.type = ?2)")
    return {r[0] for r in _query(reads, sql, (agent, kind)) or []}


def _load(path: Path, parse=json.loads):
    try:
        doc = parse(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _size(value) -> int:
    return len(value) if isinstance(value, dict | list) else 0


def file_counts(agent: str, env: Env, root: Path, dirs: dict) -> dict:
    """Cheap counts from the agent's own config files when no inventory scan exists."""
    counts = {**dict.fromkeys(COUNT_KINDS, 0), "skill": (dirs.get("skills") or {}).get("count", 0)}
    if agent == "claude_code":
        hooks = _load(root / "settings.json").get("hooks")
        counts["hook"] = sum(_size(g.get("hooks")) for groups in (hooks.values() if isinstance(hooks, dict) else ())
                             if isinstance(groups, list) for g in groups if isinstance(g, dict))
        counts["mcp"] = _size(_load(claude_json_path(env)).get("mcpServers"))
        counts["plugin"] = _size(_load(root / "plugins/installed_plugins.json").get("plugins"))
    elif agent == "codex":
        counts["mcp"] = _size(_load(root / "config.toml", tomllib.loads).get("mcp_servers"))
    return counts


# Most recent session activity first; projects without sessions follow, newest row first.
RECENT_PROJECTS = (
    "SELECT p.key_type, p.key, p.paths FROM project p LEFT JOIN (SELECT project_id, "
    "MAX(COALESCE(ended_at, started_at)) AS last FROM session WHERE project_id IS NOT NULL "
    "GROUP BY project_id) s USING(project_id) ORDER BY s.last IS NULL, s.last DESC, p.rowid DESC LIMIT 500")


def project_paths(reads, limit: int = PROJECT_LIMIT) -> list[str]:
    rows = _query(reads, RECENT_PROJECTS) or _query(
        reads, "SELECT key_type, key, paths FROM project ORDER BY rowid DESC LIMIT 500") or []
    found: list[str] = []
    for key_type, key, paths in rows:
        try:
            options = list(json.loads(paths or "[]"))
        except ValueError:
            options = []
        if key_type in ("git_root", "path"):
            options.append(key)
        for p in options:
            if isinstance(p, str) and p.startswith("/") and p not in found and os.path.isdir(p):
                found.append(p)
                break
        if len(found) >= limit:
            break
    return found


def project_info(path: str) -> dict:
    p = Path(path)
    return {"path": path, "name": p.name, "has_claude_dir": (p / ".claude").is_dir(),
            "has_claude_md": (p / "CLAUDE.md").is_file(), "has_claude_local_md": (p / "CLAUDE.local.md").is_file(),
            "has_agents_md": (p / "AGENTS.md").is_file(), "has_mcp_json": (p / ".mcp.json").is_file(),
            "has_codex_dir": (p / ".codex").is_dir()}


# ---- entry point --------------------------------------------------------------------------

_memo: dict = {}
_memo_lock = threading.Lock()


def invalidate() -> None:
    """Drop the short memo so the next call sees files an apply/revert just changed."""
    with _memo_lock:
        _memo.clear()


def environment(env: Env | None = None, *, reads=None, cache_dir: Path | None = None,
                projects: bool = True, refresh: bool = False) -> dict:
    env = env or build_env()
    key = (str(env.home), id(env), id(reads), str(cache_dir), projects)
    now = env.now()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and not refresh and now - hit[0] < MEMO_TTL:
            return hit[1]
    result = _environment(env, reads, cache_dir, projects, refresh)
    with _memo_lock:
        _memo.clear()  # one live entry is enough; avoids unbounded growth across envs
        _memo[key] = (now, result)
    return result


def _environment(env: Env, reads, cache_dir: Path | None, projects: bool, refresh: bool) -> dict:
    h = env.home
    binaries = {a: b for a in AGENTS if (b := find_binary(AGENTS[a][1], env))}
    probes = _probe_all(binaries, env, cache_dir, refresh)
    counts = all_installed_counts(reads)
    agents = []
    for agent, (name, _, _) in AGENTS.items():
        if agent == "claude_code":
            root = agent_root(agent, env)
            layers, dirs, profiles = _claude(env, root)
        elif agent == "codex":
            root = agent_root(agent, env)
            layers, dirs, profiles = _codex(env, root)
        else:
            root = _other_root(agent, env)
            layers, dirs, profiles = [], {}, []
        has_dir = root.is_dir()
        binary = binaries.get(agent)
        version = (probes.get(agent) or {}).get("version")
        full = agent in FULL_SUPPORT
        if counts is not None:
            agent_counts = counts.get(agent, dict.fromkeys(COUNT_KINDS, 0))
        elif full and has_dir:  # no inventory scan yet: fall back to cheap config-file counts
            agent_counts = file_counts(agent, env, root, dirs)
        else:
            agent_counts = None
        caps = capabilities(agent, version) if full else {**dict.fromkeys(CAPABILITIES, False), "basis": "assumed"}
        agents.append({
            "agent": agent, "name": name, "installed": has_dir or binary is not None,
            "detected_via": [v for v, ok in (("config_dir", has_dir), ("binary", binary)) if ok],
            "binary": binary, "version": version, "version_basis": "probed" if version else "unknown",
            "root": display(root, h), "root_abs": str(root), "profiles": profiles,
            "install_support": "full" if full else "read_only", "capabilities": caps,
            "layers": layers, "dirs": dirs, "installed_counts": agent_counts,
            "counts_basis": "inventory" if counts is not None else ("files" if agent_counts else "unknown"),
            "unsupported_reason": None if full else "agent_not_supported_v1",
        })
    project_list = [project_info(p) for p in project_paths(reads)] if projects else []
    return {"home": str(h), "platform": "darwin", "scanned_at": int(env.now() * 1000),
            "agents": agents, "projects": project_list}
