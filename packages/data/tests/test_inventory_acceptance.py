"""Acceptance contracts: independent expected facts, real SQLite, synthetic inputs only.

Case IDs and acceptance criteria are maintained in docs/modules/data/inventory-testing.md.
No test enables a real HOME, invokes a plugin, or downloads a configured resource.
"""

import hashlib
import json
import os
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import validate

from orbit_data.cli import main
from orbit_data.inventory import (
    InventoryRequest,
    read_inventory,
    read_inventory_connection,
    scan_inventory,
)
from orbit_data.service import ImportService
from orbit_data.store import Store, readonly_connection

# Expected observations are authored independently of the scanner's registry.
NATIVE_MCP = [
    (
        "codex",
        "config.toml",
        '[mcp_servers.sample]\ncommand="tool"\nenabled=false',
        "AGENTS.md",
        {"skill", "mcp", "hook", "plugin", "rule", "scheduled_task", "command"},
    ),
    (
        "claude_code",
        ".mcp.json",
        '{"mcpServers":{"sample":{"command":"tool","disabled":true}}}',
        "CLAUDE.md",
        {"skill", "mcp", "hook", "plugin", "rule", "command", "agent"},
    ),
    (
        "dsh",
        "cordis.patch.yml",
        '- insert:\n  - name: "@deepseek-ai/dsh-mcp-client"\n    disabled: true\n    config: {serverName: sample, command: tool}',
        "AGENTS.md",
        {"skill", "mcp", "hook", "plugin", "rule", "scheduled_task"},
    ),
    (
        "pi",
        "mcp.json",
        '{"mcpServers":{"sample":{"command":"tool","disabled":true}}}',
        "AGENTS.md",
        {"skill", "mcp", "plugin", "rule"},
    ),
    (
        "hermes",
        "config.yaml",
        "mcp_servers: {sample: {command: tool, enabled: false}}",
        "AGENTS.md",
        {"skill", "mcp", "hook", "plugin", "rule", "scheduled_task"},
    ),
    (
        "opencode",
        "opencode.jsonc",
        '{/*comment*/ "mcp":{"sample":{"type":"local","command":["tool"],"enabled":false}},}',
        "AGENTS.md",
        {"skill", "mcp", "plugin", "rule", "command", "agent"},
    ),
    (
        "kimi",
        "mcp.json",
        '{"mcpServers":{"sample":{"command":"tool","enabled":false}}}',
        "AGENTS.md",
        {"skill", "mcp", "hook", "plugin", "rule", "scheduled_task"},
    ),
]
ALL_KINDS = {"skill", "mcp", "hook", "plugin", "rule", "scheduled_task", "command", "agent"}


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict | list) else value)
    return path


def source_snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize(
    "agent,filename,content,rule,supported", NATIVE_MCP, ids=[row[0] for row in NATIVE_MCP]
)
def test_acceptance_native_cli_facts_coverage_and_source_readonly(
    tmp_path, capsys, monkeypatch, agent, filename, content, rule, supported
):
    """INV-01: real CLI dispatch yields independently specified facts and coverage."""

    def forbidden_side_effect(*args, **kwargs):
        pytest.fail("Inventory scanning must not execute processes or connect to resources")

    monkeypatch.setattr("subprocess.Popen", forbidden_side_effect)
    monkeypatch.setattr("socket.create_connection", forbidden_side_effect)
    monkeypatch.setattr("os.system", forbidden_side_effect)
    root, home = tmp_path / "source", tmp_path / "data"
    write(root, filename, content)
    write(root, rule, "synthetic instruction body")
    before = source_snapshot(root)
    observations = []
    for _ in range(2):
        main(["--home", str(home), "scan-inventory", "--agent", agent, "--root", str(root)])
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "available"
        assert set(result["coverage"]) == ALL_KINDS
        for kind in ALL_KINDS:
            expected = "available" if kind in supported else "unavailable"
            assert result["coverage"][kind]["status"] == expected
            if expected == "unavailable":
                assert result["coverage"][kind]["rows"] is None
        main(["--home", str(home), "inventory"])
        data = json.loads(capsys.readouterr().out)
        servers = [item for item in data["items"] if item["type"] == "mcp"]
        assert [
            (item["name"], item["enabled"], item["agent"], item["evidence"]) for item in servers
        ] == [("sample", 0, agent, "configured")]
        assert len([item for item in data["items"] if item["type"] == "rule"]) == 1
        assert data["coverage"]["rows"] == len(data["items"])
        assert all(item["scan_id"] == result["scan_id"] for item in data["items"])
        observations.append({item["inv_id"]: item["content_hash"] for item in data["items"]})
    assert observations[0] == observations[1]
    assert source_snapshot(root) == before
    with readonly_connection(home / "orbit.db") as db:
        assert db.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0] == 0
    assert not list((home / "raw").iterdir())


