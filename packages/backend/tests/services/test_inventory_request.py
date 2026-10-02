"""Inventory jobs authorize symlink targets, the account MCP file and shared skill roots
(recs-B6). Synthetic trees only: nothing reads the real home directory."""

import json
from pathlib import Path

from tandem_data.inventory import InventoryRequest, read_inventory, scan_inventory
from tandem_data.store import Store

from tandem_backend.services.worker_ingest import inventory_request


def write(root: Path, rel: str, value) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def skill(root: Path, rel: str, name: str) -> None:
    write(root, rel + "/SKILL.md", f"---\nname: {name}\ndescription: d\n---\nbody\n")


def tree(tmp_path):
    home = tmp_path / "home"
    shared = home / "dotfiles" / "claude"
    skill(shared, "skills/linked", "linked")
    write(shared, "settings.json", {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "true"}]}]}})
    skill(home / "work", "external-skill", "external")
    root = home / ".claude"
    root.mkdir(parents=True)
    (root / "skills").symlink_to(shared / "skills")
    (shared / "skills" / "external").symlink_to(home / "work" / "external-skill")
    (root / "settings.json").symlink_to(shared / "settings.json")
    write(home, ".claude.json", {"oauthAccount": {"email": "private"},
                                 "mcpServers": {"account-mcp": {"command": "cli"}}})
    skill(home, ".agents/skills/shared", "shared")
    return home, root


def test_request_carries_symlink_targets_account_config_and_skill_roots(tmp_path):
    home, root = tree(tmp_path)
    data = tmp_path / "data"
    claude = inventory_request({"agent": "claude_code", "root": str(root)}, data, home)
    assert set(claude["allowed_roots"]) == {
        (home / "dotfiles/claude/skills").resolve(),
        (home / "dotfiles/claude/settings.json").resolve(),
        (home / "work/external-skill").resolve()}
    assert claude["claude_config"] == home.resolve() / ".claude.json"
    assert claude["skill_roots"] == ()
    codex = inventory_request({"agent": "codex", "root": str(home / ".codex")}, data, home)
    assert codex["skill_roots"] == (home.resolve() / ".agents/skills",)
    assert "claude_config" not in codex
    explicit = inventory_request({"agent": "claude_code", "root": str(root),
                                  "allowed_roots": [], "claude_config": None}, data, home)
    assert explicit["allowed_roots"] == () and explicit["claude_config"] is None

    with Store(data) as store:
        scan_inventory(store, InventoryRequest("claude_code", root))
        assert not any(i["type"] == "skill" for i in read_inventory(store.home)["items"])
        scan_inventory(store, InventoryRequest(**claude))
        items = read_inventory(store.home)["items"]
    names = {(item["type"], item["name"]) for item in items}
    assert {("skill", "linked"), ("skill", "external"), ("mcp", "account-mcp")} <= names
    assert any(item["type"] == "hook" for item in items)


def test_second_account_and_data_home_are_never_authorized(tmp_path):
    home = tmp_path / "home"
    root = home / ".claude-work"
    write(root, ".claude.json", {"mcpServers": {"work-mcp": {}}})
    data = home / "tandem-data"
    data.mkdir(parents=True)
    (root / "home-link").symlink_to(home)
    (root / "data-link").symlink_to(data)
    (root / "outside").symlink_to(tmp_path)
    request = inventory_request({"agent": "claude_code", "root": str(root)}, data, home)
    assert request["allowed_roots"] == ()
    assert request["claude_config"] == root.resolve() / ".claude.json"
