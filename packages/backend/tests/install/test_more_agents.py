"""Install, uninstall, conflict and rollback for dsh / pi / hermes / opencode / kimi and the Codex fixes.

Every home here is fabricated under tmp_path. Expected file contents are written out by hand from
the upstream formats cited in ``install/targets.py`` (third_party/<agent>/...), not copied from
renderer output.
"""

import json
from pathlib import Path

import pytest

from orbit_backend.appdb import AppDB
from orbit_backend.install import applier
from orbit_backend.install.env import environment
from orbit_backend.install.errors import ApplyFailed, OpConflict, StaleError
from orbit_backend.install.service import InstallService
from orbit_backend.install.targets import REASON_TEXT, reason_text, resolve_targets

from .conftest import write

MCP = {"kind": "mcp", "id": "gh-mcp", "payload": {"name": "gh", "transport": "stdio", "command": "npx",
                                                  "args": ["-y", "gh-mcp"], "env": {"TOKEN": "${GH}"}}}
SSE = {"kind": "mcp", "id": "old-sse", "payload": {"name": "old", "transport": "sse", "url": "https://x.test/sse"}}
PERM = {"kind": "permission_rule", "id": "ro-git", "payload": {"allow": ["git status", "git diff"]}}
SKILL = {"kind": "skill", "id": "lint-fix", "payload": {"name": "lint-fix", "files": [
    {"rel": "SKILL.md", "text": "---\nname: lint-fix\ndescription: Fix lint\n---\n\nRun ruff.\n"}]}}
RULE = {"kind": "rule", "id": "commits", "payload": {"text": "Prefer small commits."}}
CMD = {"kind": "command", "id": "ship", "payload": {"name": "ship", "text": "Ship it.\n"}}
OC_JSON = '{\n  "$schema": "https://opencode.ai/config.json",\n  "permission": {"bash": {"*": "ask"}}\n}\n'


@pytest.fixture
def home(fake_home):
    for d in (".pi/agent", ".config/opencode", ".local/share/opencode", ".dsh", ".hermes"):
        (fake_home / d).mkdir(parents=True)
    write(fake_home / ".config/opencode/opencode.json", OC_JSON)
    return fake_home


@pytest.fixture
def svc(tmp_path, env, home):
    db = AppDB(tmp_path / "orbit" / "app.db")
    yield InstallService(db, tmp_path / "orbit", env=env)
    db.close()


def snapshot(root: Path) -> dict:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def src(spec, **extra):
    return {"type": "spec", "spec": {"title": spec["id"], **spec, **extra}}


def install(svc, spec, agents, **extra):
    plan = svc.plan(src(spec, **extra), agents=agents)
    preview = svc.preview(plan["plan_id"])
    return plan, preview, svc.apply(plan["plan_id"], preview["preview_digest"])


def targets(env, spec, agents, scope="user", project=None):
    full = {"title": spec["id"], **spec, "agents": agents, "scope": scope,
            "project_path": str(project) if project else None}
    return resolve_targets(full, environment(env, refresh=True), env=env)


# ---- install + uninstall round trips ---------------------------------------------------------

def test_skill_rule_command_round_trip_on_new_agents(svc, home):
    before = snapshot(home)
    *_, skill = install(svc, SKILL, ["dsh", "pi", "hermes", "opencode", "codex"])
    for rel in (".dsh/skills", ".pi/agent/skills", ".hermes/skills", ".config/opencode/skills", ".agents/skills"):
        assert (home / rel / "lint-fix/SKILL.md").read_text().startswith("---\nname: lint-fix\n")
    assert not (home / ".codex/skills/lint-fix").exists()  # deprecated Codex root is not written
    *_, rule = install(svc, RULE, ["dsh", "pi"])
    marked = "<!-- orbit:commits begin -->\nPrefer small commits.\n<!-- orbit:commits end -->\n"
    assert (home / ".dsh/AGENTS.md").read_text() == marked
    assert (home / ".pi/agent/AGENTS.md").read_text() == marked
    *_, cmd = install(svc, CMD, ["pi", "opencode"])
    assert (home / ".pi/agent/prompts/ship.md").read_text() == "Ship it.\n"
    assert (home / ".config/opencode/commands/ship.md").read_text() == "Ship it.\n"
    for result in (cmd, rule, skill):
        assert svc.revert(result["install_id"])["ok"]
    assert snapshot(home) == before