def test_acceptance_content_changes_keep_identity_and_isolate_sources(tmp_path, monkeypatch):
    """INV-02: content versioning and last-observation selection are per source."""
    first, second = tmp_path / "first", tmp_path / "second"
    path = write(first, "AGENTS.md", "old")
    write(second, "AGENTS.md", "other")
    clock = iter((100, 200, 200))  # Equal timestamps must still have a stable last scan.
    monkeypatch.setattr("orbit_data.inventory.now_ms", lambda: next(clock))
    with Store(tmp_path / "data") as store:
        scan_inventory(store, InventoryRequest("codex", first))
        old = read_inventory(store.home)["items"][0]
        scan_inventory(store, InventoryRequest("pi", second))
        path.write_text("new")
        scan_inventory(store, InventoryRequest("codex", first))
        current = read_inventory(store.home)
        assert len(current["items"]) == 2
        changed = next(item for item in current["items"] if item["agent"] == "codex")
        assert changed["inv_id"] == old["inv_id"]
        assert changed["content_hash"] == hashlib.sha256(b"new").hexdigest()
        assert old["content_hash"] == hashlib.sha256(b"old").hexdigest()
        assert read_inventory(store.home, until_ts=200)["items"] == [old]
        assert len(read_inventory(store.home, until_ts=201)["items"]) == 2
        assert store.db.execute("SELECT COUNT(*) FROM inventory_item").fetchone()[0] == 3


def test_acceptance_reader_snapshot_and_single_writer(tmp_path):
    """INV-03: readers see an atomic snapshot; a competing writer publishes nothing."""
    root = tmp_path / "source"
    path = write(root, "AGENTS.md", "old")
    with Store(tmp_path / "data") as store:
        request = InventoryRequest("codex", root)
        scan_inventory(store, request)
        with readonly_connection(store.db_path) as reader:
            reader.execute("BEGIN")
            before = read_inventory_connection(reader)
            path.write_text("new")
            scan_inventory(store, request)
            assert read_inventory_connection(reader) == before
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                reader.execute("DELETE FROM inventory_scan")
        assert (
            read_inventory(store.home)["items"][0]["content_hash"]
            != before["items"][0]["content_hash"]
        )
        count = store.db.execute("SELECT COUNT(*) FROM inventory_scan").fetchone()[0]
        with ImportService(store).writer():
            with pytest.raises(RuntimeError, match="Another import worker"):
                scan_inventory(store, request)
        assert store.db.execute("SELECT COUNT(*) FROM inventory_scan").fetchone()[0] == count


