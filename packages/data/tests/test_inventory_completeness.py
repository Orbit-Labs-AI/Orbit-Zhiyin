"""Regression inputs mirror native source layouts, not private machine payloads."""

import json

import pytest

from orbit_data.inventory import InventoryRequest, read_inventory, scan_inventory
from orbit_data.store import Store


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict | list) else value)
    return path


def scan(tmp_path, agent, root, **kwargs):
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest(agent, root, **kwargs))
        return result, read_inventory(store.home), "\n".join(store.db.iterdump())


@pytest.mark.parametrize(
    "agent", ["claude_code", "codex", "pi", "hermes", "opencode", "dsh", "kimi"]
)
def test_skill_boundaries_trash_and_frontmatter_for_all_connectors(tmp_path, agent):
    root = tmp_path / "source"
    write(
        root,
        "skills/synced/account/deploy-folder/SKILL.md",
        "---\nname: vercel-deploy\n---\nprivate body",
    )
    write(
        root,
        "skills/synced/account/deploy-folder/scripts/a/b/c/d/e/f/SKILL.md",
        "not another installed skill",
    )
    write(root, "skills/.trash/removed/SKILL.md", "old")
    result, data, dump = scan(tmp_path, agent, root)
    items = [item for item in data["items"] if item["type"] == "skill"]
    assert [item["name"] for item in items] == ["vercel-deploy"]
    assert result["coverage"]["skill"]["status"] == "available"
    assert "private body" not in dump
    assert not result["diagnostics"]


def test_desktop_remote_connectors_use_newest_snapshot_per_account(tmp_path):
    root = tmp_path / "desktop"
    base = root / "claude-code-sessions/org/account"
    write(
        base,
        "local_old.json",
        {"lastActivityAt": 100, "remoteMcpServersConfig": [{"uuid": "gone", "name": "Removed"}]},
    )
    write(
        base,
        "local_new.json",
        {
            "lastActivityAt": 200,
            "remoteMcpServersConfig": [
                {
                    "uuid": "v",
                    "name": "Vercel",
                    "url": "https://user:secret@example.test?token=hidden",
                    "tools": [{"name": "deploy", "inputSchema": {"description": "PRIVATE SCHEMA"}}],
                },
                {"uuid": "c", "name": "Cloudflare", "tools": []},
                {"uuid": "d", "name": "Cloudflare Developer Platform", "tools": []},
            ],
            "title": "PRIVATE TITLE",
            "initialMessage": "PRIVATE PROMPT",
        },
    )
    write(base, "scheduled-tasks.json", {"scheduledTasks": [], "recordedSkips": {}})
    result, data, dump = scan(tmp_path, "claude_desktop", root)
    assert {item["name"] for item in data["items"] if item["type"] == "mcp"} == {
        "Vercel",
        "Cloudflare",
        "Cloudflare Developer Platform",
    }
    assert result["coverage"]["mcp"]["status"] == "partial"
    assert result["coverage"]["scheduled_task"]["status"] == "available"
    assert all(item["evidence"] == "cached" and item["enabled"] is None for item in data["items"])
    assert all(item["config"]["source_observed_at"] == 200 for item in data["items"])
    assert all(secret not in dump for secret in ("PRIVATE", "user:secret", "hidden", "Removed"))
    # An explicitly empty newer snapshot must not resurrect old connector state.
    write(base, "local_empty.json", {"lastActivityAt": 300, "remoteMcpServersConfig": []})
    _, updated, _ = scan(tmp_path, "claude_desktop", root)
    assert updated["items"] == []