def test_pi_and_opencode_mcp_formats_and_revert(svc, home):
    before = snapshot(home)
    *_, result = install(svc, MCP, ["pi", "opencode"])
    # pi mcp.json: {"mcpServers": {name: {command, args, env}}} (pi extensions/mcp/config.ts header).
    assert json.loads((home / ".pi/agent/mcp.json").read_text()) == {
        "mcpServers": {"gh": {"command": "npx", "args": ["-y", "gh-mcp"], "env": {"TOKEN": "${GH}"}}}}
    # OpenCode local server: command is argv, env is "environment" (core/src/v1/config/mcp.ts Local).
    doc = json.loads((home / ".config/opencode/opencode.json").read_text())
    assert doc["mcp"] == {"gh": {"type": "local", "command": ["npx", "-y", "gh-mcp"],
                                 "environment": {"TOKEN": "${GH}"}}}
    assert doc["permission"] == {"bash": {"*": "ask"}} and doc["$schema"] == "https://opencode.ai/config.json"
    assert svc.revert(result["install_id"])["ok"]
    assert snapshot(home) == before  # mcp.json created by us is removed, opencode.json byte-identical


def test_opencode_permission_appends_after_existing_patterns(svc, home):
    *_, result = install(svc, PERM, ["opencode"])
    bash = json.loads((home / ".config/opencode/opencode.json").read_text())["permission"]["bash"]
    # findLast semantics (opencode permission/index.ts:32): our allows must come after the "*": "ask".
    assert list(bash.items()) == [("*", "ask"), ("git status *", "allow"), ("git diff *", "allow")]
    assert svc.revert(result["install_id"])["ok"]
    assert (home / ".config/opencode/opencode.json").read_text() == OC_JSON


def test_uninstall_keeps_user_edits_made_after_install(svc, home):
    *_, result = install(svc, MCP, ["opencode"])
    path = home / ".config/opencode/opencode.json"
    doc = json.loads(path.read_text())
    doc["theme"] = "mine"
    path.write_text(json.dumps(doc, indent=2) + "\n")
    assert svc.revert(result["install_id"])["ok"]
    left = json.loads(path.read_text())
    assert "mcp" not in left and left["theme"] == "mine" and left["permission"] == {"bash": {"*": "ask"}}


# ---- conflicts: preview blocks, apply refuses, nothing changes ---------------------------------

@pytest.mark.parametrize(("content", "spec", "code"), [
    ('{"mcp": {"gh": {"type": "remote", "url": "https://other"}}}\n', MCP, "mcp_exists"),
    ('{"permission": "ask"}\n', PERM, "container_type"),
    ('{"permission": {"bash": {"git status *": "deny"}}}\n', PERM, "key_exists_different"),
])
def test_opencode_conflicts_block_apply(svc, home, content, spec, code):
    path = home / ".config/opencode/opencode.json"
    path.write_text(content)
    plan = svc.plan(src(spec), agents=["opencode"])
    preview = svc.preview(plan["plan_id"])
    assert preview["conflicts"][0]["code"] == code and not preview["can_apply"]
    with pytest.raises(OpConflict):
        svc.apply(plan["plan_id"], preview["preview_digest"])
    assert path.read_text() == content


