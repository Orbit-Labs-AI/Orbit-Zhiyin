"""Offline library seed snapshot and the official Tandem KB source; no network."""

import gzip
import json
import random
import time
from pathlib import Path

import pytest

from tandem_catalog.contracts import Feature, Page, Record, Resource, SourceSpec, SyncRequest
from tandem_catalog.service import CatalogService
from tandem_catalog.snapshot import (
    BODY_LIMIT,
    FORMAT,
    build_snapshot,
    bundled_seed,
    import_snapshot,
    load_seed,
    retire_seeds,
)
from tandem_catalog.sources.structured import official_entries
from tandem_catalog.store import CatalogStore
from tandem_catalog.sync import CatalogSync

REMEDIES = Path(__file__).resolve().parents[2] / "backend/src/tandem_backend/data/recommend/remedies.v1.json"
HOOK = {"hook": {"event": "PostToolUse", "matcher": "Bash", "command": "~/.tandem/hooks/retry.sh"}}


def resource(item_id, kind, **kwargs):
    kwargs.setdefault("summary", f"{kind} {item_id} for debugging flaky tests")
    return Resource(item_id=item_id, type=kind, name=item_id.split(":")[-1], url=f"https://example.org/{item_id}", **kwargs)


def publish(store, source_id, resources, mode="full"):
    run = store.begin_run(source_id)
    store.stage(run["run_id"], Page(records=[Record(native_id=r.item_id, resource=r) for r in resources],
                                    complete=True, mode=mode, revision="r-" + source_id))
    return store.publish(run["run_id"])


def register(store, *source_ids, kind="github"):
    store.register([SourceSpec(source_id=s, kind=kind, url="https://example.org/" + s, priority=80) for s in source_ids])


@pytest.fixture
def fixture_store(tmp_path):
    """12 items across 8 kinds and 3 sources; one official hook with an install declaration."""
    store = CatalogStore(tmp_path / "source" / "catalog.db")
    register(store, "alpha", "beta", "gamma")
    licensed = {"body_policy": "licensed", "license": "MIT", "body": "# Use\nRun pytest -x and read the trace."}
    publish(store, "alpha", [
        resource("alpha:skill-a", "skill", popularity={"stars": 50}, **licensed),
        resource("alpha:skill-b", "skill", popularity={"stars": 5}),
        resource("alpha:hook-retry", "hook", official=True, install=HOOK, agents=["claude_code"]),
        resource("alpha:plugin-a", "plugin"),
    ])
    publish(store, "beta", [
        resource("beta:subagent-a", "subagent"),
        resource("beta:command-a", "command"),
        resource("beta:rule-a", "rule", features=[Feature(feature="friction", value="retry_same_call", origin="curated")]),
        resource("beta:skill-c", "skill"),
    ])
    publish(store, "gamma", [
        resource("mcp:io.example/server", "mcp_server", manifest={"name": "io.example/server"}),
        resource("gamma:workflow-a", "workflow"),
        resource("gamma:hook-b", "hook"),
        resource("gamma:skill-d", "skill"),
    ])
    return store


def listed(store):
    with store.connect(True) as conn:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT item_id,type FROM catalog_item WHERE listable=1 AND status='active'")}


def test_build_and_import_round_trip_is_faithful_and_idempotent(fixture_store, tmp_path):
    data = build_snapshot(fixture_store, built_at=1)
    assert data == build_snapshot(fixture_store, built_at=1)  # Deterministic bytes.
    doc = load_seed(data)
    assert doc["format"] == FORMAT and set(doc["sources"]) == {"alpha", "beta", "gamma"}
    assert sum(doc["stats"].values()) == 12

    target = CatalogStore(tmp_path / "fresh" / "catalog.db")
    result = import_snapshot(target, data)
    assert result["items"] == 12 and set(result["sources"]) == {"seed-alpha", "seed-beta", "seed-gamma"}
    assert listed(target) == listed(fixture_store)
    hook = target.detail("alpha:hook-retry")["resource"]
    assert hook["install"] == HOOK and hook["official"] is True
    rule = target.detail("beta:rule-a")["resource"]
    assert any(f["feature"] == "friction" and f["origin"] == "curated" for f in rule["features"])
    skill = target.detail("alpha:skill-a")
    assert skill["resource"]["body"].startswith("# Use")

    generation = target.stats()["generation"]
    again = import_snapshot(target, data)
    assert all(s["changed"] == 0 for s in again["sources"].values())
    assert target.stats()["generation"] == generation and listed(target) == listed(fixture_store)


