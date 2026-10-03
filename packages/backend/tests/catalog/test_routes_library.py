"""GET /v1/catalog/library and batch cards through the gateway; synthetic profile, no network."""

from __future__ import annotations

import re
import time

import pytest
from fastapi.testclient import TestClient

from orbit_backend.services.gateway import Gateway

TOKEN = "synthetic-test-token-0123456789abcdef"
LOCAL = {"kind": "skill", "name": "Retry triage", "summary": "generated", "body": "# Steps\nRe-run flaky pytest cases.",
         "agents": ["codex"], "self_check": {"passed": True, "checks": []}}

PROFILE = {"n_sessions": 12,
           "vector": {"domain:debugging": 1.0, "domain:testing": 0.7, "friction:retry_same_call": 0.5},
           "tags": [{"id": "domain:debugging", "label": "debugging", "sessions": 9},
                    {"id": "domain:testing", "label": "testing", "sessions": 5},
                    {"id": "friction:retry_same_call", "label": "失败后重试", "sessions": 4}],
           "groups": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("catalog tests must not reach the network")
    monkeypatch.setattr("orbit_catalog.network.HttpClient.get", no_network)
    gateway = Gateway(tmp_path / "home", discovery=lambda: [], prewarm_debounce_s=3600.0)
    yield TestClient(gateway.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                     headers={"Authorization": f"Bearer {TOKEN}"})


def wait_job(client, job_id):
    for _ in range(500):
        state = client.get(f"/v1/catalog/jobs/{job_id}").json()
        if state["status"] in ("completed", "failed", "cancelled"):
            return state
        time.sleep(0.01)
    raise AssertionError("catalog job did not finish")


@pytest.fixture
def seeded(client):
    job = client.post("/v1/catalog/sync", json={"source_ids": ["orbit-seeds"]}).json()
    assert wait_job(client, job["job_id"])["status"] == "completed"
    local = client.post("/v1/catalog/local", json=LOCAL).json()
    return client, local["item_id"]


@pytest.fixture
def with_features(monkeypatch, seeded):
    from orbit_backend import features
    client, local_id = seeded
    calls = []
    monkeypatch.setattr(features, "current", lambda: object())
    monkeypatch.setattr(features, "profile", lambda scope=None, **kw: calls.append(scope) or PROFILE)
    linked = {"items": [{"inv_id": "i1", "agent": "codex", "scope": "user", "status": "active",
                         "orbit_installed": True,
                         "catalog": {"item_id": local_id, "method": "ledger", "confidence": 1.0}},
                        {"inv_id": "i2", "agent": "claude_code", "scope": "user", "status": "unused",
                         "orbit_installed": False, "catalog": None}]}
    monkeypatch.setattr(features, "linked_inventory", lambda *a, **k: linked)
    return client, local_id, calls


def test_library_for_tab_returns_parts_reasons_and_installed(with_features):
    client, local_id, calls = with_features
    response = client.get("/v1/catalog/library", params={"limit": 50, "project_id": "p1"})
    assert response.status_code == 200
    body = response.json()
    assert calls and calls[-1]["project_ids"] == ["p1"] and calls[-1]["from_ts"] > 0
    assert body["weights"] == {"feature_overlap": 0.5, "friction": 0.3, "trust": 0.2}
    assert body["profile_basis"]["ok"] and body["profile_basis"]["n_sessions"] == 12
    assert body["profile_basis"]["window_days"] == 30 and body["profile_basis"]["scope_hash"]
    assert body["installed_summary"] == {"orbit": 1, "manual": 1}
    items = body["items"]
    assert items and [i["m"] for i in items] == sorted((i["m"] for i in items), reverse=True)
    assert all(0 <= v <= 1 for i in items for v in i["parts"].values())
    top = items[0]
    assert top["parts"]["feature_overlap"] > 0 and any("个会话" in w for w in top["why"])
    local = next(i for i in items if i["id"] == local_id)
    assert local["installed"] == {"state": "active", "agents": ["codex"], "scope": "user"} and local["local"]

    excluded = client.get("/v1/catalog/library", params={"exclude": [top["id"]], "limit": 50}).json()
    assert top["id"] not in {i["id"] for i in excluded["items"]} and excluded["hidden_excluded"] == 1
    only_local = client.get("/v1/catalog/library", params={"tab": "local"}).json()
    assert [i["id"] for i in only_local["items"]] == [local_id]
    assert client.get("/v1/catalog/library", params={"sort": "hot"}).status_code == 422
    assert client.get("/v1/catalog/library", params={"limit": 51}).status_code == 422


def test_library_without_profile_is_not_personal(seeded, monkeypatch):
    from orbit_backend import features
    client, _ = seeded
    monkeypatch.setattr(features, "current", lambda: None)
    body = client.get("/v1/catalog/library", params={"limit": 50}).json()
    assert body["profile_basis"]["ok"] is False and body["items"]
    assert all(not re.search(r"\d", w) for i in body["items"] for w in i["why"])
    assert all(i["parts"]["friction"] == 0 for i in body["items"])


def test_library_etag_batch_cards_and_detail_scan(with_features):
    client, local_id, _ = with_features
    first = client.get("/v1/catalog/library")
    tag = first.headers["etag"]
    assert client.get("/v1/catalog/library", headers={"If-None-Match": tag}).status_code == 304
    some = first.json()["items"][0]["id"]
    batch = client.get("/v1/catalog/items", params={"id": [local_id, "nope", some]}).json()
    assert [c["item_id"] for c in batch["items"]] == [local_id, some] and batch["missing"] == ["nope"]
    assert batch["items"][0]["installed"]["state"] == "active"
    assert client.get("/v1/catalog/items", params={"id": [f"x{n}" for n in range(51)]}).status_code == 422
    detail = client.get(f"/v1/catalog/items/{local_id}").json()
    assert detail["scan"]["estimate"] is True and detail["scan"]["verdict"] in ("safe", "caution", "dangerous")
    assert detail["source_label"] == "本地" and detail["compat_label"] == "Codex"
    assert {"stars_scope", "updated_scope", "license_spdx"} <= set(detail)