def test_opencode_jsonc_with_comments_is_refused_not_stripped(svc, home):
    (home / ".config/opencode/opencode.json").unlink()
    jsonc = home / ".config/opencode/opencode.jsonc"
    jsonc.write_text('{\n  // my servers\n  "mcp": {}\n}\n')
    plan = svc.plan(src(MCP), agents=["opencode"])
    assert plan["targets"][0]["display"] == "~/.config/opencode/opencode.jsonc"
    preview = svc.preview(plan["plan_id"])
    assert preview["conflicts"][0]["code"] == "parse_error" and not preview["can_apply"]
    assert jsonc.read_text() == '{\n  // my servers\n  "mcp": {}\n}\n'


def test_pi_mcp_same_name_server_is_not_overwritten(svc, home):
    path = write(home / ".pi/agent/mcp.json", '{"mcpServers": {"gh": {"command": "gh-mcp"}}}\n')
    plan = svc.plan(src(MCP), agents=["pi"])
    preview = svc.preview(plan["plan_id"])
    assert preview["conflicts"][0]["code"] == "mcp_exists"
    assert path.read_text() == '{"mcpServers": {"gh": {"command": "gh-mcp"}}}\n'


# ---- rollback ----------------------------------------------------------------------------------

def test_failed_second_write_rolls_back_first_agent(svc, home, monkeypatch):
    before = snapshot(home)
    plan = svc.plan(src(MCP), agents=["pi", "opencode"])
    preview = svc.preview(plan["plan_id"])
    real = applier.os.replace

    def replace(a, b, *args, **kw):
        if str(b).endswith("opencode.json"):
            raise OSError("disk full")
        return real(a, b, *args, **kw)

    monkeypatch.setattr(applier.os, "replace", replace)
    with pytest.raises(ApplyFailed):
        svc.apply(plan["plan_id"], preview["preview_digest"])
    monkeypatch.undo()
    assert snapshot(home) == before  # pi's new mcp.json was removed again


def test_edit_between_preview_and_apply_is_stale(svc, home):
    plan = svc.plan(src(MCP), agents=["pi", "opencode"])
    preview = svc.preview(plan["plan_id"])
    path = home / ".config/opencode/opencode.json"
    path.write_text("not json")
    with pytest.raises(StaleError):
        svc.apply(plan["plan_id"], preview["preview_digest"])
    assert not (home / ".pi/agent/mcp.json").exists() and path.read_text() == "not json"


# ---- unsupported / unverified --------------------------------------------------------------------

def test_kimi_is_never_written(svc, home):
    (home / ".kimi-code").mkdir()
    before = snapshot(home)
    plan = svc.plan(src(SKILL), agents=["kimi"])
    assert plan["status"] == "unmappable"
    assert plan["targets"][0]["reason"] == "kimi_unverified_no_source"
    assert plan["targets"][0]["reason_text"] == REASON_TEXT["kimi_unverified_no_source"]
    assert snapshot(home) == before


def test_sse_refused_where_agent_cannot_speak_it(env, home):
    got = targets(env, SSE, ["codex", "pi", "opencode", "claude_code"])
    assert [(t["agent"], t["mappable"]) for t in got] == [
        ("codex", False), ("pi", False), ("opencode", True), ("claude_code", True)]
    assert got[0]["reason"] == got[1]["reason"] == "mcp_transport_unsupported"
    assert got[2]["content"] == {"type": "remote", "url": "https://x.test/sse"}


def test_unsupported_kinds_have_reasons(env, home):
    hook = {"kind": "hook", "id": "h", "payload": {"event": "Stop", "command": "true"}}
    got = targets(env, hook, ["dsh", "pi", "hermes", "opencode"])
    assert [t["reason"] for t in got] == ["dsh_cordis_patch_unsupported_v1", "pi_hooks_are_extensions",
                                          "hermes_yaml_config_unsupported_v1", "opencode_hooks_are_plugins"]
    assert all(t["reason_text"] == REASON_TEXT[t["reason"]] for t in got)
    assert targets(env, CMD, ["codex"])[0]["reason"] == "codex_custom_prompts_removed"


