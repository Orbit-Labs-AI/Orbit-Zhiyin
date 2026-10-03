"""Install → recommend / AI / ledger links / env memo, over a tmp app.db and fabricated homes."""

import json
import sqlite3

import pytest

from orbit_backend.appdb import AppDB
from orbit_backend.install import env as envmod
from orbit_backend.install import store
from orbit_backend.install.service import InstallService

from .test_env import Reads
from .test_fetch import FakeFetcher
from .test_service import CATALOG


def make_inventory(path, items=()):
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE IF NOT EXISTS inventory_scan (scan_id INTEGER PRIMARY KEY, source_key TEXT, "
                         "agent TEXT); CREATE TABLE IF NOT EXISTS inventory_item (scan_id INTEGER, inv_id TEXT, "
                         "type TEXT, name TEXT, config_path TEXT);")
        db.execute("INSERT INTO inventory_scan (source_key, agent) VALUES ('k', 'claude_code')")
        scan = db.execute("SELECT MAX(scan_id) FROM inventory_scan").fetchone()[0]
        db.executemany("INSERT INTO inventory_item VALUES (?,?,?,?,?)", [(scan, *i) for i in items])


@pytest.fixture
def setup(tmp_path, env):
    db = AppDB(tmp_path / "orbit" / "app.db")
    calls = []
    tdb = tmp_path / "orbit.db"
    make_inventory(tdb)
    svc = InstallService(db, tmp_path / "orbit", env=env, fetcher=FakeFetcher(), catalog_lookup=CATALOG.get,
                         reads=Reads(tdb), artifact_status=lambda *a: calls.append(a))
    yield svc, tdb, calls
    db.close()


def add_candidate(appdb, cid="cand1", card=None):
    card = card or {"catalog_item_id": "docs-mcp", "target_agents": ["claude_code"], "problem": {"type": "x"}}
    with appdb.write() as db:
        db.execute("INSERT INTO rec_candidate (candidate_id, run_id, rec_key, kind, dim, title, passed, card, "
                   "created_at) VALUES (?, 'run1', 'rk1', 'mcp', 'd', 't', 1, ?, 1)", (cid, json.dumps(card)))


def run(svc, source, **kw):
    plan = svc.plan(source, agents=["claude_code"])
    preview = svc.preview(plan["plan_id"])
    return svc.apply(plan["plan_id"], preview["preview_digest"], **kw)


def test_candidate_install_tracks_exposes_links_and_reverts(setup):
    svc, tdb, _ = setup
    add_candidate(svc.appdb)
    result = run(svc, {"type": "candidate", "id": "cand1"}, surface="lite")
    assert result["state"] == "observing" and result["tracking_id"] and result["warnings"] == []
    rows = store.ledger_for(svc.appdb, result["install_id"])
    assert {r["catalog_item_id"] for r in rows if r["action"] == "install"} == {"docs-mcp"}
    with svc.appdb.read() as db:
        assert [tuple(r) for r in db.execute("SELECT surface, action FROM rec_exposure")] == [("lite", "install")]
        assert db.execute("SELECT status, install_id FROM rec_state").fetchone()[0] == "installed"
    assert svc.link_inventory() == 0  # inventory has not seen the server yet

    make_inventory(tdb, [("inv_docs", "mcp", "docs", str(svc.env.home / ".claude.json"))])
    svc.environment()  # later reads link it
    links = [r for r in store.ledger_for(svc.appdb, result["install_id"]) if r["action"] == "link"]
    assert [(r["inv_id"], r["catalog_item_id"]) for r in links] == [("inv_docs", "docs-mcp")]
    assert svc.link_inventory() == 0  # linked once

    svc.revert(result["install_id"])
    with svc.appdb.read() as db:
        assert db.execute("SELECT effect_status FROM tracking").fetchone()[0] == "reverted"
        assert db.execute("SELECT label FROM label").fetchone()[0] == "not_useful"