@pytest.mark.parametrize(
    "column,value",
    [
        ("type", "invented"),
        ("evidence", "assumed"),
        ("enabled", 2),
        ("config", "{not-json"),
        ("scan_id", 9999),
    ],
)
def test_acceptance_sql_contract_rejects_invalid_facts(tmp_path, column, value):
    """INV-04: invalid kinds, states, JSON and foreign references cannot enter storage."""
    root = tmp_path / "source"
    write(root, "AGENTS.md", "rule")
    with Store(tmp_path / "data") as store:
        scan_inventory(store, InventoryRequest("codex", root))
        before = read_inventory(store.home)
        with pytest.raises(sqlite3.IntegrityError):
            store.db.execute(f"UPDATE inventory_item SET {column}=?", (value,))
        assert read_inventory(store.home) == before
        dictionary = json.loads(
            files("orbit_data").joinpath("schemas/tables-v1.schema.json").read_text()
        )
        for table, json_columns in [
            ("inventory_item", ("config",)),
            ("inventory_scan", ("coverage", "diagnostics")),
        ]:
            row = dict(store.db.execute(f"SELECT * FROM {table}").fetchone())
            for key in json_columns:
                row[key] = json.loads(row[key])
            validate(row, dictionary["$defs"][table])


@pytest.mark.parametrize(
    "enabled,expected", [(True, 1), (False, 0), (None, None), (0, None), ("false", None)]
)
def test_acceptance_unknown_enablement_is_not_false(tmp_path, enabled, expected):
    """INV-05: only native booleans establish an enablement flag."""
    root = tmp_path / "source"
    write(root, "mcp.json", {"mcpServers": {"server": {"enabled": enabled}}})
    with Store(tmp_path / "data") as store:
        scan_inventory(store, InventoryRequest("pi", root))
        assert read_inventory(store.home)["items"][0]["enabled"] == expected


@pytest.mark.parametrize(
    "credential",
    [
        "auth.json",
        "mcp-auth.json",
        ".env",
        ".env.local",
        ".credentials.yaml",
        "credentials/token.json",
        "backups/config.json",
        "oauth_creds.json",
        "key.key",
    ],
)
def test_acceptance_credential_targets_never_opened(tmp_path, monkeypatch, credential):
    """INV-06: even explicitly allowed linked credential files remain forbidden."""
    root, external = tmp_path / "source", tmp_path / "external"
    root.mkdir()
    secret = write(external, credential, "DO-NOT-OPEN")
    (root / "AGENTS.md").symlink_to(secret)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != secret
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("codex", root, allowed_roots=(external,)))
        assert result["coverage"]["rule"]["status"] == "partial"
        assert read_inventory(store.home)["items"] == []
        assert "DO-NOT-OPEN" not in "\n".join(store.db.iterdump())


def test_acceptance_fifo_and_invalid_utf8_do_not_block_or_abort(tmp_path):
    """INV-07: non-regular inputs are rejected before open; decoding errors are isolated."""
    root = tmp_path / "source"
    root.mkdir()
    os.mkfifo(root / "config.toml")
    (root / "hooks.json").write_bytes(b"\xff\xfeinvalid")
    write(root, "AGENTS.md", "valid")
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("codex", root))
        assert {issue["code"] for issue in result["diagnostics"]} >= {
            "not_regular_file",
            "invalid_document",
        }
        assert [item["name"] for item in read_inventory(store.home)["items"]] == ["AGENTS.md"]


@pytest.mark.parametrize("boundary", ["file", "entries", "depth", "structure"])
def test_acceptance_resource_limits_publish_partial(tmp_path, monkeypatch, boundary):
    """INV-08: resource limits are coverage failures, never complete empty observations."""
    root = tmp_path / "source"
    root.mkdir()
    if boundary == "file":
        monkeypatch.setattr("orbit_data.inventory.reader.MAX_BYTES", 16)
        write(root, "config.toml", "x" * 17)
        code, kind = "file_too_large", "mcp"
    elif boundary == "entries":
        monkeypatch.setattr("orbit_data.inventory.reader.MAX_ENTRIES", 2)
        for name in ("one", "two", "three"):
            write(root, f"skills/{name}/SKILL.md", name)
        code, kind = "entry_limit", "skill"
    elif boundary == "depth":
        write(root, "skills/a/b/c/d/e/f/g/SKILL.md", "deep")
        code, kind = "depth_limit", "skill"
    else:
        nested = {}
        for _ in range(70):
            nested = {"nested": nested}
        write(root, "hooks.json", nested)
        code, kind = "invalid_document", "hook"
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("codex", root))
        assert result["coverage"][kind]["status"] == "partial"
        assert any(row["code"] == code for row in result["diagnostics"])


