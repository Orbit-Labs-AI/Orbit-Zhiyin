import pytest

from orbit_catalog import query
from orbit_catalog.contracts import Feature, Record, Resource, SourceSpec
from orbit_catalog.store import CatalogStore

from .test_storage import publish

KINDS = ["skill", "hook", "plugin"]


def item(n, **kwargs):
    defaults = {"type": KINDS[n % 3], "name": f"Item {n:02}", "summary": f"summary {n}", "url": f"https://x/{n}",
                "agents": ["claude_code"] if n % 2 else ["codex"], "license": "MIT" if n % 4 else "GPL-3.0",
                "popularity": {"installs": n * 10, "stars": 100 - n},
                "metadata": {"source_updated_at": 1_700_000_000_000 + n * 1000, "author": f"dev{n % 5}"},
                "features": [Feature(feature="domain", value="testing" if n % 2 else "writing", origin="declared")]}
    return Record(native_id=f"n{n}", resource=Resource(item_id=f"i{n:02}", **{**defaults, **kwargs}))


@pytest.fixture
def store(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test", priority=90)])
    publish(store, [item(n) for n in range(25)])
    return store


def walk(store, **kwargs):
    seen, cursor, pages = [], None, 0
    while True:
        page = query.list_items(store, limit=7, cursor=cursor, **kwargs)
        assert (page["total"] is not None) == (cursor is None)
        seen.extend(c["item_id"] for c in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            return seen, pages


@pytest.mark.parametrize(("sort", "key"), [("updated", lambda n: -n), ("installs", lambda n: -n),
                                           ("stars", lambda n: n), ("name", lambda n: -n)])
def test_keyset_pages_cover_everything_in_order(store, sort, key):
    seen, pages = walk(store, sort=sort)
    assert len(seen) == len(set(seen)) == 25 and pages == 4
    assert seen == [f"i{n:02}" for n in sorted(range(25), key=key)]
    ascending, _ = walk(store, sort=sort, order="asc")
    assert ascending == list(reversed(seen))


def test_filters_and_card_fields(store):
    page = query.list_items(store, kinds=["hook"], agents=["codex"], license="MIT")
    assert page["total"] == len(page["items"]) and page["items"]
    card = page["items"][0]
    assert card["kind"] == "hook" and card["agents"] == ["codex"] and card["license"] == "MIT"
    assert set(card) >= {"item_id", "name", "summary", "author", "official", "risk_level", "risk", "installs", "stars",
                         "updated_at", "origin", "body_policy", "canonical_of", "difficulty", "version"}
    assert query.list_items(store, exclude=["i24"])["items"][0]["item_id"] == "i23"
    with pytest.raises(ValueError, match="invalid_query"):
        query.list_items(store, sort="random")
    with pytest.raises(ValueError, match="invalid_query"):
        query.list_items(store, cursor="not-a-cursor")


def test_cursor_survives_deleted_anchor(store):
    first = query.list_items(store, limit=5)
    publish(store, [item(n) for n in range(25) if n != 20], revision="r2")  # i20 is the page anchor.
    second = query.list_items(store, limit=5, cursor=first["next_cursor"])
    assert [c["item_id"] for c in second["items"]] == ["i19", "i18", "i17", "i16", "i15"]


def test_facets_ignore_their_own_dimension(store):
    all_facets = query.facets(store)
    assert all_facets["total"] == 25
    assert {f["value"]: f["count"] for f in all_facets["kind"]} == {"skill": 9, "hook": 8, "plugin": 8}
    hooks = query.facets(store, kinds=["hook"])
    assert hooks["total"] == 8
    assert {f["value"] for f in hooks["kind"]} == {"skill", "hook", "plugin"}  # Own filter ignored.
    assert sum(f["count"] for f in hooks["agent"]) == 8
    assert hooks["official"] == {"true": 0, "false": 8}


def test_detail_fields_and_related(store):
    publish(store, [item(n) for n in range(25)] + [item(30, name="Item 01", type="hook", summary="other",
                    components=["i03"], body="# Use\n```bash\ncurl https://x\n```", body_policy="licensed")], revision="r2")
    detail = query.get_item(store, "i30")
    assert detail["readme"].startswith("# Use") and detail["readme_policy"] == "inline"
    assert detail["permissions"]["level"] >= 1 and "network" in detail["permissions"]["flags"]
    assert [c["item_id"] for c in detail["components"]] == ["i03"]
    relations = {r["card"]["item_id"]: r["relation"] for r in detail["related"]}
    assert relations["i03"] == "depends" and relations["i01"] == "alternative_to"
    assert any(r == "similar" for r in relations.values())
    assert detail["install"]["ref"] == {"source": "catalog_item", "id": "i30"}
    assert detail["versions"][0]["version_id"] == detail["version_id"] and detail["scan"]["estimate"] is True
    metadata_only = query.get_item(store, "i02")
    assert metadata_only["readme"] is None and metadata_only["readme_policy"] == "link_only"
    assert metadata_only["resident_tokens_est"] is None and query.get_item(store, "i00")["resident_tokens_est"] == 0
    assert query.get_item(store, "missing") is None


def test_models_merge_sources_and_benchmarks_resolve(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="models-dev", kind="models_dev", url="u", priority=80),
                    SourceSpec(source_id="litellm", kind="litellm", url="u", priority=60)])
    a = Resource(item_id="md:x", type="model", name="Model X", url="u",
                 metadata={"provider": "acme", "model_id": "x", "canonical_id": "acme/x", "context_window": 1000})
    b = Resource(item_id="ll:x", type="model", name="x", url="u",
                 metadata={"provider": "acme", "model_id": "x-2026", "canonical_id": "acme/x", "context_window": 999,
                           "input_per_mtok": 2.5, "aliases": ["x-latest"]})
    bench = Resource(item_id="sb:1", type="benchmark", name="run", url="https://bench",
                     manifest={"model_id": "x", "canonical_model_id": "acme/x", "benchmark": "swe", "score": 50.0})
    orphan = Resource(item_id="sb:2", type="benchmark", name="run2", url="u", manifest={"model_id": "ghost", "benchmark": "swe"})
    publish(store, [Record(native_id="a", resource=a)], source="models-dev")
    publish(store, [Record(native_id="b", resource=b), Record(native_id="c", resource=bench),
                    Record(native_id="d", resource=orphan)], source="litellm")
    models = query.models(store)
    assert models["total"] == 1
    model = models["items"][0]
    assert model["context_window"] == 1000 and model["input_per_mtok"] == 2.5  # Priority wins, gaps coalesce.
    assert model["aliases"] == ["x-latest"] and [s["source_id"] for s in model["sources"]] == ["models-dev", "litellm"]
    assert model["benchmarks_count"] == 1 and model["max_output"] is None
    rows = query.benchmarks(store, benchmark="swe")["items"]
    assert [(r["model"], r["resolved"]) for r in rows] == [("x", True), ("ghost", False)]
    assert query.get_model(store, "acme/x")["benchmarks"][0]["url"] == "https://bench"
    assert query.models(store, q="latest")["total"] == 1 and query.models(store, provider="other")["total"] == 0