def test_kb_candidate_installs_through_its_kb_catalog_entry(setup):
    """A KB-origin card (the one slate hygiene keeps over its ``catalog:kb:<id>`` twin) plans
    from the ``kb:<id>`` entry the official orbit-kb source publishes."""
    svc, _, _ = setup
    hook = {"event": "PreToolUse", "matcher": "Bash", "command": "echo synthetic-guard",
            "id": "retry-breaker"}
    entry = {"id": "kb:retry-breaker", "kind": "hook", "name": "retry breaker",
             "install": {"hook": hook}, "license": {"spdx": "MIT"}}
    asked = []
    svc.catalog_lookup = lambda item_id: asked.append(item_id) or (entry if item_id == entry["id"] else None)
    add_candidate(svc.appdb, "cand-kb", {
        "source": {"origin": "kb", "item_id": "retry-breaker", "catalog_ref": None},
        "target_agents": ["claude_code"], "problem": {"type": "x"}})
    plan = svc.plan({"type": "candidate", "id": "cand-kb"}, agents=["claude_code"])
    assert plan["status"] == "ready" and asked == ["kb:retry-breaker"]
    assert plan["kind"] == "hook"


def test_unknown_candidate_warns_without_tracking(setup):
    svc, _, _ = setup
    with svc.appdb.write() as db:
        db.execute("CREATE TABLE candidate (candidate_id TEXT PRIMARY KEY, install_spec TEXT, catalog_item_id TEXT, "
                   "target_agents TEXT, scope TEXT, title TEXT)")
        db.execute("INSERT INTO candidate VALUES ('legacy', NULL, 'docs-mcp', NULL, NULL, 'x')")
    result = run(svc, {"type": "candidate", "id": "legacy"})
    assert result["state"] == "installed" and "tracking_unavailable" in result["warnings"]


def test_artifact_status_follows_apply_and_revert(setup):
    svc, _, calls = setup
    with svc.appdb.write() as db:
        db.execute("INSERT INTO ai_artifact (artifact_id, kind, template_id, name, title, slots, payload, files, "
                   "checks, personalized, content_hash, status, created_at, updated_at) "
                   "VALUES ('a1','rule','t','n','规范','{}',?,'[]','[]',0,'h','draft',1,1)",
                   (json.dumps({"kind": "rule", "payload": {"text": "Small commits.", "heading": "C"}}),))
    result = run(svc, {"type": "artifact", "id": "a1"})
    svc.revert(result["install_id"])
    assert calls == [("a1", "installed", result["install_id"]), ("a1", "reverted", result["install_id"])]


def test_apply_and_revert_invalidate_env_memo(setup):
    svc, _, _ = setup
    svc.environment()
    assert envmod._memo
    result = run(svc, {"type": "catalog", "id": "docs-mcp"})
    assert not envmod._memo
    svc.environment()
    svc.revert(result["install_id"])
    assert not envmod._memo


def test_old_ledger_gets_link_columns(tmp_path, env):
    db = AppDB(tmp_path / "app.db")
    with db.write() as conn:
        conn.execute("DROP TABLE install_ledger")
        conn.execute("CREATE TABLE install_ledger (entry_id TEXT PRIMARY KEY, ts INTEGER, actor TEXT, action TEXT)")
        conn.execute("DELETE FROM schema_version WHERE module = 'install'")  # as an older release left it
    db.close()
    db = AppDB(tmp_path / "app.db")  # the appdb migration step adds the columns on open
    InstallService(db, tmp_path, env=env)
    with db.read() as conn:
        assert {"inv_id", "catalog_item_id"} <= {r[1] for r in conn.execute("PRAGMA table_info(install_ledger)")}
    db.close()


SHA = "a" * 40


