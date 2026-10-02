"""First start of the catalog: offline official items, seed import, refresher; no network."""

from __future__ import annotations

import threading
import time
import types
import weakref

import pytest
from fastapi.testclient import TestClient

from tandem_backend.services import routes_catalog
from tandem_backend.services.gateway import Gateway

TOKEN = "synthetic-test-token-0123456789abcdef"


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("catalog tests must not reach the network")
    monkeypatch.setattr("tandem_catalog.network.HttpClient.get", no_network)
    gw = Gateway(tmp_path / "home", discovery=lambda: [], prewarm_debounce_s=3600.0)
    client = TestClient(gw.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                        headers={"Authorization": f"Bearer {TOKEN}"})
    yield gw, client
    gw.stopping.set()  # Ends the refresher thread of this gateway.


def service_of(gw):
    from tandem_catalog import get_service
    return get_service(gw.home / "catalog.db")


def wait_job(service, job_id):
    for _ in range(1000):
        job = service.job(job_id)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    raise AssertionError("catalog job did not finish")


def test_empty_home_serves_official_hooks_immediately(gateway):
    _, client = gateway
    hooks = client.get("/v1/catalog/items", params={"kind": "hook", "official": True}).json()
    assert hooks["total"] >= 3
    ids = {card["item_id"] for card in hooks["items"]}
    assert {"kb:retry-breaker", "kb:readonly-allowlist", "kb:stop-verify-hook"} <= ids
    detail = client.get("/v1/catalog/items/kb:retry-breaker").json()
    assert detail["install"]["hints"]["hook"]["event"] == "PostToolUse" and detail["install"]["installable"]

    status = client.get("/v1/catalog/status").json()
    coverage = status["coverage"]
    assert status["items"] >= 27 and coverage["seeded"] is True
    assert coverage["by_source"]["tandem-kb"]["items"] == 25 and coverage["by_kind"]["hook"] >= 3
    assert "mcp-official" in coverage["partial_sources"] and coverage["last_sync_at"] is None


def test_seed_import_fills_every_library_kind_offline(gateway):
    gw, client = gateway
    service = service_of(gw)
    assert service.needs_seed()
    result = service.bootstrap()
    assert result["seed"]["items"] >= 1000
    assert not service.needs_seed() and service.bootstrap()["seed"] is None
    by_kind = client.get("/v1/catalog/status").json()["coverage"]["by_kind"]
    for kind in ("skill", "plugin", "subagent", "command", "rule", "hook", "workflow", "mcp_server"):
        assert by_kind.get(kind, 0) >= 3, kind
    assert client.get("/v1/catalog/items", params={"kind": "mcp_server"}).json()["total"] >= 100
    assert client.get("/v1/catalog/search", params={"q": "github"}).json()["items"]


def test_failing_network_does_not_break_startup_or_reads(gateway):
    gw, client = gateway
    service = service_of(gw)

    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise RuntimeError("http_500")
            return fail

    service.http = Down()
    job = routes_catalog.refresh_tick(service)
    assert job is not None
    done = wait_job(service, job["job_id"])
    assert done["status"] in ("failed", "completed")
    assert client.get("/v1/catalog/items", params={"kind": "hook"}).json()["total"] >= 3
    coverage = client.get("/v1/catalog/status").json()["coverage"]
    assert coverage["by_source"]["anthropic-skills"]["error"]
    assert coverage["by_source"]["tandem-kb"]["error"] is None


def test_refresh_tick_skips_while_a_catalog_job_is_active(gateway):
    gw, _ = gateway
    service = service_of(gw)
    gate = threading.Event()
    service._submit("embed", lambda cancel: gate.wait(5))
    try:
        assert routes_catalog.refresh_tick(service) is None
    finally:
        gate.set()


def test_refresher_waits_for_start_then_seeds_and_syncs(monkeypatch):
    calls = []
    service = types.SimpleNamespace(bootstrap=lambda: calls.append("seed"))
    monkeypatch.setattr(routes_catalog, "refresh_tick", lambda svc: calls.append("sync"))
    monkeypatch.setattr(routes_catalog, "FIRST_SYNC_DELAY_S", 0.0)

    class Holder:  # A gateway stand-in; weakref needs a referenceable object.
        stopping = threading.Event()
        platform = types.SimpleNamespace(started=False)
    holder = Holder()
    thread = threading.Thread(target=routes_catalog._refresher, args=(weakref.ref(holder), service, 0.01), daemon=True)
    thread.start()
    time.sleep(0.1)
    assert calls == []  # Not started: no seed import, no network sync.
    holder.platform.started = True
    for _ in range(200):
        if "sync" in calls:
            break
        time.sleep(0.01)
    holder.stopping.set()
    thread.join(2)
    assert calls[:2] == ["seed", "sync"] and not thread.is_alive()
