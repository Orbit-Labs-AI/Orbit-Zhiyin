"""Synthetic installation trees only: no test discovers or opens the user's home."""

import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from orbit_data import SCHEMA_VERSION
from orbit_data.analysis_input import AnalysisScope, read_analysis
from orbit_data.cli import main
from orbit_data.inventory import InventoryRequest, read_inventory, scan_inventory
from orbit_data.inventory.reader import MAX_BYTES
from orbit_data.store import Store


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return target


def codex_tree(root):
    write(
        root,
        "config.toml",
        """
[mcp_servers.search]
command = "npx"
args = ["--token", "argument-secret"]
enabled = false
[mcp_servers.search.env]
API_KEY = "environment-secret"
[mcp_servers.remote]
url = "https://user:password@example.test/mcp?key=url-secret"
[mcp_servers.remote.http_headers]
Authorization = "Bearer header-secret"
[plugins."sample@market"]
enabled = false
[[skills.config]]
name = "review"
enabled = false
""",
    )
    write(root, "skills/review/SKILL.md", "name: review\nPRIVATE RULE CONTENT")
    write(root, "rules/default.rules", "RULE BODY")
    write(root, "AGENTS.md", "USER INSTRUCTIONS")
    write(
        root,
        "hooks.json",
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hook-secret"}]}]}},
    )
    write(
        root,
        "automations/daily/automation.toml",
        'name="Daily review"\nstatus="PAUSED"\nrrule="FREQ=DAILY"\nprompt="private-task-prompt"',
    )
    plugin = "plugins/cache/market/sample/1.0"
    write(root, plugin + "/.codex-plugin/plugin.json", {"name": "sample"})
    write(root, plugin + "/skills/cached/SKILL.md", "cached skill")
    write(root, plugin + "/.mcp.json", {"mcpServers": {"nested": {"command": "tool"}}})
    write(
        root,
        plugin + "/hooks/hooks.json",
        {"hooks": {"Start": [{"hooks": [{"type": "command", "command": "tool"}]}]}},
    )
    write(root, "auth.json", "DO NOT OPEN credential-secret")


def test_codex_six_types_and_no_sensitive_persistence(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    codex_tree(root)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path.name != "auth.json"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("codex", root))
        assert result["status"] == "available"
        data = read_inventory(store.home)
        # Codex has no subagent definitions to scan (prompts/ count as commands).
        assert data["coverage"]["reason_counts"] == {"inventory_layout_incomplete": 1}
        assert {item["type"] for item in data["items"]} == {
            "skill",
            "mcp",
            "hook",
            "plugin",
            "rule",
            "scheduled_task",
        }
        skill = next(
            item
            for item in data["items"]
            if item["name"] == "review" and item["evidence"] == "file"
        )
        assert skill["enabled"] == 0
        cached = [item for item in data["items"] if item["evidence"] == "cached"]
        assert {item["type"] for item in cached} == {"skill", "plugin", "mcp", "hook"}
        assert all(item["enabled"] == 0 for item in cached)
        dump = "\n".join(store.db.iterdump())
        for secret in (
            "argument-secret",
            "environment-secret",
            "url-secret",
            "header-secret",
            "hook-secret",
            "credential-secret",
            "private-task-prompt",
            "PRIVATE RULE CONTENT",
            "RULE BODY",
            "USER INSTRUCTIONS",
        ):
            assert secret not in dump
        assert not list(store.raw_dir.iterdir())
        store.rebuild()
        analysis = read_analysis(store.home, AnalysisScope("UTC"))
        assert analysis["inventory"] == data["items"]
        assert analysis["coverage"]["inventory"]["reason_counts"] == {
            "inventory_layout_incomplete": 1
        }
        assert analysis["sample_boundary"]["inventory_scan_ids"] == [result["scan_id"]]


