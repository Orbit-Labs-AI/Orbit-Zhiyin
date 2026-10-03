"""Native synthetic trees for every registered connector; never use real HOME data."""

import json

import pytest

from orbit_data.connectors import MAPPERS
from orbit_data.inventory import InventoryRequest, read_inventory, scan_inventory
from orbit_data.inventory.adapters import SUPPORTED
from orbit_data.store import Store


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value) if isinstance(value, dict | list) else value)
    return target


def run(tmp_path, agent, root):
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest(agent, root))
        data = read_inventory(store.home)
        return result, data, "\n".join(store.db.iterdump())


def test_every_builtin_connector_has_inventory_adapter():
    assert set(MAPPERS) <= SUPPORTED.keys()


@pytest.mark.parametrize("agent", sorted(MAPPERS))
def test_all_connectors_support_explicit_empty_and_idempotent_observations(tmp_path, agent):
    root = tmp_path / agent
    root.mkdir()
    with Store(tmp_path / "data") as store:
        for _ in range(2):
            result = scan_inventory(store, InventoryRequest(agent, root))
            assert result["status"] == "available"
            assert read_inventory(store.home)["items"] == []
        assert store.db.execute("SELECT COUNT(*) FROM inventory_scan").fetchone()[0] == 2


def test_pi_packages_extensions_skills_mcp_and_unknown_dynamic_hooks(tmp_path):
    root = tmp_path / "pi"
    write(
        root,
        "settings.json",
        {
            "packages": [
                "npm:@example/tool",
                {"source": "https://user:private@example.test/pkg?secret=yes"},
            ],
            "extensions": ["./extensions/custom.ts"],
            "skills": ["./extra"],
        },
    )
    write(
        root,
        "npm/node_modules/@example/tool/package.json",
        {"name": "@example/tool", "pi": {"skills": []}},
    )
    write(root, "git/example.test/pkg/package.json", {"name": "pkg", "pi": {"skills": []}})
    write(root, "extra/review/SKILL.md", "private skill")
    write(root, "extensions/custom.ts", 'throw new Error("MUST NOT EXECUTE")')
    write(
        root,
        "mcp.json",
        {"mcpServers": {"search": {"disabled": True, "env": {"TOKEN": "private-token"}}}},
    )
    write(root, "AGENTS.md", "private rule")
    result, data, dump = run(tmp_path, "pi", root)
    assert result["status"] == "available"
    assert result["coverage"]["hook"]["status"] == "unavailable"
    assert result["coverage"]["scheduled_task"]["rows"] is None
    assert {item["type"] for item in data["items"]} == {"skill", "plugin", "mcp", "rule"}
    assert next(item for item in data["items"] if item["name"] == "search")["enabled"] == 0
    assert not any(
        value in dump for value in ("private-token", "MUST NOT EXECUTE", "user:private", "?secret=")
    )


@pytest.mark.parametrize("version", [1, 2])
def test_opencode_jsonc_versions_do_not_expand_env_or_read_files(tmp_path, version):
    root = tmp_path / "opencode"
    config = {
        "mcp": {"search": {"type": "local", "command": ["tool", "private-arg"], "enabled": False}},
        "plugin": ["package-a", ["package-b", {"token": "private-option"}]],
        "skills": {"paths": ["./extra"]},
        "instructions": ["INSTRUCTIONS.md"],
    }
    if version == 2:
        config["mcp"] = {
            "servers": {"search": {"type": "local", "command": ["tool"], "disabled": True}}
        }
        config["plugins"] = [{"package": "package-c", "options": {"api_key": "private-option"}}]
        config["skills"] = ["./extra"]
    # Comments/trailing commas; interpolation is a declaration, not an IO request.
    text = json.dumps(config)[:-1] + ', "provider": {"apiKey":"{file:/never/open}"},}'
    write(root, "opencode.jsonc", "// native config\n" + text)
    write(root, "extra/check/SKILL.md", "skill")
    write(root, "INSTRUCTIONS.md", "rule")
    write(root, "plugins/local.js", "dangerous()")
    result, data, dump = run(tmp_path, "opencode", root)
    assert result["status"] == "available"
    assert {"skill", "rule", "mcp", "plugin"} == {item["type"] for item in data["items"]}
    assert next(item for item in data["items"] if item["name"] == "search")["enabled"] == 0
    assert "private-arg" not in dump and "private-option" not in dump and "never/open" not in dump


