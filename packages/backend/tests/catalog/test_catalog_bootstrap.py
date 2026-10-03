"""First start of the catalog: offline official items, seed import, refresher; no network."""

from __future__ import annotations

import json
import threading
import time
import types
import weakref
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbit_backend.services import routes_catalog
from orbit_backend.services.gateway import Gateway

TOKEN = "synthetic-test-token-0123456789abcdef"


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("catalog tests must not reach the network")
    monkeypatch.setattr("orbit_catalog.network.HttpClient.get", no_network)
    gw = Gateway(tmp_path / "home", discovery=lambda: [], prewarm_debounce_s=3600.0)
    client = TestClient(gw.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                        headers={"Authorization": f"Bearer {TOKEN}"})
    yield gw, client
    gw.stopping.set()  # Ends the refresher thread of this gateway.


def service_of(gw):
    from orbit_catalog import get_service
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
    assert coverage["by_source"]["orbit-kb"]["items"] == 25 and coverage["by_kind"]["hook"] >= 3
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
    assert coverage["by_source"]["orbit-kb"]["error"] is None


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


GEMINI = Path(__file__).resolve().parents[3] / "catalog/tests/fixtures/library/gemini_mini.json"


class OnlyGemini:
    """Injected fetcher: the Gemini extension list answers, every other host is down."""

    def json(self, url, immutable=False):
        if url == "https://geminicli.com/extensions.json":
            return json.loads(GEMINI.read_text())
        raise RuntimeError("http_500")

    def get(self, url, immutable=False):
        raise RuntimeError("http_500")

    def get_many(self, urls, workers=12, immutable=False):
        raise RuntimeError("http_500")


def wait_first_sync(client, states=("completed", "failed", "cancelled")):
    for _ in range(3000):
        first = client.get("/v1/catalog/status").json()["first_sync"]
        if first["state"] in states:
            return first
        time.sleep(0.01)
    raise AssertionError(f"first sync did not finish: {first}")


def test_fresh_install_schedules_one_first_sync_without_blocking(gateway, monkeypatch):
    gw, client = gateway
    monkeypatch.setattr(routes_catalog, "FIRST_RUN_DELAY_S", 0.0)
    service = service_of(gw)
    service.http = OnlyGemini()
    assert service.needs_network_sync()
    assert client.get("/v1/catalog/status").json()["first_sync"]["state"] == "pending"

    gw.platform.started = True  # The refresher polls once a second.
    first = wait_first_sync(client)
    assert first["job_id"] and first["sources"]["completed"] >= 1
    assert "mcp-official" in first["sources"]["failed"]
    assert not service.needs_network_sync()
    gemini = client.get("/v1/catalog/items", params={"source_id": "gemini-extensions"}).json()
    assert gemini["total"] >= 1
    # Reads keep working on the seeded library while other sources failed.
    assert client.get("/v1/catalog/items", params={"kind": "hook"}).json()["total"] >= 3


def test_first_sync_respects_disabled_autosync(gateway, monkeypatch):
    gw, client = gateway
    monkeypatch.setenv("ORBIT_CATALOG_AUTOSYNC", "0")
    service = service_of(gw)
    service.http = OnlyGemini()
    gw.platform.started = True
    first = wait_first_sync(client, ("disabled",))
    assert first["job_id"] is None and service.needs_network_sync()


def test_first_sync_retries_soon_when_another_job_runs(monkeypatch):
    states, ticks = [], iter([None, {"job_id": "j1"}])
    service = types.SimpleNamespace(bootstrap=lambda: None, needs_network_sync=lambda: True,
                                    track_first_sync=lambda state, **kw: states.append((state, kw.get("job_id"))))
    monkeypatch.setattr(routes_catalog, "refresh_tick", lambda svc: next(ticks, None))
    monkeypatch.setattr(routes_catalog, "FIRST_RUN_DELAY_S", 0.0)

    class Holder:
        stopping = threading.Event()
        platform = types.SimpleNamespace(started=True)
    holder = Holder()
    thread = threading.Thread(target=routes_catalog._refresher, args=(weakref.ref(holder), service, 0.01), daemon=True)
    thread.start()
    for _ in range(200):
        if ("started", "j1") in states:
            break
        time.sleep(0.01)
    holder.stopping.set()
    thread.join(2)
    assert [s for s, _ in states] == ["scheduled", "deferred", "started"] and states[-1][1] == "j1"


def run_refresher(service, until, timeout_s=2.0):
    class Holder:
        stopping = threading.Event()
        platform = types.SimpleNamespace(started=True)
    holder = Holder()
    thread = threading.Thread(target=routes_catalog._refresher, args=(weakref.ref(holder), service, 0.01), daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not until():
        time.sleep(0.01)
    holder.stopping.set()
    thread.join(2)


def test_vector_tick_waits_for_the_first_sync(monkeypatch):
    calls = []
    service = types.SimpleNamespace(bootstrap=lambda: None, needs_network_sync=lambda: True,
                                    track_first_sync=lambda state, **kw: None,
                                    vector_tick=lambda: calls.append("vector"))
    monkeypatch.setattr(routes_catalog, "refresh_tick", lambda svc: calls.append("sync") or {"job_id": "j1"})
    monkeypatch.setattr(routes_catalog, "FIRST_RUN_DELAY_S", 0.0)
    monkeypatch.setattr(routes_catalog, "VECTOR_TICK_S", 0.0)
    monkeypatch.delenv("ORBIT_CATALOG_AUTOEMBED", raising=False)
    monkeypatch.setenv("ORBIT_CATALOG_AUTOSYNC", "1")
    run_refresher(service, lambda: calls.count("vector") >= 2)
    assert calls[0] == "sync" and calls.count("vector") >= 2


def test_autoembed_follows_autosync_unless_set(monkeypatch):
    calls = []
    service = types.SimpleNamespace(bootstrap=lambda: None, needs_network_sync=lambda: True,
                                    track_first_sync=lambda state, **kw: None,
                                    vector_tick=lambda: calls.append("vector"))
    monkeypatch.setattr(routes_catalog, "VECTOR_TICK_S", 0.0)
    monkeypatch.setenv("ORBIT_CATALOG_AUTOSYNC", "0")
    monkeypatch.delenv("ORBIT_CATALOG_AUTOEMBED", raising=False)
    run_refresher(service, lambda: False, timeout_s=0.2)
    assert calls == []
    # Offline install that still wants local vectors: no network sync is pending a turn.
    monkeypatch.setenv("ORBIT_CATALOG_AUTOEMBED", "1")
    run_refresher(service, lambda: bool(calls))
    assert calls


def test_status_reports_vector_block_and_consent(gateway):
    gw, client = gateway
    vector = client.get("/v1/catalog/status").json()["vector"]
    assert vector["download"]["allowed"] is False
    assert vector["download"]["revision"] == "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    assert vector["status"] in ("not_configured", "not_loaded", "unavailable")  # a dev machine may hold a model
    declined = client.put("/v1/catalog/embeddings/model", json={"allow_download": False}).json()
    assert declined["download"]["allowed"] is False
    assert json.loads((gw.home / "models/download.json").read_text())["allowed"] is False
    assert client.get("/v1/catalog/embeddings/status").json()["download"]["allowed"] is False