def test_selection_ranks_official_then_stars_and_keeps_three_sources(fixture_store):
    data = build_snapshot(fixture_store, per_kind={"skill": 3, "hook": 1}, built_at=1)
    doc = load_seed(data)
    skills = sorted(i["item_id"] for s in doc["sources"].values() for i in s["items"] if i["type"] == "skill")
    # Top by stars is alpha:skill-a; the other two slots guarantee beta and gamma appear.
    assert "alpha:skill-a" in skills and len(skills) == 3
    assert {s.split(":")[0] for s in skills} == {"alpha", "beta", "gamma"}
    hooks = [i for s in doc["sources"].values() for i in s["items"] if i["type"] == "hook"]
    assert [h["item_id"] for h in hooks] == ["alpha:hook-retry"]  # Official wins.


def test_size_budget_truncates_readme_and_keeps_metadata_items_bodyless(tmp_path):
    store = CatalogStore(tmp_path / "big" / "catalog.db")
    register(store, "big-a", "big-b", "big-c")
    rng = random.Random(7)
    words = [f"w{n}" for n in range(5000)]
    for index, source in enumerate(("big-a", "big-b", "big-c")):
        rows = []
        for n in range(index * 700, min(2000, (index + 1) * 700)):
            licensed = n % 2 == 0
            size = 4500 if n % 20 == 0 else 40  # Some READMEs ~25 KB (over the cap), most short.
            body = " ".join(rng.choice(words) for _ in range(size))
            rows.append(resource(f"{source}:skill-{n}", "skill", body=body, body_policy="licensed" if licensed else "metadata",
                                 license="MIT" if licensed else None, popularity={"stars": n}))
        publish(store, source, rows)
    data = build_snapshot(store, per_kind={"skill": 2000}, built_at=1)
    assert len(data) <= 3_000_000
    items = [i for s in load_seed(data)["sources"].values() for i in s["items"]]
    assert items and all(len(i.get("body", "").encode()) <= BODY_LIMIT for i in items)
    assert any(len(i.get("body", "").encode()) > BODY_LIMIT - 100 for i in items)  # Truncated, not dropped.
    assert all(not i.get("body") for i in items if i.get("body_policy", "metadata") == "metadata")
    assert len({i["item_id"].split(":")[0] for i in items}) == 3

    tiny = build_snapshot(store, per_kind={"skill": 2000}, max_bytes=10_000, built_at=1)
    assert len(tiny) <= 10_000 and 0 < sum(load_seed(tiny)["stats"].values()) < 2000


def test_network_sync_retires_seed_rows_without_duplicates(fixture_store, tmp_path):
    data = build_snapshot(fixture_store, built_at=1)
    target = CatalogStore(tmp_path / "fresh" / "catalog.db")
    register(target, "alpha")  # The real source, not yet synced.
    import_snapshot(target, data)
    assert {"alpha:skill-a", "alpha:skill-b", "alpha:hook-retry", "alpha:plugin-a"} <= set(listed(target))

    # Network copy of alpha: skill-a changed, skill-b gone, a new item appeared.
    publish(target, "alpha", [resource("alpha:skill-a", "skill", summary="fresh from network"),
                              resource("alpha:hook-retry", "hook", official=True, install=HOOK),
                              resource("alpha:plugin-a", "plugin"), resource("alpha:skill-new", "skill")])
    assert target.detail("alpha:skill-a")["resource"]["summary"] == "fresh from network"  # Priority 80 > 10.
    assert retire_seeds(target, ["alpha"]) == 4
    assert retire_seeds(target, ["alpha"]) == 0
    now = listed(target)
    assert "alpha:skill-b" not in now and "alpha:skill-new" in now and "beta:rule-a" in now
    with target.connect(True) as conn:
        assert conn.execute("SELECT count(*) FROM item_source WHERE source_id='seed-alpha' AND status='active'").fetchone()[0] == 0
        dupes = conn.execute("SELECT name,type,count(*) FROM catalog_item WHERE listable=1 GROUP BY item_id HAVING count(*)>1").fetchall()
    assert not dupes
    # A synced real source is not re-seeded by a later import.
    assert import_snapshot(target, data)["skipped"] == ["alpha"] and "alpha:skill-b" not in listed(target)


