import time

from tandem_backend.features.hub import QueryHub


def test_gather_parallel_and_errors(seeded, make_service):
    svc = make_service()
    out = svc.hub.gather(ok=lambda db: db.execute("SELECT COUNT(*) FROM t.session").fetchone()[0],
                         bad=lambda db: db.execute("SELECT * FROM nope").fetchall())
    assert out["ok"] == 3 and isinstance(out["bad"], Exception)
    assert svc.hub.has("t", "session") and not svc.hub.has("c", "catalog_item")


def test_late_attach(home, make_service, catalog, request):
    svc = make_service()
    assert svc.hub.attached() == set()
    assert svc.match({"vector": {"tool:browser": 1.0}}) == []
    request.getfixturevalue("tandem")
    catalog([("i1", "skill", ["claude_code"], "active", [("tool_kind", "browser", 1.0)])])
    assert svc.hub.attached() == {"t", "c"}
    assert svc.catalog_rev() == "0"
    assert [m["item_id"] for m in svc.match({"vector": {"tool:browser": 1.0}})] == ["i1"]


def test_match_scores(home, make_service, catalog):
    catalog([
        ("a", "skill", ["claude_code"], "active",
         [("file_type", ".py", 1.0), ("tool_kind", "browser", 0.5)]),
        ("b", "mcp_server", ["codex"], "active", [("language", "python", 2.0)]),
        ("c", "skill", ["claude_code"], "retired", [("file_type", ".py", 1.0)]),
        ("d", "skill", ["claude_code"], "active", [("domain", "writing", 1.0)]),
    ])
    svc = make_service()
    profile = {"vector": {"lang:python": 0.8, "tool:browser": 0.4, "ftype:.py": 1.0}}
    # pairs: language/python .8, file_type/.py max(.8,1.0)=1.0, other .py-langs files .8,
    # tool_kind/browser .4
    pairs_total = 0.8 + 1.0 + 0.4  # language, .py, browser
    result = svc.match(profile)
    by_id = {r["item_id"]: r for r in result}
    assert set(by_id) == {"a", "b"}
    assert abs(by_id["a"]["score"] - (1.0 * 1.0 + 0.4 * 0.5) / pairs_total) < 1e-5
    assert abs(by_id["b"]["score"] - 0.8 * 1.0 / pairs_total) < 1e-5
    assert result[0]["item_id"] == "a"
    assert by_id["a"]["matched"][0] == {"id": "ftype:.py", "feature": "file_type",
                                         "value": ".py", "w": 1.0}
    assert [r["item_id"] for r in svc.match(profile, kinds=["mcp"])] == ["b"]
    assert [r["item_id"] for r in svc.match(profile, agent="claude_code")] == ["a"]
    assert svc.match(profile, k=1)[0]["item_id"] == "a"


def test_hub_close(home, tmp_path):
    from tandem_backend.appdb import AppDB

    appdb = AppDB(home / "app.db")
    hub = QueryHub(home, appdb.path, workers=2)
    started = time.perf_counter()
    out = hub.gather(a=lambda db: 1, b=lambda db: 2)
    assert out == {"a": 1, "b": 2} and time.perf_counter() - started < 2
    hub.close()
    appdb.close()