def test_empty_catalog_reads(tmp_path):
    from orbit_catalog.contracts import MatchRequest
    from orbit_catalog.search import search
    store = CatalogStore(tmp_path / "empty.db")
    assert query.list_items(store) == {"items": [], "next_cursor": None, "total": 0, "generation": 0}
    assert query.facets(store)["total"] == 0 and query.facets(store)["agent"] == []
    assert search(store, MatchRequest(text="调试 debug", prefix=True))["items"] == []
    assert query.models(store)["items"] == [] and query.benchmarks(store)["items"] == []
    assert query.get_item(store, "x") is None and store.verify()["ok"]


@pytest.mark.parametrize("kind,hints", [("skill", {}), ("command", {}),
                                       ("hook", {"hook": {"event": "Stop", "command": "echo done"}}),
                                       ("mcp_server", {"mcp": {"command": "example"}}),
                                       ("plugin", {"name": "example", "marketplace": "example"})])
@pytest.mark.parametrize("metadata", [{}, {"installable": True}])
def test_install_display_keeps_existing_eligible_resources(kind, hints, metadata):
    result = query._install("x", {"status": "active", "type": kind}, ["codex"], hints, True, metadata)
    assert result["installable"] is True and result["reason"] is None
    assert result["targets"] == ["codex"] and result["hints"] == hints


def test_explicit_non_installable_takes_precedence_over_valid_install_hints():
    result = query._install("x", {"status": "active", "type": "mcp_server"}, ["codex"],
                            {"mcp": {"command": "example"}}, True, {"installable": False})
    assert result["installable"] is False and result["reason"] == "source_declared_not_installable"
