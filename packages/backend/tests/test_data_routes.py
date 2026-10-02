import fcntl
import json
import os
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tandem_data.maintenance import PURGE_CONFIRMATION
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store
from tandem_data.validation.fixtures import create_sources

from tandem_backend.api import data_routes

SECRET = "sk-proj-" + "Q1w2E3r4T5y6U7i8O9p0"


@pytest.fixture
def home(tmp_path):
    roots = create_sources(tmp_path / "fixtures")
    row = {
        "sessionId": "secret-session",
        "cwd": "/tandem-demo",
        "timestamp": "2026-10-02T00:00:00Z",
        "type": "user",
        "uuid": "secret-u",
        "message": {"role": "user", "content": f"请修复第 7 个问题 key {SECRET}"},
    }
    secret = roots["claude_code"] / "projects/demo/secret-session.jsonl"
    secret.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    home = tmp_path / "home"
    with Store(home) as store:
        service = ImportService(store)
        for agent, root in roots.items():
            service.import_source(ImportRequest(agent, root))
    return home


@pytest.fixture
def client(home):
    return TestClient(data_routes.register(FastAPI(), home))


def test_search_routes(client):
    response = client.get("/v1/search", params={"q": "修复第 7"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1 and SECRET not in response.text
    assert "<redacted:api_key>" in body["hits"][0]["snippet"]
    everything = client.get("/v1/search", params={"q": "git status"}).json()
    sources = {hit["source_id"] for hit in everything["hits"]}
    split = sum(
        client.get("/v1/search", params={"q": "git status", "source_id": sid}).json()["total"]
        for sid in sources
    )
    both = client.get(
        "/v1/search", params=[("q", "git status"), *(("source_id", sid) for sid in sources)]
    ).json()
    assert split == everything["total"] == both["total"]
    assert client.get("/v1/search").status_code == 422
    assert client.get("/v1/search", params={"q": "x", "limit": 0}).status_code == 422
    bad_window = client.get("/v1/search", params={"q": "x", "from_ts": 2, "until_ts": 1})
    assert bad_window.status_code == 422


def test_search_without_database(tmp_path):
    client = TestClient(data_routes.register(FastAPI(), tmp_path / "none"))
    assert client.get("/v1/search", params={"q": "x"}).status_code == 404
    assert client.get("/v1/sessions/s/resume").status_code == 404
    assert client.get("/v1/storage").json()["total_bytes"] == 0


def test_resume_route_never_spawns(client, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(os, "system", lambda *a, **k: calls.append(a))
    session = client.get("/v1/search", params={"q": "git status"}).json()["hits"][0]
    response = client.get(f"/v1/sessions/{session['session_uid']}/resume")
    assert response.status_code == 200
    assert response.json()["agent"] == session["agent"]
    assert client.get("/v1/sessions/session_missing/resume").status_code == 404
    assert calls == []


def test_capabilities_route_caches(client, home):
    first = client.get("/v1/sources/capabilities").json()
    assert first["cache"] == "miss" and first["sources"]
    assert client.get("/v1/sources/capabilities").json()["cache"] == "hit"
    assert (
        client.get("/v1/sources/capabilities", params={"refresh": True}).json()["cache"] == "miss"
    )


def test_storage_and_purge_routes(client, home):
    usage = client.get("/v1/storage").json()
    assert usage["layers"]["l2"] > 0
    assert client.post("/v1/storage/purge", json={"confirm": "yes"}).status_code == 400
    assert client.post("/v1/storage/purge", json={}).status_code == 422
    descriptor = os.open(home / "import.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        busy = client.post("/v1/storage/purge", json={"confirm": PURGE_CONFIRMATION})
        assert busy.status_code == 409
    finally:
        os.close(descriptor)
    assert (home / "tandem.db").exists()
    done = client.post("/v1/storage/purge", json={"confirm": PURGE_CONFIRMATION})
    assert done.status_code == 200 and done.json()["deleted_files"] > 0
    assert not (home / "tandem.db").exists()
    assert client.post("/v1/storage/purge", json={"confirm": PURGE_CONFIRMATION}).status_code == 400


def test_privacy_routes(client):
    listing = client.get("/v1/privacy/rules").json()
    assert listing["count"] == len(listing["rules"])
    response = client.post("/v1/privacy/preview", json={"text": f"key {SECRET}"})
    assert response.status_code == 200
    assert response.json()["matches"] == {"api_key": 1} and SECRET not in response.text
    assert client.post("/v1/privacy/preview", json={}).status_code == 422
    too_long = "x" * 100_001
    assert client.post("/v1/privacy/preview", json={"text": too_long}).status_code == 422


def test_register_alongside_application_routes(tmp_path, home):
    from tandem_backend.api.routes import create_app

    app = create_app(home=home, catalog_cache=tmp_path / "catalog.json")
    data_routes.register(app, home)
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/v1/privacy/rules").status_code == 200
    paths = [
        (route.path, tuple(sorted(getattr(route, "methods", ()) or ()))) for route in app.routes
    ]
    assert len(paths) == len(set(paths))
