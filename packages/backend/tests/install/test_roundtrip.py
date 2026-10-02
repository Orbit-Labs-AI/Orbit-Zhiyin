"""EV-13: every action on realistic files applies cleanly and reverts byte-for-byte."""

import json
import tomllib
from pathlib import Path

import pytest

from tandem_backend.install import applier

SETTINGS = """{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(git status:*)"
    ],
    "deny": [
      "Read(./.env)"
    ]
  },
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "afplay /System/Library/Sounds/Glass.aiff"
          }
        ]
      }
    ]
  },
  "model": "opus",
  "statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}
}
"""
CLAUDE_JSON = json.dumps({
    "numStartups": 42, "userID": "u", "projects": {"/Users/x/p": {"allowedTools": []}},
    "mcpServers": {"existing": {"type": "stdio", "command": "uvx", "args": ["foo"]}},
}, indent=2)
CONFIG_TOML = """# Codex config
model = "gpt-5"

[mcp_servers.docs]
command = "npx"  # keep this comment
args = ["-y", "docs-mcp"]
"""
CLAUDE_MD = "# Project memory\n\n- Use uv for Python.\n"
SKILL = "---\nname: lint-fix\ndescription: Fix lint errors\n---\n\nRun `ruff check --fix`.\n"


def t(idx, path, action, **kw):
    return {"idx": idx, "agent": kw.pop("agent", "claude_code"), "scope": "user",
            "path": str(path), "display": str(path), "action": action,
            "pointer": kw.pop("pointer", None), "content": kw.pop("content", None),
            "write_mode": kw.pop("write_mode", "add"), "block_id": kw.pop("block_id", None),
            "file_mode": kw.pop("file_mode", None), "mappable": True, **kw}


CASES = {
    "permissions_allow": ("settings.json", SETTINGS, lambda p: [
        t(0, p, "merge_json", pointer="/permissions/allow", content=["Bash(git diff:*)"])]),
    "hooks_new_event": ("settings.json", SETTINGS, lambda p: [
        t(0, p, "merge_json", pointer="/hooks/PostToolUse", content=[
            {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "ruff format"}]}])]),
    "mcp_servers": (".claude.json", CLAUDE_JSON, lambda p: [
        t(0, p, "merge_json", pointer="/mcpServers",
          content={"github": {"type": "http", "url": "https://api.example/mcp"}})]),
    "plugins": ("settings.json", SETTINGS, lambda p: [
        t(0, p, "merge_json", pointer="/enabledPlugins", content={"lint@tools": True}),
        t(1, p, "merge_json", pointer="/extraKnownMarketplaces",
          content={"tools": {"source": {"source": "github", "repo": "o/r"}}})]),
    "setting_set": ("settings.json", SETTINGS, lambda p: [
        t(0, p, "merge_json", pointer="", content={"model": "sonnet"}, write_mode="set")]),
    "claude_md": ("CLAUDE.md", CLAUDE_MD, lambda p: [
        t(0, p, "md_block", content="## Tandem\n- run tests", block_id="tandem:tests")]),
    "agents_md_new": ("AGENTS.md", None, lambda p: [
        t(0, p, "md_block", content="Prefer small commits.", block_id="tandem:commits",
          agent="codex")]),
    "codex_toml": ("config.toml", CONFIG_TOML, lambda p: [
        t(0, p, "toml_block", content='[mcp_servers.gh]\ncommand = "gh-mcp"',
          block_id="tandem:gh", agent="codex")]),
    "skill_files": ("skills/lint-fix/SKILL.md", None, lambda p: [
        t(0, p, "create_file", content=SKILL),
        t(1, p.parent / "scripts" / "fix.sh", "create_file", content="#!/bin/sh\nruff\n",
          file_mode=0o755)]),
    "codex_rules": ("rules/tandem-git.rules", None, lambda p: [
        t(0, p, "create_file", content='prefix_rule(pattern=["git", "status"])\n',
          agent="codex")]),
}


def _parse(path: Path):
    text = path.read_text()
    if path.suffix == ".json":
        return json.loads(text)
    if path.suffix == ".toml":
        return tomllib.loads(text)
    return text


