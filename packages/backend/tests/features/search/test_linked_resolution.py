from pathlib import Path

from conftest import NOW

from orbit_backend import appdb as appdb_schema
from orbit_backend.features.linked import compute_linked, norm

REVS = {"data": 1, "inventory": 1, "catalog": "1"}


def run(world, revs=REVS, **kw):
    return compute_linked(world.connection(kw.pop("catalog", True)), revs=revs, now_ms=NOW,
                          write=world.write, read_text=lambda _p: None, **kw)


def by_id(result):
    return {i["inv_id"]: i for i in result["items"]}


def test_norm_folds_separators_and_prefixes():
    assert norm("Plugin-Code.Review") == "code_review"
    assert norm("mcp:Playwright") == "playwright"
    assert norm("a / b@c") == "a_b_c"


def test_hash_name_alias_priority_and_official_tiebreak(world):
    world.item("cat-hash", "skill", "other-name", body_sha256="h-s1")
    world.item("cat-s1", "skill", "pdf_tools")
    world.item("cat-b", "mcp_server", "playwright", official=0)
    world.item("cat-a", "mcp_server", "Playwright", official=1)
    world.item("cat-plug", "plugin", "review-kit")
    world.inventory("claude_code", [
        {"inv_id": "s1", "type": "skill", "name": "pdf-tools"},
        {"inv_id": "s2", "type": "skill", "name": "PDF Tools"},
        {"inv_id": "m1", "type": "mcp", "name": "playwright"},
        {"inv_id": "p1", "type": "plugin", "name": "review-kit@market"},
        {"inv_id": "x1", "type": "skill", "name": "nothing-here"},
    ])
    items = by_id(run(world))
    assert items["s1"]["catalog"]["item_id"] == "cat-hash"
    assert items["s1"]["catalog"]["method"] == "hash"
    assert items["s2"]["catalog"]["method"] == "name" and items["s2"]["catalog"]["confidence"] == 0.8
    assert items["m1"]["catalog"]["item_id"] == "cat-a"
    assert items["p1"]["catalog"] == {"item_id": "cat-plug", "name": "review-kit",
                                      "method": "alias", "confidence": 0.6,
                                      "url": "https://x/cat-plug"}
    assert items["x1"]["catalog"] is None
    stored = dict(world.a.execute("SELECT inv_id, method FROM inv_link").fetchall())
    assert stored == {"s1": "hash", "s2": "name", "m1": "name", "p1": "alias"}


def test_confirmed_link_is_never_overwritten(world):
    world.item("cat-s1", "skill", "pdf_tools")
    world.inventory("claude_code", [{"inv_id": "s1", "type": "skill", "name": "pdf-tools"}])
    world.a.execute("INSERT INTO inv_link VALUES ('s1','cat-manual','user',1.0,'0',1)")
    item = by_id(run(world, revs={**REVS, "catalog": "2"}))["s1"]
    assert item["catalog"]["item_id"] == "cat-manual" and item["catalog"]["method"] == "user"
    assert world.a.execute("SELECT catalog_item_id FROM inv_link").fetchone()[0] == "cat-manual"


def test_ledger_outranks_matching_and_marks_installed(world):
    world.item("cat-s1", "skill", "pdf_tools")
    world.a.execute("CREATE TABLE install_ledger (install_id TEXT, inv_id TEXT, catalog_item_id TEXT)")
    world.a.execute("INSERT INTO install_ledger VALUES ('i1','s1','cat-ledger')")
    world.inventory("claude_code", [{"inv_id": "s1", "type": "skill", "name": "pdf-tools"},
                                    {"inv_id": "s2", "type": "skill", "name": "pdf-tools"}])
    result = run(world)
    items = by_id(result)
    assert items["s1"]["catalog"]["method"] == "ledger" and items["s1"]["orbit_installed"]
    assert not items["s2"]["orbit_installed"]
    assert result["summary"]["orbit_installed"] == 1