def test_service_sync_retires_seed_and_bootstrap_imports_once(tmp_path):
    entries = official_entries(json.loads(REMEDIES.read_text()))[:3]
    official = tmp_path / "official.json"
    official.write_text(json.dumps(entries))
    seed = {"format": FORMAT, "built_at": 1, "stats": {"hook": 1},
            "sources": {"mirror": {"revision": "r1", "items": [
                {"item_id": "kb:readonly-allowlist", "type": "hook", "name": "stale", "url": ""},
                {"item_id": "kb:gone", "type": "hook", "name": "gone", "url": ""}]}}}
    service = CatalogService(tmp_path / "home" / "catalog.db", http=object())
    try:
        service.store.register([SourceSpec(source_id="mirror", kind="kb", url="bundled:kb", config={"file": str(official)})])
        first = service.bootstrap(gzip.compress(json.dumps(seed).encode()), offline_ids=())
        assert first["seed"]["items"] == 2 and not service.needs_seed()
        assert service.bootstrap(gzip.compress(json.dumps(seed).encode()), offline_ids=())["seed"] is None
        job = service.start_sync(SyncRequest(source_ids=["mirror"]))
        for _ in range(500):
            state = service.job(job["job_id"])
            if state["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        assert state["status"] == "completed"
        items = listed(service.store)
        assert "kb:gone" not in items and "kb:readonly-allowlist" in items
        assert service.store.detail("kb:readonly-allowlist")["resource"]["name"] == entries[0]["name"]
        coverage = service.coverage()
        assert coverage["seeded"] and coverage["by_source"]["seed-mirror"]["items"] == 0
    finally:
        service.close()


def test_kb_source_maps_all_remedies_as_curated_official_items(tmp_path):
    store = CatalogStore(tmp_path / "kb" / "catalog.db")
    store.register([SourceSpec(source_id="tandem-kb", kind="kb", url="bundled:kb", priority=100,
                               config={"file": str(REMEDIES)})])
    [result] = CatalogSync(store, http=None).sync(["tandem-kb"])
    assert result["status"] == "completed" and result["seen"] == 25
    rules = json.loads(REMEDIES.read_text())["rules"]
    with store.connect(True) as conn:
        rows = {r["item_id"]: dict(r) for r in conn.execute("SELECT item_id,type,official,listable FROM catalog_item")}
        friction = {(r[0], r[1]) for r in conn.execute(
            "SELECT item_id,value FROM item_feature WHERE feature='friction' AND origin='curated'")}
    assert set(rows) == {"kb:" + r["id"] for r in rules}
    assert all(r["official"] == 1 and r["listable"] == 1 for r in rows.values())
    assert {("kb:" + r["id"], t) for r in rules for t in r["problem"]["types"]} <= friction
    retry = store.detail("kb:retry-breaker")["resource"]
    assert retry["install"]["hook"] == {"event": "PostToolUse", "matcher": "Bash", "command": "~/.tandem/hooks/retry-breaker.sh"}
    assert retry["type"] == "hook" and retry["license"] == "MIT" and retry["metadata"]["origin"] == "tandem-kb"
    assert sum(1 for r in rows.values() if r["type"] == "hook") >= 3
    # Unchanged KB: the next visit is a no-op.
    store.register([SourceSpec(source_id="tandem-kb", kind="kb", url="bundled:kb", priority=100,
                               config={"file": str(REMEDIES)})])
    assert CatalogSync(store, http=None).sync(["tandem-kb"], force=True)[0]["changed"] == 0


def test_bundled_official_export_matches_the_recommend_kb():
    bundled = json.loads((Path(__file__).resolve().parents[1] / "src/tandem_catalog/data/official.v1.json").read_text())
    assert bundled == official_entries(json.loads(REMEDIES.read_text())), \
        "run: python -m tandem_catalog export-official --remedies <remedies.v1.json> --out data/official.v1.json"


def test_bundled_seed_is_small_valid_and_covers_every_library_kind():
    data = bundled_seed()
    assert data is not None and len(data) <= 3_000_000
    doc = load_seed(data)
    assert set(doc["stats"]) >= {"skill", "plugin", "subagent", "command", "rule", "hook", "workflow", "mcp_server"}
    assert doc["stats"]["mcp_server"] >= 100 and doc["stats"]["skill"] >= 100
    for source in doc["sources"].values():
        for item in source["items"]:
            Resource.model_validate(item)
            assert len(item.get("body", "").encode()) <= BODY_LIMIT
