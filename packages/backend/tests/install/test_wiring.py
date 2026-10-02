"""Install → recommend / AI / ledger links / env memo, over a tmp app.db and fabricated homes."""

import json
import sqlite3

import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.install import env as envmod
from tandem_backend.install import store
from tandem_backend.install.service import InstallService

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
    db = AppDB(tmp_path / "tandem" / "app.db")
    calls = []
    tdb = tmp_path / "tandem.db"
    make_inventory(tdb)
    svc = InstallService(db, tmp_path / "tandem", env=env, fetcher=FakeFetcher(), catalog_lookup=CATALOG.get,
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
    InstallService(db, tmp_path, env=env)
    with db.read() as conn:
        assert {"inv_id", "catalog_item_id"} <= {r[1] for r in conn.execute("PRAGMA table_info(install_ledger)")}
    db.close()


SHA = "a" * 40


def test_catalog_item_maps_catalog_resources():
    from tandem_backend.install.plan import catalog_item

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

    from tandem_backend.services.routes_install import _catalog_lookup

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
