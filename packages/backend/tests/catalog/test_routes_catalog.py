"""Gateway-level catalog routes on a temporary home; no network, no real agent homes."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from orbit_backend.services.gateway import Gateway

TOKEN = "synthetic-test-token-0123456789abcdef"
BASE = "http://127.0.0.1:8765"
LOCAL = {"kind": "skill", "name": "Retry triage", "summary": "generated", "body": "# Steps\nRe-run flaky pytest cases.",
         "agents": ["codex"], "self_check": {"passed": True, "checks": []}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("catalog tests must not reach the network")
    monkeypatch.setattr("orbit_catalog.network.HttpClient.get", no_network)
    gateway = Gateway(tmp_path / "home", discovery=lambda: [], prewarm_debounce_s=3600.0)
    # No lifespan: catalog routes do not need the supervisor or ingest worker.
    yield TestClient(gateway.app(token=TOKEN, port=8765), base_url=BASE, headers={"Authorization": f"Bearer {TOKEN}"})


def wait_job(client, job_id):
    for _ in range(500):
        state = client.get(f"/v1/catalog/jobs/{job_id}").json()
        if state["status"] in ("completed", "failed", "cancelled"):
            return state
        time.sleep(0.01)
    raise AssertionError("catalog job did not finish")


def test_gateway_serves_catalog_reads_local_writes_and_sync(client, monkeypatch):
    started = client.post("/v1/catalog/sync", json={"source_ids": ["orbit-seeds"]})
    assert started.status_code == 202
    assert wait_job(client, started.json()["job_id"])["status"] == "completed"

    page = client.get("/v1/catalog/items", params={"limit": 5}).json()
    assert page["total"] >= 5 and len(page["items"]) == 5 and page["next_cursor"]
    assert all(card["installed"] is None for card in page["items"])  # No features module yet: degrade.
    facets = client.get("/v1/catalog/facets").json()
    assert facets["total"] == page["total"] and facets["kind"]
    item_id = page["items"][0]["item_id"]
    detail = client.get(f"/v1/catalog/items/{item_id}").json()
    assert detail["item_id"] == item_id and detail["scan"]["estimate"] is True and "install" in detail
    found = client.get("/v1/catalog/search", params={"q": "调试"}).json()
    assert found["items"] and "snippet" in found["items"][0]

    missing = client.post("/v1/catalog/local", json={k: v for k, v in LOCAL.items() if k != "self_check"})
    assert missing.status_code == 422
    created = client.post("/v1/catalog/local", json=LOCAL)
    assert created.status_code == 201
    assert client.post("/v1/catalog/local", json=LOCAL).status_code == 200
    assert client.get("/v1/catalog/items", params={"origin": "local"}).json()["total"] == 1
    assert client.get("/v1/catalog/items/missing:item").status_code == 404


def test_cards_are_decorated_when_features_inventory_exists(client, monkeypatch):
    from orbit_backend import features
    created = client.post("/v1/catalog/local", json=LOCAL).json()
    linked = {"items": [{"inv_id": "i1", "agent": "codex", "scope": "user", "status": "active",
                         "catalog": {"item_id": created["item_id"], "method": "ledger", "confidence": 1.0}},
                        {"inv_id": "i2", "agent": "claude", "scope": "user", "status": "unused", "catalog": None}]}
    monkeypatch.setattr(features, "linked_inventory", lambda: linked)
    card = client.get("/v1/catalog/items", params={"origin": "local"}).json()["items"][0]
    assert card["installed"] == {"state": "active", "agents": ["codex"], "scope": "user"}


def test_catalog_reads_answer_304_until_the_generation_moves(client):
    first = client.get("/v1/catalog/items")
    tag = first.headers["etag"]
    assert client.get("/v1/catalog/items", headers={"If-None-Match": tag}).status_code == 304
    assert client.get("/v1/catalog/items", params={"limit": 2}, headers={"If-None-Match": tag}).status_code == 200
    assert "etag" not in client.get("/v1/catalog/status").headers  # Status and jobs are never cached.
    client.post("/v1/catalog/local", json=LOCAL)
    assert client.get("/v1/catalog/items", headers={"If-None-Match": tag}).status_code == 200


def test_sync_passes_concurrency_offline_and_reports_durations(client, monkeypatch):
    from orbit_backend import platform
    from orbit_catalog.sync import CatalogSync
    seen, recorded = {}, []
    original = CatalogSync.sync

    def spy(self, *args, **kwargs):
        seen.update(concurrency=kwargs["concurrency"], offline=self.http.offline, ttl=self.http.ttl)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(CatalogSync, "sync", spy)
    monkeypatch.setattr(platform, "record", lambda name, value=1.0, **tags: recorded.append((name, value, tags)))
    started = client.post("/v1/catalog/sync", json={"source_ids": ["orbit-seeds"], "concurrency": 2, "force": True,
                                                    "offline": True, "ttl": 600})
    job = wait_job(client, started.json()["job_id"])
    assert seen == {"concurrency": 2, "offline": True, "ttl": 600}
    assert job["duration_ms"] >= 0 and job["result"][0]["duration_ms"] >= 0
    for _ in range(100):
        if any(name == "catalog.sync" for name, *_ in recorded):
            break
        time.sleep(0.01)
    assert {name for name, *_ in recorded} >= {"catalog.sync", "catalog.sync.source"}
    assert client.post("/v1/catalog/sync", json={"concurrency": 99}).status_code == 422