@pytest.mark.parametrize(
    "agent,filename,document",
    [
        ("pi", "settings.json", {"packages": ["https://[invalid"], "skills": []}),
        ("opencode", "opencode.json", {"instructions": ["https://[invalid"]}),
    ],
)
def test_acceptance_malformed_urls_do_not_abort_valid_siblings(tmp_path, agent, filename, document):
    """INV-09: malformed references are diagnostic; unrelated files still publish."""
    root = tmp_path / "source"
    write(root, filename, document)
    write(root, "AGENTS.md", "valid")
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest(agent, root))
        assert result["status"] == "partial"
        assert any(row["code"] == "invalid_reference" for row in result["diagnostics"])
        assert any(item["name"] == "AGENTS.md" for item in read_inventory(store.home)["items"])


def test_acceptance_unresolvable_home_reference_is_diagnostic(tmp_path, monkeypatch):
    """INV-10: user-relative paths must not abort a scan when expansion fails."""
    root = tmp_path / "source"
    write(root, "settings.json", {"skills": ["~synthetic-missing-user/skills"]})
    write(root, "AGENTS.md", "valid")
    original = Path.expanduser

    def expand(path):
        if str(path).startswith("~synthetic-missing-user"):
            raise RuntimeError("cannot expand synthetic user")
        return original(path)

    monkeypatch.setattr(Path, "expanduser", expand)
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("pi", root))
        assert result["coverage"]["skill"]["status"] == "partial"
        assert any(item["name"] == "AGENTS.md" for item in read_inventory(store.home)["items"])


@pytest.mark.parametrize("input_kind", ["hook", "bundle_patch"])
def test_acceptance_missing_explicit_dsh_inputs_are_not_known_empty(tmp_path, input_kind):
    """INV-11: absent optional discovery paths differ from missing declared inputs."""
    root = tmp_path / "source"
    if input_kind == "hook":
        write(
            root,
            "cordis.patch.yml",
            [
                {
                    "insert": [
                        {
                            "name": "@deepseek-ai/dsh-hooks-claude-code",
                            "config": {"configPath": str(root / "missing.json")},
                        }
                    ]
                }
            ],
        )
        kind = "hook"
    else:
        write(root, "package.json", {"dsh": {"profile": {"bundles": ["sample"]}}})
        write(
            root,
            "node_modules/sample/package.json",
            {
                "name": "sample",
                "dsh": {"bundle": {"patch": "missing.patch.yml"}},
            },
        )
        kind = "plugin"
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest("dsh", root))
        assert result["coverage"][kind]["status"] == "partial"
        assert any(row["code"] == "missing_reference" for row in result["diagnostics"])


@pytest.mark.parametrize("source_of_overlap", ["root", "allow-root"])
def test_acceptance_cli_rejects_source_overlap_before_creating_database(
    tmp_path, source_of_overlap
):
    """INV-12: invalid destinations must fail before any source-directory writes."""
    root = tmp_path / "source"
    root.mkdir()
    allowed = tmp_path / "shared"
    allowed.mkdir()
    home = (root if source_of_overlap == "root" else allowed) / "orbit-data"
    args = ["--home", str(home), "scan-inventory", "--agent", "codex", "--root", str(root)]
    if source_of_overlap == "allow-root":
        args += ["--allow-root", str(allowed)]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert not home.exists()