@pytest.mark.parametrize(
    "agent,manifest_name",
    [("claude_code", ".claude-plugin/plugin.json"), ("codex", ".codex-plugin/plugin.json")],
)
def test_plugin_manifest_inline_and_custom_components_are_observed(tmp_path, agent, manifest_name):
    root = tmp_path / "source"
    folder = root / "plugins/cache/market/deploy/1"
    write(
        folder,
        manifest_name,
        {
            "name": "deploy",
            "skills": ["./custom"],
            "mcpServers": [{"Vercel": {"url": "https://example.test"}}, "./servers.json"],
            "hooks": {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "PRIVATE"}]}]}},
        },
    )
    write(folder, "servers.json", {"mcpServers": {"Cloudflare": {"command": "tool"}}})
    write(folder, ".mcp.json", {"plain-map-server": {"command": "tool"}})
    write(folder, "custom/a/SKILL.md", "---\nname: cloudflare-deploy\n---\nprivate")
    _, data, dump = scan(tmp_path, agent, root)
    assert {"Vercel", "Cloudflare", "plain-map-server", "cloudflare-deploy", "Stop"} <= {
        item["name"] for item in data["items"]
    }
    assert all(item["evidence"] == "cached" for item in data["items"])
    assert "PRIVATE" not in dump


def test_synced_plugins_and_cowork_installation_are_not_marketplace_catalogs(tmp_path):
    root = tmp_path / "source"
    write(
        root,
        "plugins/synced/account/deploy/.claude-plugin/plugin.json",
        {"name": "deploy", "mcpServers": {"Vercel": {"url": "https://example.test"}}},
    )
    write(root, "plugins/synced/account/deploy/skills/a/SKILL.md", "skill")
    write(
        root,
        "plugins/marketplaces/catalog/not-installed/.claude-plugin/plugin.json",
        {"name": "not-installed"},
    )
    _, data, _ = scan(tmp_path, "claude_code", root)
    assert {"deploy", "Vercel", "a"} == {item["name"] for item in data["items"]}
    assert all(item["evidence"] == "cached" for item in data["items"])


def test_desktop_extensions_cowork_plugins_and_scheduled_tasks(tmp_path):
    root = tmp_path / "desktop"
    write(
        root,
        "extensions-installations.json",
        {
            "extensions": {
                "sample": {
                    "manifest": {
                        "name": "local-mcp",
                        "server": {"type": "node", "args": ["PRIVATE"]},
                    }
                }
            }
        },
    )
    folder = root / "local-agent-mode-sessions/org/account/cowork_plugins"
    installed = folder / "cache/market/tools/1"
    write(
        folder,
        "installed_plugins.json",
        {"plugins": {"tools@market": [{"installPath": str(installed)}]}},
    )
    write(installed, ".claude-plugin/plugin.json", {"name": "tools"})
    write(installed, "skills/review/SKILL.md", "skill")
    write(
        folder.parent,
        "scheduled-tasks.json",
        {
            "scheduledTasks": [
                {"id": "daily", "name": "Daily", "enabled": False, "prompt": "PRIVATE"}
            ]
        },
    )
    result, data, dump = scan(tmp_path, "claude_desktop", root)
    assert {"local-mcp", "tools@market", "review", "Daily"} <= {
        item["name"] for item in data["items"]
    }
    assert result["coverage"]["scheduled_task"]["status"] == "available"
    assert next(item for item in data["items"] if item["name"] == "Daily")["enabled"] == 0
    assert "PRIVATE" not in dump


def test_pi_package_payloads_and_explicit_disable_all(tmp_path):
    root = tmp_path / "pi"
    write(root, "settings.json", {"packages": [{"source": "npm:@example/deploy@1", "skills": []}]})
    package = root / "npm/node_modules/@example/deploy"
    write(
        package,
        "package.json",
        {"name": "@example/deploy", "pi": {"skills": ["custom/a/SKILL.md"]}},
    )
    write(package, "custom/a/SKILL.md", "---\nname: vercel-deploy\n---\nprivate")
    result, data, _ = scan(tmp_path, "pi", root)
    assert result["status"] == "available"
    resource = next(item for item in data["items"] if item["name"] == "vercel-deploy")
    assert resource["enabled"] == 0
    assert resource["config"]["plugin"] == "@example/deploy"