def test_hermes_profiles_hooks_plugins_cron_and_disabled_skills(tmp_path):
    root = tmp_path / "hermes"
    write(
        root,
        "config.yaml",
        """mcp_servers:
  search:
    command: tool
    env: {TOKEN: private-token}
plugins:
  enabled: [demo]
  disabled: [demo]
skills:
  disabled: [review]
""",
    )
    write(root, "skills/review/SKILL.md", "secret body")
    write(root, "plugins/demo/plugin.yaml", "name: demo\nprovides_hooks: [agent:start]")
    write(root, "hooks/notify/HOOK.yaml", "name: notify\nevents: [agent:end]")
    write(root, "hooks/notify/handler.py", 'raise Exception("DO NOT EXECUTE")')
    write(
        root,
        "cron/jobs.json",
        {
            "jobs": [
                {
                    "id": "a",
                    "name": "Daily",
                    "enabled": True,
                    "state": "paused",
                    "prompt": "private-task",
                }
            ]
        },
    )
    write(
        root,
        "profiles/coder/config.yaml",
        'mcp_servers:\n  other: {url: "https://example.test", enabled: false}',
    )
    write(root, "profiles/coder/SOUL.md", "private profile")
    result, data, dump = run(tmp_path, "hermes", root)
    assert result["status"] == "available"
    assert {item["type"] for item in data["items"]} == set(SUPPORTED["hermes"])
    assert {
        item["enabled"]
        for item in data["items"]
        if item["name"] in ("demo", "review", "Daily", "other")
    } == {0}
    assert not any(
        secret in dump
        for secret in ("private-token", "private-task", "private profile", "DO NOT EXECUTE")
    )


def test_dsh_profiles_bundles_patches_and_schedule(tmp_path):
    root = tmp_path / "dsh"
    hooks_path = write(
        root,
        "my-hooks.json",
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "private-command"}]}]}},
    )
    write(root, "profiles/web/package.json", {"dsh": {"profile": {"bundles": ["bundle-demo"]}}})
    write(
        root,
        "profiles/web/node_modules/bundle-demo/package.json",
        {"name": "bundle-demo", "dsh": {"bundle": {"patch": "cordis.patch.yml"}}},
    )
    write(
        root,
        "profiles/web/node_modules/bundle-demo/cordis.patch.yml",
        '- insert:\n  - id: search\n    name: "@deepseek-ai/dsh-mcp-client"\n    config: {serverName: search, command: tool, env: {TOKEN: private-token}}',
    )
    write(
        root,
        "profiles/web/cordis.patch.yml",
        [
            {
                "insert": [
                    {
                        "id": "hook",
                        "name": "@deepseek-ai/dsh-hooks-claude-code",
                        "config": {"configPath": str(hooks_path)},
                    },
                    {"id": "disabled", "name": "other-plugin", "disabled": True},
                ]
            }
        ],
    )
    write(root, "skills/check/SKILL.md", "skill")
    write(root, "AGENTS.md", "rule")
    write(
        root,
        "storages/schedule.json",
        {
            "unit": {"name": "schedule", "version": 1},
            "tables": {
                "tasks": {
                    "x": {
                        "sessionId": "s",
                        "status": "inactive",
                        "record": {"id": "x", "title": "Daily", "prompt": "private-prompt"},
                    }
                }
            },
        },
    )
    result, data, dump = run(tmp_path, "dsh", root)
    assert result["status"] == "available"
    assert {item["type"] for item in data["items"]} == set(SUPPORTED["dsh"])
    assert next(item for item in data["items"] if item["name"] == "Daily")["enabled"] == 0
    assert (
        "private-token" not in dump
        and "private-command" not in dump
        and "private-prompt" not in dump
    )


