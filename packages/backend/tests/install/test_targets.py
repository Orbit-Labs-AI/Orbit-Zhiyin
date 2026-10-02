import os
import tomllib

import pytest

from tandem_backend.install.env import environment
from tandem_backend.install.targets import (
    REASON_TEXT,
    TABLE,
    PlanError,
    check_path,
    lookup,
    resolve_targets,
    safe_name,
    safe_rel,
)

PAYLOADS = {
    "permission_rule": {"allow": ["git status", "git diff"]},
    "rule": {"text": "Prefer small commits.", "heading": "Commits"},
    "skill": {"name": "demo", "files": [{"rel": "SKILL.md", "text": "# demo"}, {"rel": "ref/a.md", "text": "a"}]},
    "hook": {"event": "PreToolUse", "matcher": "Bash", "command": "echo hi", "timeout": 5},
    "mcp": {"name": "gh", "transport": "stdio", "command": "npx", "args": ["-y", "gh-mcp"], "env": {"TOKEN": "${GH}"}},
    "plugin": {"plugin": "fmt", "marketplace": "acme", "marketplace_source": {"source": "github", "repo": "acme/mk"}},
    "subagent": {"name": "reviewer", "text": "You review."},
    "command": {"name": "ship", "text": "Ship it."},
    "setting": {"settings": {"model": "opus"}},
}


@pytest.fixture
def info(env):
    return environment(env)


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


def spec(kind, agents=("claude_code",), scope="user", project=None, payload=None, id_="demo"):
    return {"kind": kind, "id": id_, "title": kind, "agents": list(agents), "scope": scope,
            "project_path": str(project) if project else None, "payload": payload or PAYLOADS[kind],
            "source": {"type": "spec"}}


# (kind, agent, scope) -> (path relative to home or project, action, pointer, mappable, requires_trust)
GRID = {
    ("permission_rule", "claude_code", "user"): ("H/.claude/settings.json", "merge_json", "/permissions/allow"),
    ("permission_rule", "claude_code", "project"): ("P/.claude/settings.local.json", "merge_json", "/permissions/allow"),
    ("rule", "claude_code", "user"): ("H/.claude/CLAUDE.md", "md_block", None),
    ("rule", "claude_code", "project"): ("P/CLAUDE.md", "md_block", None),
    ("skill", "claude_code", "user"): ("H/.claude/skills/demo/SKILL.md", "create_file", None),
    ("skill", "claude_code", "project"): ("P/.claude/skills/demo/SKILL.md", "create_file", None),
    ("hook", "claude_code", "user"): ("H/.claude/settings.json", "merge_json", "/hooks/PreToolUse"),
    ("hook", "claude_code", "project"): ("P/.claude/settings.local.json", "merge_json", "/hooks/PreToolUse"),
    ("mcp", "claude_code", "user"): ("H/.claude.json", "merge_json", "/mcpServers/gh"),
    ("mcp", "claude_code", "project"): ("H/.claude.json", "merge_json", "/projects/{P}/mcpServers/gh"),
    ("plugin", "claude_code", "user"): ("H/.claude/settings.json", "merge_json", "/enabledPlugins"),
    ("plugin", "claude_code", "project"): ("P/.claude/settings.local.json", "merge_json", "/enabledPlugins"),
    ("subagent", "claude_code", "user"): ("H/.claude/agents/reviewer.md", "create_file", None),
    ("subagent", "claude_code", "project"): ("P/.claude/agents/reviewer.md", "create_file", None),
    ("command", "claude_code", "user"): ("H/.claude/commands/ship.md", "create_file", None),
    ("command", "claude_code", "project"): ("P/.claude/commands/ship.md", "create_file", None),
    ("setting", "claude_code", "user"): ("H/.claude/settings.json", "merge_json", ""),
    ("setting", "claude_code", "project"): ("P/.claude/settings.local.json", "merge_json", ""),
    ("permission_rule", "codex", "user"): ("H/.codex/rules/tandem-demo.rules", "create_file", None),
    ("permission_rule", "codex", "project"): "codex_project_rules_unsupported_v1",
    ("rule", "codex", "user"): ("H/.codex/AGENTS.md", "md_block", None),
    ("rule", "codex", "project"): ("P/AGENTS.md", "md_block", None),
    ("skill", "codex", "user"): ("H/.codex/skills/demo/SKILL.md", "create_file", None),
    ("skill", "codex", "project"): "codex_project_skills_unsupported_v1",
    ("hook", "codex", "user"): ("H/.codex/hooks.json", "merge_json", "/hooks/PreToolUse"),
    ("hook", "codex", "project"): "codex_project_hooks_unsupported_v1",
    ("mcp", "codex", "user"): ("H/.codex/config.toml", "toml_block", None),
    ("mcp", "codex", "project"): "codex_project_mcp_unsupported_v1",
    ("plugin", "codex", "user"): "codex_plugin_install_unsupported_v1",
    ("plugin", "codex", "project"): "codex_plugin_install_unsupported_v1",
    ("subagent", "codex", "user"): "codex_has_no_subagent_files",
    ("subagent", "codex", "project"): "codex_has_no_subagent_files",
    ("command", "codex", "user"): ("H/.codex/prompts/ship.md", "create_file", None),
    ("command", "codex", "project"): "codex_project_prompts_unsupported_v1",
    ("setting", "codex", "user"): "codex_settings_unsupported_v1",
    ("setting", "codex", "project"): "codex_settings_unsupported_v1",
}