def test_catalog_item_maps_catalog_resources():
    from orbit_backend.install.plan import catalog_item

    skill = catalog_item({"resource": {
        "item_id": "skill:github.com:1:skills/foo/SKILL.md", "type": "skill", "name": "foo", "license": "MIT",
        "url": f"https://github.com/acme/skills/blob/{SHA}/skills/foo/SKILL.md", "commit_sha": SHA,
        "repo_path": "skills/foo/SKILL.md", "agents": ["claude_code"], "metadata": {"repository": "acme/skills"}}})
    assert skill["kind"] == "skill" and skill["install"] is None and skill["agents"] == ["claude_code"]
    assert skill["source"] == {"type": "github", "repo": "acme/skills", "ref": SHA, "path": "skills/foo"}

    mcp = catalog_item({"item_id": "mcp:io.github.acme/docs", "type": "mcp_server", "name": "Docs",
                        "url": "https://example.com", "license": "CC0-1.0 (registry metadata)",
                        "manifest": {"name": "io.github.acme/docs", "packages": [
                            {"registryType": "npm", "identifier": "@acme/docs-mcp", "version": "1.2.0",
                             "transport": {"type": "stdio"}}]}})
    assert mcp["kind"] == "mcp" and mcp["source"] is None
    assert mcp["install"]["mcp"] == {"name": "docs", "transport": "stdio", "command": "npx",
                                     "args": ["-y", "@acme/docs-mcp@1.2.0"]}
    remote = catalog_item({"item_id": "mcp:x/r", "type": "mcp_server", "name": "r", "url": "",
                           "manifest": {"name": "x/r", "remotes": [{"type": "sse", "url": "https://r.example/sse"}]}})
    assert remote["install"]["mcp"]["transport"] == "sse"

    plugin = catalog_item({"item_id": "plugin:marketplace:1:lint", "type": "plugin", "name": "lint",
                           "url": "https://github.com/acme/tools", "install": {"marketplace": "tools", "name": "lint"}})
    assert plugin["install"]["plugin"] == {"plugin": "lint", "marketplace": "tools",
                                           "marketplace_source": {"source": "github", "repo": "acme/tools"}}


def test_route_lookup_prefers_gateway_catalog_then_seed(tmp_path):
    from types import SimpleNamespace

    from orbit_backend.services.routes_install import _catalog_lookup

    resource = {"item_id": "mcp:acme/docs", "type": "mcp_server", "name": "docs", "url": "",
                "manifest": {"name": "acme/docs", "remotes": [{"type": "streamable-http", "url": "https://d.example"}]}}
    store = SimpleNamespace(detail=lambda i: {"resource": resource} if i == "mcp:acme/docs" else None)
    lookup = _catalog_lookup(SimpleNamespace(catalog=SimpleNamespace(store=store), home=tmp_path))
    assert lookup("mcp:acme/docs")["install"]["mcp"]["url"] == "https://d.example"
    assert lookup("missing-item-id") is None
    shaped = {"id": "x", "kind": "mcp", "install": {"mcp": {"name": "x", "url": "https://x"}}}
    direct = _catalog_lookup(SimpleNamespace(catalog=SimpleNamespace(item=lambda i: shaped), home=tmp_path))
    assert direct("x") is shaped
    assert _catalog_lookup(SimpleNamespace(home=tmp_path))("missing-item-id") is None  # no catalog.db


def insert_ai_artifact(appdb, artifact_id, kind, out):
    with appdb.write() as db:
        db.execute("INSERT INTO ai_artifact (artifact_id, kind, template_id, name, title, slots, payload, files, "
                   "checks, personalized, content_hash, status, created_at, updated_at) "
                   "VALUES (?,?,'t',?,?,'{}',?,?,'[]',1,?,'draft',1,1)",
                   (artifact_id, kind, out["name"], out["title"], json.dumps(out["payload"]),
                    json.dumps(out["files"]), out["content_hash"]))


