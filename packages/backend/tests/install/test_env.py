import sqlite3
import subprocess
import time
from contextlib import contextmanager
from dataclasses import replace

from tandem_backend.install import env as envmod
from tandem_backend.install.env import (
    build_env,
    capabilities,
    environment,
    installed_counts,
    inventory_names,
)

from .conftest import FakeRun


def agent(result, name):
    return next(a for a in result["agents"] if a["agent"] == name)


class Reads:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def read(self):
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        db = sqlite3.connect(self.path)
        try:
            yield db
        finally:
            db.close()


def make_db(path, project_dirs=()):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE inventory_scan (scan_id INTEGER PRIMARY KEY, source_key TEXT, agent TEXT);
        CREATE TABLE inventory_item (scan_id INTEGER, inv_id TEXT, type TEXT, name TEXT, enabled INTEGER);
        CREATE TABLE project (project_id TEXT, key_type TEXT, key TEXT, name TEXT, paths TEXT);
        INSERT INTO inventory_scan VALUES (1,'cc','claude_code'),(2,'cc','claude_code'),(3,'cx','codex');
        INSERT INTO inventory_item VALUES (1,'a','skill','old',1),(2,'b','skill','alpha',1),(2,'c','skill','beta',NULL),
          (2,'d','mcp','gh',0),(2,'e','hook','fmt',1),(3,'f','rule','agents',1);
    """)
    for i, p in enumerate(project_dirs):
        db.execute("INSERT INTO project VALUES (?, 'path', ?, ?, ?)", (f"p{i}", str(p), p.name, f'["{p}"]'))
    db.commit()
    db.close()


def test_detects_agents_by_config_dir_and_binary(env, fake_run, tmp_path):
    result = environment(env, cache_dir=tmp_path / "cache")
    cc = agent(result, "claude_code")
    assert cc["installed"] and cc["detected_via"] == ["config_dir", "binary"]
    assert cc["version"] == "2.1.3" and cc["version_basis"] == "probed"
    assert cc["root"] == "~/.claude" and cc["root_abs"] == str(env.home / ".claude")
    assert cc["capabilities"]["basis"] == "probed" and cc["capabilities"]["hooks"]
    assert cc["dirs"]["skills"] == {"path": str(env.home / ".claude/skills"), "display": "~/.claude/skills",
                                    "exists": True, "count": 1}
    layers = {lay["id"]: lay for lay in cc["layers"]}
    assert layers["mcp_user"]["path"] == str(env.home / ".claude.json") and layers["mcp_user"]["exists"]
    assert layers["managed"]["managed"] and not layers["managed"]["writable"]
    assert layers["user_settings"]["writable"]
    cx = agent(result, "codex")
    assert cx["version"] == "0.80.0" and not cx["capabilities"]["subagents"]
    assert cx["dirs"]["skills"]["path"] == str(env.home / ".codex/skills")
    assert cx["dirs"]["skills"]["alternatives"] == [str(env.home / ".agents/skills")]
    assert {lay["id"] for lay in cx["layers"]} == {"config_toml", "agents_md", "hooks_json"}
    assert len(fake_run.calls) == 2
    # no tandem.db: counts fall back to directory counts
    assert cc["installed_counts"]["skill"] == 1 and cc["counts_basis"] == "files"


def test_claude_config_dir_moves_claude_json_and_profiles(env, tmp_path):
    custom = tmp_path / "alt-claude"
    custom.mkdir()
    (env.home / ".claude-work").mkdir()
    result = environment(replace(env, environ={**env.environ, "CLAUDE_CONFIG_DIR": str(custom)}))
    cc = agent(result, "claude_code")
    assert cc["root_abs"] == str(custom)
    assert {lay["id"]: lay["path"] for lay in cc["layers"]}["mcp_user"] == str(custom / ".claude.json")
    assert cc["profiles"] == [str(env.home / ".claude-work")]


def test_probe_failures_do_not_raise_and_cache_hits(env, tmp_path):
    cache = tmp_path / "cache"
    timeouts = FakeRun(error=subprocess.TimeoutExpired("claude", 3))
    result = environment(replace(env, run=timeouts), cache_dir=cache)
    cc = agent(result, "claude_code")
    assert cc["version"] is None and cc["version_basis"] == "unknown"
    assert cc["capabilities"]["basis"] == "assumed" and cc["capabilities"]["plugins"]
    nonzero = FakeRun(outputs={})
    assert agent(environment(replace(env, run=nonzero), cache_dir=tmp_path / "c2"), "codex")["version"] is None

    counting = FakeRun()
    environment(replace(env, run=counting), cache_dir=cache, refresh=True)
    assert len(counting.calls) == 2
    envmod._memo.clear()
    again = FakeRun()
    result = environment(replace(env, run=again), cache_dir=cache)
    assert again.calls == [] and agent(result, "claude_code")["version"] == "2.1.3"
    (cache / "probe.json").write_text("{broken")
    envmod._memo.clear()
    environment(replace(env, run=again), cache_dir=cache)
    assert len(again.calls) == 2


def test_capabilities_table():
    assert capabilities("claude_code", None) == {**dict.fromkeys(envmod.CAPABILITIES, True), "basis": "assumed"}
    old = capabilities("claude_code", "1.0.10")
    assert old["basis"] == "probed" and not old["hooks"] and old["mcp"]
    assert capabilities("codex", None)["plugins"] is False


def test_installed_counts_and_names(tmp_path):
    path = tmp_path / "tandem.db"
    assert installed_counts(Reads(path), "claude_code") is None
    assert installed_counts(None, "claude_code") is None
    make_db(path)
    reads = Reads(path)
    assert installed_counts(reads, "claude_code") == {"skill": 2, "mcp": 0, "hook": 1, "plugin": 0, "rule": 0,
                                                      "scheduled_task": 0}
    assert installed_counts(reads, "codex")["rule"] == 1
    assert inventory_names(reads, "claude_code", "skill") == {"alpha", "beta"}
    assert inventory_names(reads) == {"alpha", "beta", "gh", "fmt", "agents"}


def test_projects_markers_and_counts(env, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / "AGENTS.md").write_text("x")
    (proj / ".mcp.json").write_text("{}")
    path = tmp_path / "tandem.db"
    make_db(path, [proj, tmp_path / "gone"])
    result = environment(env, reads=Reads(path))
    assert result["projects"] == [{"path": str(proj), "name": "proj", "has_claude_dir": True, "has_claude_md": False,
                                   "has_claude_local_md": False, "has_agents_md": True, "has_mcp_json": True,
                                   "has_codex_dir": False}]
    assert agent(result, "claude_code")["counts_basis"] == "inventory"
    assert environment(env, reads=Reads(path), projects=False)["projects"] == []


def test_missing_and_read_only_agents(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".hermes").mkdir()
    run = FakeRun()
    result = environment(envmod.Env(home=empty, environ={"PATH": ""}, search_dirs=[], run=run))
    cc = agent(result, "claude_code")
    assert not cc["installed"] and cc["detected_via"] == [] and cc["installed_counts"] is None
    hermes = agent(result, "hermes")
    assert hermes["installed"] and hermes["install_support"] == "read_only"
    assert hermes["unsupported_reason"] == "agent_not_supported_v1" and not hermes["capabilities"]["skills"]
    assert run.calls == []


def test_build_env_uses_install_home(tmp_path, monkeypatch):
    built = build_env(environ={"TANDEM_INSTALL_HOME": str(tmp_path)})
    assert built.home == tmp_path


def test_time_budget_and_memo(env, tmp_path):
    cache = tmp_path / "cache"
    environment(env, cache_dir=cache)  # warm the probe cache
    envmod._memo.clear()
    start = time.perf_counter()
    first = environment(env, cache_dir=cache)
    cold = time.perf_counter() - start
    start = time.perf_counter()
    second = environment(env, cache_dir=cache)
    warm = time.perf_counter() - start
    assert first is second
    assert cold < 0.5 and warm < 0.01


def test_projects_ordered_by_recent_session_activity(tmp_path):
    from tandem_backend.install.env import project_paths

    dirs = [tmp_path / n for n in ("old", "busy", "idle")]
    for d in dirs:
        d.mkdir()
    path = tmp_path / "t.db"
    make_db(path, dirs)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE session (session_uid TEXT, project_id TEXT, started_at INTEGER, ended_at INTEGER)")
        db.executemany("INSERT INTO session VALUES (?,?,?,?)",
                       [("s1", "p0", 100, 200), ("s2", "p1", 300, None), ("s3", "p1", 50, 60)])
    assert project_paths(Reads(path)) == [str(dirs[1]), str(dirs[0]), str(dirs[2])]
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE session")
    assert project_paths(Reads(path)) == [str(d) for d in reversed(dirs)]  # no sessions: newest row first


def test_dir_counts_mean_installed_plugins_and_real_skills(env, tmp_path):
    claude = env.home / ".claude"
    plugins = claude / "plugins"
    for d in ("cache", "marketplaces", "repos"):
        (plugins / d).mkdir(parents=True)
    (plugins / "config.json").write_text("{}", "utf-8")
    (plugins / "installed_plugins.json").write_text('{"version": 2, "plugins": {}}', "utf-8")
    (claude / "skills/notes-only").mkdir()  # no SKILL.md: not a skill
    (claude / "skills/README.md").write_text("x", "utf-8")
    target = tmp_path / "linked-skill"
    target.mkdir()
    (target / "SKILL.md").write_text("---\nname: linked\n---\n", "utf-8")
    (claude / "skills/linked").symlink_to(target)
    dirs = agent(environment(env), "claude_code")["dirs"]
    assert dirs["plugins"]["count"] == 0
    assert dirs["skills"]["count"] == 2  # x + linked

    envmod._memo.clear()
    (plugins / "installed_plugins.json").write_text(
        '{"version": 2, "plugins": {"a@m": [{"scope": "user"}], "b@m": [{}, {}]}}', "utf-8")
    assert agent(environment(env), "claude_code")["dirs"]["plugins"]["count"] == 2
