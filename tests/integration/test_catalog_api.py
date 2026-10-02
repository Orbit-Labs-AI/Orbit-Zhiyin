import time

from fastapi.testclient import TestClient

from tandem_catalog.api import create_catalog_app
from tandem_catalog.service import CatalogService


def wait_job(client, job_id):
    for _ in range(300):
        state = client.get("/v1/catalog/jobs/" + job_id).json()
        if state["status"] in ("completed", "failed", "cancelled"):
            return state
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_api_builds_searches_and_keeps_disabled_sources_disabled(tmp_path):
    service = CatalogService(tmp_path / "catalog.db")
    with TestClient(create_catalog_app(service)) as client:
        response = client.post("/v1/catalog/sync", json={"source_ids": ["tandem-seeds"]})
        assert response.status_code == 202
        assert wait_job(client, response.json()["job_id"])["status"] == "completed"
        result = client.post("/v1/catalog/search", json={"text": "调试", "types": ["skill"]}).json()
        assert result["contract"] == "catalog-match-v1" and result["items"]
        item_id = result["items"][0]["item_id"]
        detail = client.get("/v1/catalog/items/detail", params={"item_id": item_id}).json()
        assert detail["version_id"] == result["items"][0]["version_id"]
        from tandem_backend.recommend.sources.normalize import catalog_resource
        draft = catalog_resource(detail["resource"])
        assert draft.identity.id == item_id
        assert draft.evidence_quality.status == "draft"
        assert draft.source.status == "draft"
        assert client.post("/v1/catalog/embeddings", json={}).status_code == 422
        assert client.post("/v1/catalog/sync", json={"source_ids": ["not-registered"]}).status_code == 422
        assert client.post("/v1/catalog/search", json={"limit": 5000}).status_code == 422
        assert client.put("/v1/catalog/sources/tandem-seeds", json={"enabled": False}).status_code == 200
        assert client.post("/v1/catalog/search", json={"text": "调试"}).json()["items"] == []
        assert client.get("/v1/catalog/jobs/missing").status_code == 404
        assert service.store.verify()["ok"]
    reopened = CatalogService(tmp_path / "catalog.db")
    try:
        assert next(s for s in reopened.store.sources() if s["source_id"] == "tandem-seeds")["enabled"] == 0
    finally:
        reopened.close()


def test_existing_backend_exposes_catalog_without_replacing_legacy_catalog(tmp_path):
    from tandem_backend.api import create_app
    with TestClient(create_app(tmp_path / "history.sqlite")) as client:
        assert len(client.get("/v1/catalog").json()) == 10
        assert client.get("/v1/catalog/status").json()["contract"] == "catalog-v1"
        assert client.get("/v1/catalog/match-analysis").json()["batches"] == []