def test_hermes_portable_plugins_and_hook_alias(tmp_path):
    root = tmp_path / "hermes"
    write(
        root,
        "plugins/portable/plugin.json",
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "portable",
        },
    )
    write(root, "plugins/portable/mcp.json", {"mcpServers": {"Cloudflare": {"command": "tool"}}})
    write(root, "plugins/portable/skills/deploy/SKILL.md", "skill")
    write(root, "plugins/native/plugin.yaml", "name: native\nhooks: [agent:start]")
    _, data, _ = scan(tmp_path, "hermes", root)
    assert {"portable", "Cloudflare", "deploy", "native", "agent:start"} <= {
        item["name"] for item in data["items"]
    }


def test_opencode_servers_named_servers_and_timeout_metadata(tmp_path):
    root = tmp_path / "opencode"
    write(
        root,
        "opencode.json",
        {"mcp": {"servers": {"type": "remote", "url": "https://example.test"}}},
    )
    write(root, "opencode.jsonc", '{"mcp":{"timeout":{"startup":100}}}')
    _, data, _ = scan(tmp_path, "opencode", root)
    assert [item["name"] for item in data["items"] if item["type"] == "mcp"] == ["servers"]


def test_dsh_disabled_installed_dependency_remains_in_inventory(tmp_path):
    root = tmp_path / "dsh"
    write(
        root, "package.json", {"dependencies": {"deploy": "1"}, "dsh": {"profile": {"bundles": []}}}
    )
    write(
        root,
        "node_modules/deploy/package.json",
        {"name": "deploy", "dsh": {"bundle": {"patch": "cordis.patch.yml"}}},
    )
    write(root, "node_modules/deploy/cordis.patch.yml", [])
    write(root, "node_modules/deploy/skills/deploy/SKILL.md", "skill")
    result, data, _ = scan(tmp_path, "dsh", root)
    assert result["status"] == "available"
    assert next(item for item in data["items"] if item["type"] == "skill")["enabled"] == 0
    assert any(item["evidence"] == "installed" for item in data["items"])


def test_plugin_paths_cannot_escape_package_even_into_authorized_root(tmp_path):
    root = tmp_path / "kimi"
    plugin = root / "plugins/managed/a"
    write(
        root,
        "plugins/installed.json",
        {"version": 1, "plugins": [{"id": "a", "root": str(plugin), "enabled": True}]},
    )
    write(plugin, "kimi.plugin.json", {"name": "a", "skills": ["../../../shared"]})
    write(root, "shared/foreign/SKILL.md", "not part of plugin")
    result, data, _ = scan(tmp_path, "kimi", root)
    assert result["coverage"]["skill"]["status"] == "partial"
    assert "foreign" not in {item["name"] for item in data["items"]}


def test_explicit_shared_skill_roots_and_codex_path_selectors(tmp_path):
    root, shared = tmp_path / "codex", tmp_path / "shared"
    doc = write(shared, "deploy/SKILL.md", "---\nname: vercel-deploy\n---\nprivate")
    write(root, "config.toml", f'[[skills.config]]\npath="{doc}"\nenabled=false')
    result, data, _ = scan(tmp_path, "codex", root, skill_roots=(shared,))
    assert result["status"] == "available"
    items = [
        item for item in data["items"] if item["type"] == "skill" and item["evidence"] == "file"
    ]
    assert len(items) == 1
    assert items[0]["name"] == "vercel-deploy"
    assert items[0]["enabled"] == 0


def test_metadata_sidecars_are_not_packages_or_automations(tmp_path):
    root = tmp_path / "codex"
    write(root, "plugins/cache/market/plugin/.codex-remote-plugin-install.json", {})
    write(root, "plugins/cache/market/plugin/1/.codex-plugin/plugin.json", {"name": "plugin"})
    write(root, "automations/.run-jitter-salt", "salt")
    result, _, _ = scan(tmp_path, "codex", root)
    assert result["status"] == "available"
    root = tmp_path / "claude"
    write(root, "plugins/synced/account/manifest.json", {})
    write(root, "plugins/synced/account/sample.meta.json", {})
    write(root, "plugins/synced/account/sample/.claude-plugin/plugin.json", {"name": "sample"})
    result, data, _ = scan(tmp_path, "claude_code", root)
    assert result["status"] == "available"
    assert {item["name"] for item in data["items"]} >= {"sample"}