# ---- context file chains -------------------------------------------------------------------------

def test_codex_user_rule_goes_to_non_empty_override(env, home):
    override = home / ".codex/AGENTS.override.md"
    override.write_text("  \n")  # empty override is skipped by codex-home/src/instructions/mod.rs
    assert targets(env, RULE, ["codex"])[0]["path"] == str(home / ".codex/AGENTS.md")
    override.write_text("# override\n")
    assert targets(env, RULE, ["codex"])[0]["path"] == str(override)


def test_pi_project_with_only_claude_md_is_refused(env, home, tmp_path):
    proj = tmp_path / "proj"
    write(proj / "CLAUDE.md", "# team\n")
    got = targets(env, RULE, ["pi", "dsh"], scope="project", project=proj)
    assert got[0]["mappable"] is False and got[0]["reason"] == "context_file_shadowed:CLAUDE.md"
    assert got[0]["reason_text"] == reason_text("context_file_shadowed")
    assert got[1]["path"] == str(proj / "AGENTS.md")  # dsh loads AGENTS.md and CLAUDE.md side by side
    write(proj / "AGENTS.md", "# agents\n")
    assert targets(env, RULE, ["pi"], scope="project", project=proj)[0]["path"] == str(proj / "AGENTS.md")


def test_hermes_project_priority(env, home, tmp_path):
    proj = tmp_path / "proj"
    write(proj / ".cursorrules", "be nice\n")
    assert targets(env, RULE, ["hermes"], scope="project", project=proj)[0]["reason"] == \
        "context_file_shadowed:.cursorrules"
    write(proj / "AGENTS.md", "# a\n")
    write(proj / ".hermes.md", "")  # empty: hermes falls through to the next type
    assert targets(env, RULE, ["hermes"], scope="project", project=proj)[0]["path"] == str(proj / "AGENTS.md")
    write(proj / ".hermes.md", "# h\n")
    got = targets(env, RULE, ["hermes"], scope="project", project=proj)[0]
    assert got["path"] == str(proj / ".hermes.md") and got["shared_layer"]


def test_opencode_user_rule_would_shadow_claude_md(env, home):
    got = targets(env, RULE, ["opencode"])[0]  # fake_home has ~/.claude/CLAUDE.md, no opencode AGENTS.md
    assert got["mappable"] is False and got["reason"] == "context_file_shadowed:CLAUDE.md"
    (home / ".claude/CLAUDE.md").unlink()
    assert targets(env, RULE, ["opencode"])[0]["path"] == str(home / ".config/opencode/AGENTS.md")


def test_codex_project_hook_scripts_stay_in_project(env, home, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    hook = {"kind": "hook", "id": "fmt", "payload": {"event": "Stop", "command": "bash {script_path}",
                                                     "script": {"name": "fmt.sh", "text": "#!/bin/sh\n"}}}
    script, hooks = targets(env, hook, ["codex"], scope="project", project=proj)
    assert script["path"] == str(proj / ".codex/hooks/orbit-fmt-fmt.sh")
    assert hooks["path"] == str(proj / ".codex/hooks.json") and hooks["requires_trust"]
    assert hooks["content"][0]["hooks"][0]["command"] == f"bash {proj}/.codex/hooks/orbit-fmt-fmt.sh"


def test_plan_and_preview_mark_unverified_min_version(svc):
    # opencode has no checked minimum version: both the plan summary and the preview rows the UI
    # reads must say so, otherwise the 版本兼容性未知 note never shows.
    plan = svc.plan(src(SKILL), agents=["opencode", "claude_code"])
    by_agent = {t["agent"]: t["version_check"] for t in plan["targets"] if t["mappable"]}
    preview = svc.preview(plan["plan_id"])
    rows = {t["agent"]: t["version_check"] for t in preview["targets"] if t["mappable"]}
    assert by_agent == rows == {"opencode": "unknown", "claude_code": "known"}
