import importlib.util
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tandem_backend import features
from tandem_backend.appdb import AppDB
from tandem_backend.services.gateway import install_error_handlers
from tandem_backend.services.routes_features import router

HAS_LINKED = importlib.util.find_spec("tandem_backend.features.linked") is not None
HAS_SEARCH = importlib.util.find_spec("tandem_backend.features.search") is not None


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


@pytest.mark.skipif(HAS_SEARCH, reason="search module merged")
def test_search_not_implemented(client):
    response = client.get("/v1/search", params={"q": "pytest"})
    assert response.status_code == 501 and response.json()["error"]["code"] == "not_implemented"


@pytest.mark.skipif(not HAS_SEARCH, reason="search module not merged yet")
def test_search_ok(seeded, client):
    assert client.get("/v1/search", params={"q": "s1"}).status_code == 200


@pytest.mark.skipif(HAS_LINKED, reason="linked module merged")
def test_linked_not_implemented(client):
    response = client.get("/v1/inventory/linked")
    assert response.status_code == 501 and response.json()["error"]["code"] == "not_implemented"


@pytest.mark.skipif(not HAS_LINKED, reason="linked module not merged yet")
def test_linked_ok(seeded, client):
    body = client.get("/v1/inventory/linked").json()
    assert {"items", "summary", "coverage"} <= set(body)


def test_module_helpers_are_functions():
    import tandem_backend.features.profile  # noqa: F401
    import tandem_backend.features.vocab  # noqa: F401

    for name in ("profile", "linked_inventory", "search", "vocab", "match_items"):
        assert callable(getattr(features, name)), name
    assert features.vocab()["version"] == "vocab-1"