def test_ledger_from_real_install_tables(world):
    schema = Path(appdb_schema.__file__).parent / "schema" / "install.sql"
    world.a.executescript(schema.read_text())
    world.item("cat-pdf", "skill", "pdf_tools")
    world.item("cat-pw", "mcp_server", "playwright")
    world.item("cat-gh", "mcp_server", "github")
    for install_id, item_id, path, state in [
            ("in1", "cat-ledger-pdf", "/cfg/s1", "active"),
            ("in2", "cat-pw", "/cfg/shared.json", "active"),
            ("in3", "cat-gh", "/cfg/shared.json", "active"),
            ("in4", "cat-gone", "/cfg/s3", "reverted")]:
        world.a.execute("INSERT INTO install_state (install_id, plan_id, source_type, source_id, "
                        "title, kind, agents, scope, preview_digest, state, installed_at) "
                        "VALUES (?, 'p', 'catalog', ?, 't', 'skill', '[]', 'global', 'd', ?, 1)",
                        (install_id, item_id, state))
        world.a.execute("INSERT INTO install_ledger (entry_id, ts, actor, action, install_id, "
                        "path) VALUES (?, 1, 'orbit', 'install', ?, ?)",
                        (f"e-{install_id}", install_id, path))
    world.inventory("claude_code", [
        {"inv_id": "s1", "type": "skill", "name": "pdf-tools"},
        {"inv_id": "m1", "type": "mcp", "name": "playwright", "config_path": "/cfg/shared.json"},
        {"inv_id": "m2", "type": "mcp", "name": "other", "config_path": "/cfg/shared.json"},
        {"inv_id": "s3", "type": "skill", "name": "pdf-tools"}])
    items = by_id(run(world, revs={**REVS, "data": 7}))
    assert items["s1"]["catalog"]["method"] == "ledger" and items["s1"]["orbit_installed"]
    assert items["m1"]["catalog"]["item_id"] == "cat-pw" and items["m1"]["orbit_installed"]
    assert not items["m2"]["orbit_installed"]
    assert items["s3"]["catalog"]["method"] == "name" and not items["s3"]["orbit_installed"]


def test_prefixed_body_sha256_matches(world):
    world.item("cat-hash", "skill", "other-name", body_sha256="sha256:H-S1")
    world.inventory("claude_code", [{"inv_id": "s1", "type": "skill", "name": "x",
                                     "content_hash": "h-s1"}])
    assert by_id(run(world, revs={**REVS, "data": 8}))["s1"]["catalog"]["method"] == "hash"


def test_missing_ledger_and_app_tables_degrade(world):
    world.a.execute("DROP TABLE inv_link")
    world.a.execute("DROP TABLE inv_size")
    world.item("cat-s1", "skill", "pdf_tools")
    world.inventory("claude_code", [{"inv_id": "s1", "type": "skill", "name": "pdf-tools"}])
    assert by_id(run(world))["s1"]["catalog"]["method"] == "name"


def test_catalog_rev_change_rematches_unconfirmed(world):
    world.item("cat-s1", "skill", "pdf_tools")
    world.inventory("claude_code", [{"inv_id": "s1", "type": "skill", "name": "pdf-tools"}])
    run(world)
    world.c.execute("UPDATE catalog_item SET status='retired' WHERE item_id='cat-s1'")
    world.item("cat-s1b", "skill", "pdf-tools")
    assert by_id(run(world))["s1"]["catalog"]["item_id"] == "cat-s1"  # cached by rev
    item = by_id(run(world, revs={**REVS, "catalog": "2"}))["s1"]
    assert item["catalog"]["item_id"] == "cat-s1b"
    assert world.a.execute("SELECT catalog_rev FROM inv_link").fetchone()[0] == "2"


def test_no_scan_and_project_filter(world):
    empty = run(world)
    assert empty["items"] == [] and empty["coverage"]["inventory"]["status"] == "unavailable"
    world.project("p1", "alpha", paths=["/work/alpha"])
    world.inventory("claude_code", [
        {"inv_id": "g", "type": "skill", "name": "g"},
        {"inv_id": "pa", "type": "skill", "name": "pa", "config": {"project_path": "/work/alpha"}},
        {"inv_id": "pb", "type": "skill", "name": "pb", "config": {"project_path": "/work/beta"}},
    ])
    world.inventory("codex", [{"inv_id": "cx", "type": "skill", "name": "cx"}])
    ids = set(by_id(run(world, revs={**REVS, "data": 2}, project_ids=["p1"])))
    assert ids == {"g", "pa", "cx"}
    assert set(by_id(run(world, revs={**REVS, "data": 3}, agent="codex"))) == {"cx"}


def test_catalog_missing_still_reports(world):
    world.inventory("claude_code", [{"inv_id": "s1", "type": "skill", "name": "pdf"}])
    result = run(world, catalog=False)
    assert result["items"][0]["catalog"] is None
    assert result["coverage"]["catalog"] == "unavailable"