def test_empty_missing_errors_and_deleted_items_are_distinct(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    root.mkdir()
    times = iter((100, 200, 300, 400))
    monkeypatch.setattr("orbit_data.inventory.now_ms", lambda: next(times))
    with Store(tmp_path / "data") as store:
        assert read_inventory(store.home)["items"] is None
        request = InventoryRequest("codex", root)
        scan_inventory(store, request)
        assert read_inventory(store.home)["items"] == []
        assert read_inventory(store.home)["coverage"]["reason_counts"] == {
            "inventory_layout_incomplete": 1  # agent: Codex has no subagent definitions
        }
        path = write(root, "skills/one/SKILL.md", "one")
        scan_inventory(store, request)
        previous = read_inventory(store.home)["items"][0]
        path.unlink()
        scan_inventory(store, request)
        assert read_inventory(store.home)["items"] == []
        historical = read_inventory(store.home, until_ts=300)
        assert historical["items"][0]["inv_id"] == previous["inv_id"]
        assert read_inventory(store.home, until_ts=100)["items"] is None
        write(root, "config.toml", "INVALID = [")
        write(root, "skills/good/SKILL.md", "good")
        result = scan_inventory(store, request)
        assert result["status"] == "partial"
        assert result["diagnostics"][0]["code"] == "invalid_document"
        current = read_inventory(store.home)
        assert current["coverage"]["status"] == "partial"
        assert any(item["name"] == "good" for item in current["items"])
        assert store.db.execute("SELECT COUNT(*) FROM inventory_scan").fetchone()[0] == 4


def test_symlink_authorization_cycles_and_credential_targets(tmp_path):
    root = tmp_path / "codex"
    shared = tmp_path / "shared"
    write(shared, "review/SKILL.md", "shared skill")
    (root / "skills").mkdir(parents=True)
    (root / "skills/review").symlink_to(shared / "review", target_is_directory=True)
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("codex", root))
        assert result["coverage"]["skill"]["status"] == "partial"
        assert read_inventory(store.home)["items"] == []
        result = scan_inventory(store, InventoryRequest("codex", root, allowed_roots=(shared,)))
        assert result["coverage"]["skill"]["status"] == "available"
        assert read_inventory(store.home)["items"][0]["name"] == "review"
        (root / "skills/loop").symlink_to(root / "skills", target_is_directory=True)
        secret = write(root, "auth.json", "secret")
        (root / "AGENTS.md").symlink_to(secret)
        result = scan_inventory(store, InventoryRequest("codex", root, allowed_roots=(shared,)))
        assert {issue["code"] for issue in result["diagnostics"]} >= {
            "symlink_cycle",
            "credential_path",
        }
        assert "secret" not in "\n".join(store.db.iterdump())


def test_claude_and_explicit_account_file_only_extract_mcp(tmp_path):
    root = tmp_path / "claude"
    write(
        root,
        "settings.json",
        {
            "enabledPlugins": {"demo@market": False},
            "disableAllHooks": True,
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo private"}]}]},
        },
    )
    write(
        root,
        "plugins/installed_plugins.json",
        {
            "version": 2,
            "plugins": {"demo@market": [{"scope": "user", "installPath": "/do/not/follow"}]},
        },
    )
    write(root, "skills/example/SKILL.md", "example")
    write(root, "rules/code.md", "rule")
    config = write(
        tmp_path,
        ".claude.json",
        {
            "oauthAccount": {"email": "private-account"},
            "mcpServers": {"global": {"command": "cli", "env": {"SECRET": "private-secret"}}},
            "projects": {"/fictional/project": {"mcpServers": {"local": {"command": "tool"}}}},
        },
    )
    with Store(tmp_path / "data") as store:
        scan_inventory(store, InventoryRequest("claude_code", root))
        assert not any(item["type"] == "mcp" for item in read_inventory(store.home)["items"])
        result = scan_inventory(store, InventoryRequest("claude_code", root, claude_config=config))
        assert result["coverage"]["scheduled_task"]["status"] == "unavailable"
        data = read_inventory(store.home)
        assert {item["name"] for item in data["items"] if item["type"] == "mcp"} == {
            "global",
            "local",
        }
        assert next(item for item in data["items"] if item["type"] == "hook")["enabled"] == 0
        dump = "\n".join(store.db.iterdump())
        assert "private-account" not in dump and "private-secret" not in dump
        assert any(item["evidence"] == "installed" for item in data["items"])


def test_project_scope_and_common_layout(tmp_path):
    root = tmp_path / "project"
    write(root, "AGENTS.md", "project rule")
    write(root, ".mcp.json", {"mcpServers": {"project-mcp": {"url": "https://example.test"}}})
    write(root, ".claude/skills/check/SKILL.md", "check")
    common = tmp_path / "common"
    write(common, "AGENTS.md", "global rule")
    with Store(tmp_path / "data") as store:
        store.db.execute(
            "INSERT INTO project(project_id,key_type,key,name) VALUES('p','path','/fictional','fictional')"
        )
        scan_inventory(store, InventoryRequest("project", root, project_id="p"))
        scan_inventory(store, InventoryRequest("common", common))
        assert len(read_inventory(store.home)["items"]) == 4
        assert len(read_inventory(store.home, project_ids=[])["items"]) == 1
        assert len(read_inventory(store.home, project_ids=["p"])["items"]) == 4
        with pytest.raises(ValueError, match="Unknown project_id"):
            scan_inventory(store, InventoryRequest("project", root, project_id="missing"))
        assert store.db.execute("SELECT COUNT(*) FROM inventory_scan").fetchone()[0] == 2