def test_kimi_registry_components_and_cron_delete_fold(tmp_path):
    root = tmp_path / "kimi"
    plugin = root / "plugins/managed/demo"
    write(root, "config.toml", '[[hooks]]\nevent="Stop"\ncommand="private-command"')
    write(
        root,
        "plugins/installed.json",
        {"version": 1, "plugins": [{"id": "demo", "root": str(plugin), "enabled": False}]},
    )
    write(
        plugin,
        "kimi.plugin.json",
        {
            "name": "demo",
            "skills": ["./skills"],
            "mcpServers": {"remote": {"url": "https://user:secret@example.test"}},
            "hooks": [{"event": "PreToolUse", "command": "private-command"}],
            "systemPrompt": "private-prompt",
        },
    )
    write(plugin, "skills/review/SKILL.md", "private-skill")
    agent = root / "sessions/project/session/agents/main"
    write(
        agent,
        "cron/old.json",
        {"id": "old", "cron": "* * * * *", "prompt": "private-task", "createdAt": 1},
    )
    write(
        agent,
        "wire.jsonl",
        "\n".join(
            json.dumps(event)
            for event in [
                {"type": "message", "text": "private message"},
                {"type": "cron.delete", "ids": ["old"]},
                {
                    "type": "cron.add",
                    "task": {
                        "id": "new",
                        "cron": "* * * * *",
                        "prompt": "private-task",
                        "createdAt": 2,
                    },
                },
            ]
        ),
    )
    result, data, dump = run(tmp_path, "kimi", root)
    assert result["status"] == "available"
    assert {item["type"] for item in data["items"]} == set(SUPPORTED["kimi"])
    assert [item["name"] for item in data["items"] if item["type"] == "scheduled_task"] == ["new"]
    components = [item for item in data["items"] if item["config"].get("plugin") == "demo"]
    assert components and all(item["enabled"] == 0 for item in components)
    assert not any(
        secret in dump
        for secret in (
            "private-command",
            "private-prompt",
            "private-skill",
            "private-task",
            "private message",
            "user:secret",
        )
    )


@pytest.mark.parametrize(
    "payload",
    [
        '!!python/object/apply:os.system ["touch /tmp/never"]',
        "a: &a [*a]",
        "mcp_servers: {1: {}, text: {}}",
    ],
)
def test_unsafe_or_invalid_yaml_is_partial_without_execution(tmp_path, payload):
    root = tmp_path / "hermes"
    write(root, "config.yaml", payload)
    write(root, "AGENTS.md", "still observed")
    result, data, dump = run(tmp_path, "hermes", root)
    assert result["status"] == "partial"
    assert any(item["type"] == "rule" for item in data["items"])
    assert "touch /tmp/never" not in dump


def test_dsh_expressions_are_inert_and_static_siblings_survive(tmp_path):
    root = tmp_path / "dsh"
    write(
        root,
        "cordis.patch.yml",
        "- insert:\n  - name: demo\n    config:\n      value: !!js process.exit(1)",
    )
    result, data, dump = run(tmp_path, "dsh", root)
    assert result["status"] == "partial"
    assert any(item["name"] == "demo" for item in data["items"])
    assert "process.exit" not in dump
    assert any(row["code"] == "dynamic_yaml_expression" for row in result["diagnostics"])


def test_external_references_and_opencode_wrong_root_report_partial(tmp_path):
    root = tmp_path / "opencode"
    write(
        root,
        "opencode.json",
        {"skills": ["https://example.test/skills"], "instructions": ["../not-authorized.md"]},
    )
    result, _, _ = run(tmp_path, "opencode", root)
    assert result["status"] == "partial"
    assert {row["code"] for row in result["diagnostics"]} >= {
        "unresolved_reference",
        "unauthorized_reference",
    }
    (root / "opencode.json").unlink()
    write(root, "opencode.db", "do not open")
    result, _, _ = run(tmp_path, "opencode", root)
    assert result["diagnostics"][0]["code"] == "expected_opencode_config_root"


def test_credentials_symlink_blocked_but_oauth_plugin_name_allowed(tmp_path):
    root = tmp_path / "hermes"
    secret = write(root, "credentials/secret.json", "DO NOT OPEN")
    (root / "config.yaml").symlink_to(secret)
    write(root, "plugins/oauth-helper/plugin.yaml", "name: oauth-helper")
    result, data, dump = run(tmp_path, "hermes", root)
    assert result["status"] == "partial"
    assert any(item["name"] == "oauth-helper" for item in data["items"])
    assert "DO NOT OPEN" not in dump