def test_ai_hook_artifact_resolves_placeholders_and_symbolic_targets(setup):
    from orbit_backend.ai.generate.render import render
    from orbit_backend.ai.generate.templates import get

    svc, _, _ = setup
    slots = {"matcher": "Bash", "threshold": 3, "message": "先看错误再重试。", "command_heads": ["pnpm test"]}
    out = render(get("retry-breaker"), slots, {"refs": {"event": ["e1"]}}, personalized=True)
    insert_ai_artifact(svc.appdb, "h1", "hook", out)
    plan = svc.plan({"type": "artifact", "id": "h1"})
    assert plan["agents"] == ["claude_code", "codex"]  # from claude.* and codex.* targets
    codex = [t["idx"] for t in plan["targets"] if t["agent"] == "codex"]
    preview = svc.preview(plan["plan_id"], disabled_targets=codex)
    assert preview["risk"]["level"] != "dangerous", preview["risk"]
    result = svc.apply(plan["plan_id"], preview["preview_digest"], disabled_targets=codex)
    home = svc.env.home
    hooks_dir = home / ".claude/hooks/orbit"
    assert (hooks_dir / "retry-breaker@1.py").stat().st_mode & 0o111
    assert json.loads((hooks_dir / "retry-breaker@1.config.json").read_text()) == slots
    settings = json.loads((home / ".claude/settings.json").read_text())
    entries = {event: settings["hooks"][event][0] for event in ("PreToolUse", "PostToolUse")}
    for entry in entries.values():
        command = entry["hooks"][0]["command"]
        assert entry["matcher"] == "Bash" and "{orbit.hooks}" not in command
        assert f'"{hooks_dir}/retry-breaker@1.py" --config "{hooks_dir}/retry-breaker@1.config.json"' in command
    claude_settings = next(t for t in preview["targets"] if t["path"].endswith("settings.json"))
    assert any(r["op"] == "ai" for r in claude_settings["diff"]["lines"])  # matcher came from an AI slot
    assert svc.revert(result["install_id"])["ok"] and not (hooks_dir / "retry-breaker@1.py").exists()


def test_ai_skill_rule_and_command_artifacts_install(setup):
    from orbit_backend.ai.generate.render import render
    from orbit_backend.ai.generate.templates import get

    svc, _, _ = setup
    pack = {"refs": {"event": ["e1"]}}
    skill = render(get("procedure"), {"name": "ts-verify", "description": "验证。", "steps": ["跑测试"],
                                      "verify": "全绿"}, pack, personalized=False, kind="skill")
    rule = render(get("paragraph"), {"title": "测试先行", "rules": [{"text": "先跑测试。", "dimension": "verification"}]},
                  pack, personalized=False, kind="rule")
    command = render(get("checklist"), {"name": "ship", "description": "发布前检查", "body": "检查 diff"},
                     pack, personalized=False, kind="command")
    for aid, kind, out in (("s1", "skill", skill), ("r1", "rule", rule), ("c1", "command", command)):
        insert_ai_artifact(svc.appdb, aid, kind, out)
        plan = svc.plan({"type": "artifact", "id": aid}, agents=["claude_code"])
        preview = svc.preview(plan["plan_id"])
        assert preview["can_apply"], preview
        svc.apply(plan["plan_id"], preview["preview_digest"])
    home = svc.env.home / ".claude"
    assert "1. 跑测试" in (home / "skills/ts-verify/SKILL.md").read_text()
    memory = (home / "CLAUDE.md").read_text()
    assert "## 测试先行" in memory and "orbit:rule id=" not in memory
    assert "检查 diff" in (home / "commands/ship.md").read_text()


def test_maintain_sweeps_old_plans(setup):
    svc, _, _ = setup
    plan = svc.plan({"type": "catalog", "id": "docs-mcp"}, agents=["claude_code"])
    with svc.appdb.write() as db:
        db.execute("UPDATE install_plan SET created_at = 1 WHERE plan_id = ?", (plan["plan_id"],))
    assert svc.maintain() == {"triggered": 0, "idle": 0, "kept": 0, "backups": 0, "plans": 1, "linked": 0}