def test_dsh_can_resolve_shipped_bundles_under_explicit_installation_root(tmp_path):
    root, installation = tmp_path / "dsh", tmp_path / "installation"
    write(root, "package.json", {"dsh": {"profile": {"bundles": ["base"]}}})
    write(
        installation,
        "node_modules/base/package.json",
        {"name": "base", "dsh": {"bundle": {"patch": "cordis.patch.yml"}}},
    )
    write(
        installation,
        "node_modules/base/cordis.patch.yml",
        [
            {
                "insert": [
                    {"name": "@deepseek-ai/dsh-mcp-client", "config": {"serverName": "Cloudflare"}}
                ]
            }
        ],
    )
    result, data, _ = scan(tmp_path, "dsh", root, allowed_roots=(installation,))
    assert result["status"] == "available"
    assert "Cloudflare" in {item["name"] for item in data["items"]}


def test_project_layout_includes_native_agent_configs_without_generic_config_json(tmp_path):
    root = tmp_path / "project"
    for path, name in [(".pi/mcp.json", "pi"), (".kimi-code/mcp.json", "kimi")]:
        write(root, path, {"mcpServers": {name: {"command": "tool"}}})
    write(root, "opencode.json", {"mcp": {"opencode": {"type": "local", "command": ["tool"]}}})
    write(root, "config.json", {"mcp": {"not-agent-config": {"command": "tool"}}})
    _, data, _ = scan(tmp_path, "project", root)
    assert {item["name"] for item in data["items"] if item["type"] == "mcp"} == {
        "pi",
        "kimi",
        "opencode",
    }


def test_shared_scan_does_not_abort_after_unapproved_skill_symlink(tmp_path):
    root = tmp_path / "claude"
    external = tmp_path / "external"
    write(external, "SKILL.md", "external")
    (root / "skills").mkdir(parents=True)
    (root / "skills/a-external").symlink_to(external, target_is_directory=True)
    write(root, "skills/z-valid/SKILL.md", "valid")
    result, data, _ = scan(tmp_path, "claude_code", root)
    assert result["coverage"]["skill"]["status"] == "partial"
    assert [item["name"] for item in data["items"] if item["type"] == "skill"] == ["z-valid"]


def test_desktop_malformed_metadata_stays_partial_without_exposing_private_fields(tmp_path):
    root = tmp_path / "desktop"
    write(
        root,
        "claude-code-sessions/org/account/local_bad.json",
        {
            "lastActivityAt": 200,
            "remoteMcpServersConfig": "unsupported",
            "initialMessage": "PRIVATE",
        },
    )
    result, data, dump = scan(tmp_path, "claude_desktop", root)
    assert result["coverage"]["mcp"]["status"] == "partial"
    assert "PRIVATE" not in dump
    assert not data["items"]


def test_default_and_manifest_reference_to_same_component_are_not_double_counted(tmp_path):
    root = tmp_path / "codex"
    folder = root / "plugins/cache/market/deploy/1"
    write(
        folder,
        ".codex-plugin/plugin.json",
        {"name": "deploy", "mcpServers": ["./.mcp.json", "./.mcp.json"]},
    )
    write(
        folder,
        ".mcp.json",
        {"$schema": "https://example.test/schema", "Cloudflare": {"command": "tool"}},
    )
    result, data, _ = scan(tmp_path, "codex", root)
    assert result["status"] == "available"
    assert [item["name"] for item in data["items"] if item["type"] == "mcp"] == ["Cloudflare"]