def test_native_agent_project_scope_and_cli_choices(tmp_path, capsys):
    from orbit_data.cli import main

    root = tmp_path / "pi"
    write(root, "AGENTS.md", "project rule")
    with Store(tmp_path / "data") as store:
        store.db.execute(
            "INSERT INTO project(project_id,key_type,key,name) VALUES('p','path','/fictional','P')"
        )
        scan_inventory(store, InventoryRequest("pi", root, project_id="p"))
        assert read_inventory(store.home, project_ids=[])["items"] is None
        assert read_inventory(store.home, project_ids=["p"])["items"][0]["scope"] == "project"
    main(["--home", str(tmp_path / "data"), "scan-inventory", "--agent", "pi", "--root", str(root)])
    assert json.loads(capsys.readouterr().out)["status"] == "available"


def test_yaml_profile_corruption_isolated_from_valid_sibling(tmp_path):
    root = tmp_path / "hermes"
    write(root, "profiles/bad/config.yaml", "mcp_servers: [broken")
    write(root, "profiles/good/config.yaml", "mcp_servers: {ok: {command: tool}}")
    write(root, "plugins/platforms/demo/plugin.yaml", "name: demo")
    write(root, "plugins/platforms/demo/skills/deep/SKILL.md", "skill")
    result, data, _ = run(tmp_path, "hermes", root)
    assert result["status"] == "partial"
    assert {"ok", "platforms/demo", "deep"} <= {item["name"] for item in data["items"]}
    assert all(issue["code"] != "depth_limit" for issue in result["diagnostics"])


def test_kimi_current_scan_removes_deleted_cron_and_bad_records_are_partial(tmp_path):
    root = tmp_path / "kimi"
    path = write(
        root,
        "sessions/p/s/agents/main/wire.jsonl",
        json.dumps({"type": "cron.add", "task": {"id": "x", "prompt": "private"}}),
    )
    with Store(tmp_path / "data") as store:
        request = InventoryRequest("kimi", root)
        scan_inventory(store, request)
        assert len(read_inventory(store.home)["items"]) == 1
        path.write_text(path.read_text() + "\n" + json.dumps({"type": "cron.delete", "ids": ["x"]}))
        scan_inventory(store, request)
        assert read_inventory(store.home)["items"] == []
        path.write_text('{"type":"cron.delete","ids":null}\nnot json')
        result = scan_inventory(store, request)
        assert result["coverage"]["scheduled_task"]["status"] == "partial"
        assert len(result["diagnostics"]) == 2


def test_claude_commands_and_agents_are_inventoried_as_their_own_types(tmp_path):
    root = tmp_path / "claude"
    write(root, "commands/review.md", "Review the diff")
    write(root, "commands/git/commit.md", "---\ndescription: commit\n---\nCommit")
    write(root, "commands/notes.txt", "not a command")
    write(root, "agents/researcher.md", "---\nname: deep-researcher\ndescription: d\n---\nbody")
    write(root, "agents/plain.md", "no frontmatter")
    result, data, dump = run(tmp_path, "claude_code", root)
    found = {(item["type"], item["name"]) for item in data["items"] if item["type"] != "rule"}
    assert found == {
        ("command", "review"),
        ("command", "git:commit"),
        ("agent", "deep-researcher"),
        ("agent", "plain"),
    }
    assert "Review the diff" not in dump and "body" not in dump
    assert result["coverage"]["skill"]["rows"] == 0
    assert result["coverage"]["command"] == {"status": "available", "rows": 2, "reason": None}
    assert result["coverage"]["agent"] == {"status": "available", "rows": 2, "reason": None}
    # ~/.claude.json was not passed: user-scope MCP servers are not represented.
    assert result["coverage"]["mcp"]["reason"] == "user_scope_not_scanned"