@pytest.mark.parametrize("key", sorted(GRID))
def test_landing_grid(key, env, info, project):
    kind, agent, scope = key
    expected = GRID[key]
    assert lookup(kind, agent, scope) is TABLE[key]
    targets = resolve_targets(spec(kind, [agent], scope, project if scope == "project" else None), info, env=env)
    first = targets[0]
    if isinstance(expected, str):
        assert first == {"idx": 0, "agent": agent, "kind": kind, "mappable": False, "reason": expected,
                         "reason_text": REASON_TEXT[expected]}
        return
    path, action, pointer = expected
    if kind == "hook":
        first = targets[-1]  # no script: only the settings target
    want = path.replace("H/", f"{env.home}/").replace("P/", f"{project}/")
    assert first["path"] == want and first["action"] == action and first["mappable"]
    if pointer is not None:
        token = str(project).replace("~", "~0").replace("/", "~1")
        assert first["pointer"] == pointer.replace("{P}", token)
    assert first["requires_trust"] == (kind == "hook" and agent == "codex")
    assert [t["idx"] for t in targets] == list(range(len(targets)))
    if action in ("md_block", "toml_block"):
        assert first["block_id"] == "tandem:demo"
    if scope == "project" and want.startswith(str(project)):
        assert first["shared_layer"] == ("settings.local.json" not in want)
        assert first["scope"] == ("local" if "settings.local.json" in want else "project")


def test_rendered_contents(env, info):
    claude, codex = (resolve_targets(spec(k, ["claude_code", "codex"]), info, env=env) for k in ("permission_rule", "rule"))
    assert claude[0]["content"] == ["Bash(git status:*)", "Bash(git diff:*)"]
    assert claude[1]["content"].splitlines() == ['prefix_rule(pattern=["git","status"], decision="allow")',
                                                 'prefix_rule(pattern=["git","diff"], decision="allow")']
    assert claude[1]["note"] == "语法待验证 V6"
    assert codex[0]["content"] == "## Commits\n\nPrefer small commits."
    plugin = resolve_targets(spec("plugin"), info, env=env)
    assert [t["pointer"] for t in plugin] == ["/enabledPlugins", "/extraKnownMarketplaces"]
    assert plugin[0]["content"] == {"fmt@acme": True}
    assert plugin[1]["content"] == {"acme": {"source": {"source": "github", "repo": "acme/mk"}}}
    assert {t["group"] for t in plugin} == {"plugin:demo"}
    bare = resolve_targets(spec("plugin", payload={"plugin": "fmt", "marketplace": "acme"}), info, env=env)
    assert len(bare) == 1 and bare[0]["note"] == "marketplace_must_exist"
    setting = resolve_targets(spec("setting"), info, env=env)[0]
    assert setting["write_mode"] == "set" and setting["content"] == {"model": "opus"}


def test_skill_files_group_and_binary(env, info):
    payload = {"name": "demo", "files": [{"rel": "SKILL.md", "text": "x"}, {"rel": "img.png", "text": "\x00\x01"},
                                         {"rel": "docs/b.md", "text": "b"}]}
    targets = resolve_targets(spec("skill", payload=payload), info, env=env)
    assert [t.get("group") for t in targets] == ["skill:demo"] * 3
    assert targets[1]["mappable"] is False and targets[1]["reason"] == "skipped_binary"
    assert targets[2]["path"] == f"{env.home}/.claude/skills/demo/docs/b.md"
    with pytest.raises(PlanError):
        resolve_targets(spec("skill", payload={"name": "demo", "files": [{"rel": "/etc/x", "text": "x"}]}), info)
    with pytest.raises(PlanError):
        resolve_targets(spec("skill", payload={"name": "demo", "files": [{"rel": "a/../../x", "text": "x"}]}), info)