def test_acceptance_old_database_read_does_not_implicitly_migrate(tmp_path):
    """INV-13: read-only compatibility yields unavailable until an explicit writer upgrade."""
    home = tmp_path / "data"
    home.mkdir()
    with sqlite3.connect(home / "orbit.db") as db:
        for name in ("001.sql", "002.sql", "003.sql", "004.sql"):
            db.executescript(files("orbit_data").joinpath("migrations/" + name).read_text())
    result = read_inventory(home)
    assert result["items"] is None and result["coverage"]["status"] == "unavailable"
    with readonly_connection(home / "orbit.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='inventory_scan'"
        ).fetchone()


def test_acceptance_schema_names_do_not_change_existing_call_coverage():
    """INV-14: inventory additions must not change unrelated columns sharing a name."""
    from orbit_data.schema_export import table_schemas

    dictionary = json.loads(
        files("orbit_data").joinpath("schemas/tables-v1.schema.json").read_text()
    )
    assert dictionary == table_schemas()
    for table in ("model_call", "usage_snapshot"):
        assert dictionary["$defs"][table]["properties"]["coverage"]["type"] == "string"
    assert dictionary["$defs"]["inventory_scan"]["properties"]["coverage"]["type"] == "object"
    assert dictionary["$defs"]["inventory_item"]["properties"]["locator"]["type"] == "string"


@pytest.mark.parametrize(
    "agent,filename,payload,kind",
    [
        ("codex", "config.toml", '[[skills.config]]\nname="good"\nenabled=false\n', "skill"),
        ("claude_code", "settings.json", '{"hooks":[]}', "hook"),
        ("dsh", "cordis.patch.yml", "- insert: not-a-list", "plugin"),
        ("pi", "settings.json", '{"packages":{}}', "plugin"),
        ("hermes", "cron/jobs.json", '{"jobs":{}}', "scheduled_task"),
        ("opencode", "opencode.json", '{"mcp":[]}', "mcp"),
        ("kimi", "plugins/installed.json", '{"version":999,"plugins":[]}', "plugin"),
    ],
)
def test_acceptance_declared_shapes_and_future_versions(tmp_path, agent, filename, payload, kind):
    """INV-15: unsupported shapes are partial; a valid disabled declaration stays known."""
    root = tmp_path / "source"
    write(root, filename, payload)
    rule_name = "CLAUDE.md" if agent == "claude_code" else "AGENTS.md"
    write(root, rule_name, "healthy sibling")
    with Store(tmp_path / "data") as store:
        result = scan_inventory(store, InventoryRequest(agent, root))
        expected = "available" if agent == "codex" else "partial"
        assert result["coverage"][kind]["status"] == expected
        data = read_inventory(store.home)
        assert any(item["type"] == "rule" for item in data["items"])
        if agent == "codex":
            assert next(item for item in data["items"] if item["name"] == "good")["enabled"] == 0


def test_acceptance_failed_scan_recovery_replaces_diagnostics(tmp_path):
    """INV-16: latest successful snapshot clears errors without rewriting history."""
    root = tmp_path / "source"
    path = write(root, "config.toml", "broken=[")
    with Store(tmp_path / "data") as store:
        failed = scan_inventory(store, InventoryRequest("codex", root))
        path.write_text('[mcp_servers.healthy]\ncommand="tool"')
        recovered = scan_inventory(store, InventoryRequest("codex", root))
        result = read_inventory(store.home)
        # Only the kind Codex layouts never scan (agent) is incomplete.
        assert result["coverage"]["reason_counts"] == {"inventory_layout_incomplete": 1}
        assert result["scans"][0]["diagnostics"] == []
        assert result["scans"][0]["scan_id"] == recovered["scan_id"]
        old = store.db.execute(
            "SELECT diagnostics FROM inventory_scan WHERE scan_id=?", (failed["scan_id"],)
        ).fetchone()[0]
        assert json.loads(old)[0]["code"] == "invalid_document"
