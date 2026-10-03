from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orbit_backend import features
from orbit_backend import platform as orbit_platform
from orbit_backend.appdb import AppDB
from orbit_backend.platform.middleware import PlatformMiddleware
from orbit_backend.platform.revisions import EtagRules, RevisionRegistry
from orbit_backend.services.gateway import install_error_handlers
from orbit_backend.services.routes_features import router


@pytest.fixture
def client(home, revs):
    appdb = AppDB(home / "app.db")
    gw = SimpleNamespace(home=home, appdb=appdb, revisions=SimpleNamespace(snapshot=revs))
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router(gw))
    with TestClient(app) as test_client:
        yield test_client
    features.get().close()
    features.bind(None)
    appdb.close()


def test_profile_endpoint(seeded, client):
    body = client.get("/v1/features/profile").json()
    assert body["n_sessions"] == 3 and "vector" not in body and "centroid" not in body
    assert {"scope_hash", "revs", "tags", "groups", "coverage", "cache"} <= set(body)
    scoped = client.get("/v1/features/profile", params={
        "project_id": "p1", "include": "vector,centroid,evidence"}).json()
    assert scoped["n_sessions"] == 2 and len(scoped["centroid"]) == 128
    assert "tool:shell" in scoped["vector"] and scoped["evidence"]
    assert client.get("/v1/features/profile", params={"agent": "codex"}).json()["n_sessions"] == 1
    bad = client.get("/v1/features/profile", params={"include": "nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_request"
    assert client.get("/v1/features/profile", params={"since": 5, "until": 1}).status_code == 400
    assert features.profile()["cache"] == "hit"  # module-level helper bound by router()


def test_vocab_endpoint(client):
    body = client.get("/v1/features/vocab").json()
    assert body["version"] == "vocab-1"
    assert {"head": "rm", "family": "fs", "cls": "destructive"} in body["commands"]
    assert body["ext_language"][".py"] == "python"
    assert {f["id"] for f in body["friction"]} >= {"friction:tool_error"}


def test_search_validation(client):
    for q in ("", "   ", "x" * 201):
        response = client.get("/v1/search", params={"q": q})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"


def test_search_ok(seeded, client):
    body = client.get("/v1/search", params={"q": "s1"}).json()
    assert {"q", "took_ms", "index", "counts", "results", "partial"} <= set(body)
    assert client.get("/v1/search", params={"q": "s1", "kinds": "nope"}).status_code == 400


def test_linked_ok(seeded, client):
    body = client.get("/v1/inventory/linked").json()
    assert {"items", "summary", "coverage"} <= set(body)
    assert client.get("/v1/features/linked").json()["summary"] == body["summary"]


def test_router_reuses_bound_service(home, revs):
    appdb = AppDB(home / "app.db")
    gw = SimpleNamespace(home=home, appdb=appdb, revisions=SimpleNamespace(snapshot=revs))
    try:
        router(gw)
        first = features.get()
        router(gw)
        assert features.get() is first
        router(SimpleNamespace(home=home, appdb=AppDB(home / "app2.db"),
                               revisions=SimpleNamespace(snapshot=revs)))
        assert features.get() is not first and first.hub.pool._shutdown
    finally:
        features.get().appdb.close()
        features.bind(None)
        appdb.close()


def test_conditional_get(seeded, home, revs):
    appdb = AppDB(home / "app.db")
    gw = SimpleNamespace(home=home, appdb=appdb, revisions=SimpleNamespace(snapshot=revs))
    pf = SimpleNamespace(etag_rules=EtagRules(), revisions=RevisionRegistry(), slow_ms=500,
                         slow_log=False)
    orbit_platform._set_platform(pf)
    try:
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(router(gw))
        app.add_middleware(PlatformMiddleware, platform=pf)
        with TestClient(app) as client:
            first = client.get("/v1/features/profile")
            tag = first.headers["etag"]
            assert client.get("/v1/features/profile",
                              headers={"If-None-Match": tag}).status_code == 304
            vocab = client.get("/v1/features/vocab").headers["etag"]
            assert client.get("/v1/features/vocab",
                              headers={"If-None-Match": vocab}).status_code == 304
            revs.value["data_rev"] = 2
            assert client.get("/v1/features/profile",
                              headers={"If-None-Match": tag}).status_code == 200
    finally:
        orbit_platform._set_platform(None)
        features.get().close()
        features.bind(None)
        appdb.close()


def test_module_helpers_are_functions():
    import orbit_backend.features.profile  # noqa: F401
    import orbit_backend.features.vocab  # noqa: F401

    for name in ("profile", "linked_inventory", "search", "vocab", "match_items"):
        assert callable(getattr(features, name)), name
    assert features.vocab()["version"] == "vocab-1"


def test_search_records_telemetry(seeded, client, monkeypatch):
    from orbit_backend.features import search_index

    seen = []
    monkeypatch.setattr(orbit_platform, "record", lambda name, value=1.0, **tags:
                        seen.append((name, tags)))
    monkeypatch.setattr(search_index, "record", lambda name, value=1.0, **tags:
                        seen.append((name, tags)))
    assert client.get("/v1/search", params={"q": "s1"}).status_code == 200
    names = [name for name, _ in seen]
    assert "features.search" in names
    assert any(n == "features.search_index" and t.get("mode") for n, t in seen)