def _setup(tmp_path, name):
    rel, original, make = CASES[name]
    home = tmp_path / "home"
    path = home / ".agent" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if original is not None:
        path.write_text(original)
    elif not any(path.parent.iterdir()):
        path.parent.rmdir()
    env = {"backup_dir": tmp_path / "b", "lock_dir": tmp_path / "l"}
    return home, path, original, make(path), env


def _apply(home, targets, env):
    prep = applier.preflight(targets, selected={}, expect=None, home=home)
    return applier.apply_targets(prep, install_id="i", home=home, **env)


def _revert(recs, env):
    return applier.revert_records(recs, backup_dir=env["backup_dir"], lock_dir=env["lock_dir"])


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in sorted(root.rglob("*"))}


@pytest.mark.parametrize("name", list(CASES))
def test_apply_then_revert_is_byte_identical(tmp_path, name):
    home, path, original, targets, env = _setup(tmp_path, name)
    before = _snapshot(home)
    recs = _apply(home, targets, env)
    for tg in targets:
        p = Path(tg["path"])
        parsed = _parse(p)
        if p.suffix == ".json":
            assert parsed.get("numStartups", 42) == 42 or "permissions" in parsed
        if p.suffix == ".toml":
            assert parsed["mcp_servers"]["docs"]["args"] == ["-y", "docs-mcp"]
            assert "# keep this comment" in p.read_text()
        if tg.get("file_mode"):
            assert p.stat().st_mode & 0o777 == 0o755
    res = _revert(recs, env)
    assert {r["status"] for r in res} == {"reverted"}, res
    assert _snapshot(home) == before
    again = _revert(recs, env)
    assert {r["status"] for r in again} == {"already_reverted"}, again
    assert _snapshot(home) == before


UNIT_CASES = ["permissions_allow", "mcp_servers", "setting_set", "claude_md", "codex_toml"]


@pytest.mark.parametrize("name", UNIT_CASES)
def test_unrelated_edit_still_reverts_our_unit(tmp_path, name):
    home, path, original, targets, env = _setup(tmp_path, name)
    recs = _apply(home, targets, env)
    if path.suffix == ".json":
        data = json.loads(path.read_text())
        data["unrelatedKey"] = {"added": "later"}
        path.write_text(json.dumps(data, indent=2) + "\n")
    else:
        path.write_text(path.read_text() + "\n# user note\n")
    res = _revert(recs, env)
    assert res[0]["status"] == "reverted", res
    if path.suffix == ".json":
        data = json.loads(path.read_text())
        assert data["unrelatedKey"] == {"added": "later"}
        assert data == {**json.loads(original), "unrelatedKey": {"added": "later"}}
    else:
        text = path.read_text()
        assert "tandem:" not in text and "# user note" in text
    assert _revert(recs, env)[0]["status"] == "already_reverted"


@pytest.mark.parametrize("name", ["mcp_servers", "setting_set", "claude_md", "codex_toml", "skill_files"])
def test_user_edit_of_our_unit_is_refused(tmp_path, name):
    home, path, original, targets, env = _setup(tmp_path, name)
    recs = _apply(home, targets, env)
    text = path.read_text()
    if name == "mcp_servers":
        edited = text.replace("https://api.example/mcp", "https://other.example/mcp")
    elif name == "setting_set":
        edited = text.replace('"sonnet"', '"haiku"')
    elif name == "skill_files":
        edited = text + "extra\n"
    else:
        edited = text.replace("run tests", "run all tests").replace("gh-mcp", "gh-mcp2")
    assert edited != text
    path.write_text(edited)
    res = _revert(recs, env)
    mine = [r for r in res if r["idx"] == 0][0]
    assert mine["status"] == "modified" and mine["manual_steps"]
    sides = {ln["side"] for ln in mine["diff"]["lines"]}
    # create_file keeps only a hash in the ledger, so there is no "ours" text to show
    assert sides == {"current"} if name == "skill_files" else {"ours", "current"} <= sides
    assert path.read_text() == edited


def test_edited_array_item_counts_as_gone(tmp_path):
    """A list edit is indistinguishable from remove+add: our item is gone, theirs stays."""
    home, path, original, targets, env = _setup(tmp_path, "permissions_allow")
    recs = _apply(home, targets, env)
    edited = path.read_text().replace("Bash(git diff:*)", "Bash(git diff --stat:*)")
    path.write_text(edited)
    assert _revert(recs, env)[0]["status"] == "already_reverted"
    assert path.read_text() == edited