def test_claude_plugin_commands_and_agents_are_namespaced_by_plugin(tmp_path):
    root = tmp_path / "claude"
    write(root, "settings.json", {"enabledPlugins": {"tools@market": True}})
    plugin = root / "plugins/cache/market/tools/1.0.0"
    write(plugin, ".claude-plugin/plugin.json", {"name": "tools"})
    write(plugin, "commands/ship.md", "Ship it")
    write(plugin, "agents/checker.md", "---\nname: checker\n---\nbody")
    _, data, _ = run(tmp_path, "claude_code", root)
    found = {
        (item["type"], item["name"], item["config"].get("plugin"))
        for item in data["items"]
        if item["type"] in ("command", "agent")
    }
    assert found == {
        ("command", "tools:ship", "tools@market"),
        ("agent", "tools:checker", "tools@market"),
    }


def test_codex_plugin_cache_does_not_list_claude_markdown_components(tmp_path):
    root = tmp_path / "codex"
    plugin = root / "plugins/cache/market/tools/1.0.0"
    write(plugin, ".codex-plugin/plugin.json", {"name": "tools"})
    write(plugin, "commands/ship.md", "Ship it")
    _, data, _ = run(tmp_path, "codex", root)
    assert not [item for item in data["items"] if item["type"] in ("command", "agent")]


def test_migration_015_retypes_scanner_130_command_and_agent_rows(tmp_path):
    """A v14 library keeps its earlier observations; component-marked skills become typed."""
    import sqlite3

    with Store(tmp_path / "data") as store:
        scan = store.db.execute(
            "INSERT INTO inventory_scan(source_key,agent,root_path,scope,observed_at,"
            "scanner_version,coverage,diagnostics) VALUES('k','claude_code','/r','global',1,"
            "'1.3.0','{}','[]')"
        ).lastrowid
    db = sqlite3.connect(tmp_path / "data/orbit.db")
    db.executescript(
        "DROP TABLE inventory_item;"
        "CREATE TABLE inventory_item (scan_id INTEGER NOT NULL REFERENCES inventory_scan,"
        " inv_id TEXT NOT NULL, type TEXT NOT NULL CHECK(type IN"
        " ('skill','mcp','hook','plugin','rule','scheduled_task')), name TEXT NOT NULL,"
        " config_path TEXT NOT NULL, locator TEXT NOT NULL, enabled INTEGER CHECK(enabled IN (0,1)),"
        " evidence TEXT NOT NULL CHECK(evidence IN ('file','configured','cached','installed')),"
        " config TEXT NOT NULL CHECK(json_valid(config)), content_hash TEXT NOT NULL,"
        " PRIMARY KEY(scan_id, inv_id)) STRICT;"
        "UPDATE schema_manifest SET schema_version=14; PRAGMA user_version=14;"
    )
    rows = [
        ("i1", "skill", "review", '{"component":"command"}'),
        ("i2", "skill", "helper", '{"component":"agent"}'),
        ("i3", "skill", "dataviz", "{}"),
        ("i4", "mcp", "docs", '{"component":"command"}'),
    ]
    db.executemany(
        "INSERT INTO inventory_item VALUES(?,?,?,?,'/p','',NULL,'file',?,'h')",
        [(scan, inv, kind, name, config) for inv, kind, name, config in rows],
    )
    db.commit()
    db.close()
    with Store(tmp_path / "data") as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] >= 15
        typed = dict(store.db.execute("SELECT inv_id,type FROM inventory_item"))
        # Only skill rows carrying a command/agent component marker change type.
        assert typed == {"i1": "command", "i2": "agent", "i3": "skill", "i4": "mcp"}
        store.db.execute(
            "INSERT INTO inventory_item VALUES(?,?,?,?,'/p','',NULL,'file','{}','h')",
            (scan, "i5", "command", "new"),
        )


def test_claude_mcp_coverage_has_no_gap_reason_when_user_config_is_scanned(tmp_path):
    root = tmp_path / "claude"
    root.mkdir()
    config = write(tmp_path, "claude.json", {"mcpServers": {"docs": {"command": "x"}}})
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("claude_code", root, claude_config=config))
    assert result["coverage"]["mcp"]["reason"] is None
    assert result["coverage"]["mcp"]["rows"] == 1