def test_hook_with_script(env, info):
    payload = {**PAYLOADS["hook"], "command": "bash {script_path}", "timeout": None,
               "matcher": None, "script": {"name": "check.sh", "text": "#!/bin/sh\n"}}
    targets = resolve_targets(spec("hook", ["claude_code", "codex"], payload=payload), info, env=env)
    script, settings, cx_script, cx_hooks = targets
    want = f"{env.home}/.claude/hooks/tandem-demo-check.sh"
    assert script["path"] == want and script["file_mode"] == 0o755 and script["action"] == "create_file"
    assert settings["content"] == [{"hooks": [{"type": "command", "command": f"bash {want}"}]}]
    assert script["group"] == settings["group"] == "hook:demo"
    assert cx_script["path"] == f"{env.home}/.codex/hooks/tandem-demo-check.sh"
    assert cx_hooks["requires_trust"] and cx_hooks["path"].endswith(".codex/hooks.json")
    full = resolve_targets(spec("hook"), info, env=env)[0]
    assert full["content"] == [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi", "timeout": 5}]}]


def test_mcp_stdio_and_http(env, info):
    stdio = resolve_targets(spec("mcp", ["claude_code", "codex"]), info, env=env)
    assert stdio[0]["content"] == {"type": "stdio", "command": "npx", "args": ["-y", "gh-mcp"], "env": {"TOKEN": "${GH}"}}
    assert stdio[0]["write_mode"] == "set"
    parsed = tomllib.loads(stdio[1]["content"])
    assert parsed == {"mcp_servers": {"gh": {"command": "npx", "args": ["-y", "gh-mcp"], "env": {"TOKEN": "${GH}"}}}}
    http = {"name": "docs.v2", "transport": "http", "url": "https://x.test/mcp", "headers": {"X-Key": "${K}"}}
    both = resolve_targets(spec("mcp", ["claude_code", "codex"], payload=http), info, env=env)
    assert both[0]["content"] == {"type": "http", "url": "https://x.test/mcp", "headers": {"X-Key": "${K}"}}
    assert both[0]["pointer"] == "/mcpServers/docs.v2"
    assert tomllib.loads(both[1]["content"]) == {
        "mcp_servers": {"docs.v2": {"url": "https://x.test/mcp", "http_headers": {"X-Key": "${K}"}}}}


def test_safe_names(info):
    assert safe_name("a.b-c_1") == "a.b-c_1"
    for bad in ("../x", "a/b", "..", "", "a b", None):
        with pytest.raises(PlanError):
            safe_name(bad)
    assert safe_rel("docs/a.md") == "docs/a.md"
    for bad in ("/abs", "../x", "a/../b", "a\\b", ""):
        with pytest.raises(PlanError):
            safe_rel(bad)
    with pytest.raises(PlanError) as error:
        resolve_targets(spec("command", payload={"name": "a/b", "text": "x"}), info)
    assert error.value.code == "unsafe_name" and error.value.http == 422


def test_invalid_specs(info, env):
    for bad in ({"id": "Bad Id"}, {"kind": "nope"}, {"scope": "project", "project_path": "relative"}):
        with pytest.raises(PlanError):
            resolve_targets({**spec("rule"), **bad}, info, env=env)


def test_path_policy(env, info, project, tmp_path):
    managed = next(lay for lay in info["agents"][0]["layers"] if lay["managed"])["path"]
    assert check_path(managed, env, info, None) == "managed_layer"
    assert check_path(project / ".claude/settings.json", env, info, str(project)) == "project_shared_settings"
    assert check_path(tmp_path / "elsewhere.txt", env, info, None) == "outside_agent_roots"
    assert check_path(env.home / ".claude.json", env, info, None) is None
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, env.home / ".claude/commands/escape")
    assert check_path(env.home / ".claude/commands/escape/x.md", env, info, None) == "symlink_escape"
    targets = resolve_targets(spec("command", payload={"name": "x", "text": "t"}), info, env=env)
    assert targets[0]["mappable"]
    os.symlink(outside / "ship.md", env.home / ".claude/commands/ship.md")
    blocked = resolve_targets(spec("command"), info, env=env)[0]
    assert blocked["mappable"] is False and blocked["reason"] == "path_policy:symlink_escape"


def test_unsupported_and_undetected_agents(env, info, tmp_path):
    other = resolve_targets(spec("skill", ["hermes", "unknown"]), info, env=env)
    assert [t["reason"] for t in other] == ["agent_not_supported_v1"] * 2
    empty = tmp_path / "nohome"
    empty.mkdir()
    from tandem_backend.install.env import Env

    bare = environment(Env(home=empty, environ={}, search_dirs=[]))
    targets = resolve_targets(spec("rule"), bare)
    assert targets[0]["mappable"] and targets[0]["note"] == "agent_not_detected"