def test_bounds_missing_root_and_cli(tmp_path, capsys):
    root = tmp_path / "codex"
    write(root, "config.toml", "a" * (MAX_BYTES + 1))
    home = tmp_path / "data"
    with pytest.raises(SystemExit) as error:
        main(["--home", str(home), "scan-inventory", "--agent", "codex", "--root", str(root)])
    assert error.value.code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["diagnostics"][0]["code"] == "file_too_large"
    main(["--home", str(home), "inventory"])
    assert json.loads(capsys.readouterr().out)["coverage"]["status"] == "partial"
    with Store(home) as store:
        result = scan_inventory(store, InventoryRequest("codex", tmp_path / "missing"))
        assert result["status"] == "partial"
        with pytest.raises(ValueError, match="outside"):
            scan_inventory(store, InventoryRequest("codex", tmp_path))
        with pytest.raises(ValueError, match="Unsupported"):
            scan_inventory(store, InventoryRequest("unknown", root))


def test_upgrade_from_v4_keeps_session_tables_and_inventory_survives_rebuild(tmp_path):
    home = tmp_path / "data"
    home.mkdir()
    with sqlite3.connect(home / "orbit.db") as connection:
        for name in ("001.sql", "002.sql", "003.sql", "004.sql"):
            connection.executescript(files("orbit_data").joinpath("migrations/" + name).read_text())
    root = tmp_path / "codex"
    write(root, "AGENTS.md", "rule")
    with Store(home) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        scan_inventory(store, InventoryRequest("codex", root))
        store.rebuild()
        assert len(read_inventory(home)["items"]) == 1
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_desktop_tasks_and_unknown_shape_remain_visible(tmp_path):
    root = tmp_path / "desktop"
    path = write(
        root,
        "account/scheduled-tasks.json",
        {"tasks": [{"id": "task", "name": "Daily", "enabled": False, "prompt": "private prompt"}]},
    )
    with Store(tmp_path / "data") as store:
        scan_inventory(store, InventoryRequest("claude_desktop", root))
        assert read_inventory(store.home)["items"][0]["enabled"] == 0
        path.write_text('{"unknown-layout": []}')
        result = scan_inventory(store, InventoryRequest("claude_desktop", root))
        assert result["coverage"]["scheduled_task"]["status"] == "partial"


def test_account_project_mcp_does_not_leak_into_other_project_scopes(tmp_path):
    root = tmp_path / "claude"
    root.mkdir()
    config = write(
        tmp_path,
        ".claude.json",
        {
            "mcpServers": {"global": {}},
            "projects": {
                "/fictional/a": {"mcpServers": {"a": {}}},
                "/fictional/b": {"mcpServers": {"b": {}}},
            },
        },
    )
    with Store(tmp_path / "data") as store:
        store.db.execute(
            "INSERT INTO project(project_id,key_type,key,name) VALUES('a','path','/fictional/a','A')"
        )
        scan_inventory(store, InventoryRequest("claude_code", root, claude_config=config))
        items = read_inventory(store.home, project_ids=["a"])["items"]
        assert {item["name"] for item in items} == {"global", "a"}
        assert next(item for item in items if item["name"] == "a")["scope"] == "project"
        assert {item["name"] for item in read_inventory(store.home, project_ids=[])["items"]} == {
            "global"
        }


def test_publication_is_atomic_when_writing_an_item_fails(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    write(root, "AGENTS.md", "rule")
    with Store(tmp_path / "data") as store:
        request = InventoryRequest("codex", root)
        scan_inventory(store, request)
        before = read_inventory(store.home)

        def fail(*args, **kwargs):
            raise sqlite3.IntegrityError("synthetic write failure")

        monkeypatch.setattr("orbit_data.inventory.insert", fail)
        with pytest.raises(sqlite3.IntegrityError):
            scan_inventory(store, request)
        assert read_inventory(store.home) == before
        assert store.db.execute("SELECT COUNT(*) FROM inventory_scan").fetchone()[0] == 1


def test_bad_entry_shapes_and_read_failure_are_isolated(tmp_path, monkeypatch):
    root = tmp_path / "codex"
    write(root, "config.toml", "mcp_servers=[]\nplugins=[]\n[skills]\nconfig=[1]")
    write(root, "automations/task/automation.toml", 'name=["bad"]\nstatus=["bad"]')
    write(root, "AGENTS.md", "rule")
    original = Path.open

    def denied(path, *args, **kwargs):
        if path.name == "AGENTS.md":
            raise PermissionError("private error text")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("codex", root))
        assert result["status"] == "partial"
        assert {issue["code"] for issue in result["diagnostics"]} >= {
            "invalid_mcp_servers",
            "invalid_plugins",
            "invalid_skill_config",
            "invalid_item_name",
            "PermissionError",
        }
        assert "private error text" not in "\n".join(store.db.iterdump())
