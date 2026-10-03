from fastapi.testclient import TestClient

from orbit_catalog.api import create_catalog_app
from orbit_catalog.contracts import Record, Resource
from orbit_catalog.service import CatalogService

from .test_local import PAYLOAD
from .test_storage import publish


def make_client(tmp_path, decorate=None):
    service = CatalogService(tmp_path / "catalog.db")
    rows = [Record(native_id=f"n{n}", resource=Resource(item_id=f"seed:{n}", type="skill" if n % 2 else "hook",
            name=f"Retry helper {n}", summary="retry flaky tests", url="https://x", agents=["codex"])) for n in range(6)]
    rows.append(Record(native_id="m", resource=Resource(item_id="model:x", type="model", name="X", url="u",
                       metadata={"provider": "acme", "model_id": "x"})))
    publish(service.store, rows, source="orbit-seeds")
    return TestClient(create_catalog_app(service, decorate)), service


def test_list_facets_detail_and_search_endpoints(tmp_path):
    marked = []
    client, service = make_client(tmp_path, decorate=lambda cards: marked.extend(c["item_id"] for c in cards))
    with client:
        assert client.get("/v1/catalog/status").json() == service.store.stats()
        page = client.get("/v1/catalog/items", params={"kind": ["skill"], "limit": 2, "sort": "name"}).json()
        assert page["total"] == 3 and len(page["items"]) == 2 and page["next_cursor"]
        rest = client.get("/v1/catalog/items", params={"kind": "skill", "limit": 2, "sort": "name",
                                                       "cursor": page["next_cursor"]}).json()
        assert rest["total"] is None and len(rest["items"]) == 1
        assert client.get("/v1/catalog/items", params={"sort": "nope"}).status_code == 422
        assert client.get("/v1/catalog/items", params={"cursor": "%%%"}).status_code == 422
        facets = client.get("/v1/catalog/facets", params={"kind": "hook"}).json()
        assert facets["total"] == 3 and {f["value"] for f in facets["kind"]} == {"skill", "hook"}
        detail = client.get("/v1/catalog/items/seed:1").json()
        assert detail["item_id"] == "seed:1" and "permissions" in detail and "related" in detail
        assert client.get("/v1/catalog/items/detail", params={"item_id": "seed:1"}).json()["resource"]["item_id"] == "seed:1"
        missing = client.get("/v1/catalog/items/nope")
        assert missing.status_code == 404 and missing.json()["detail"] == "catalog_item_not_found"
        found = client.get("/v1/catalog/search", params={"q": "retr", "kind": "skill"}).json()
        assert found["items"] and all(i["kind"] == "skill" and "snippet" in i and "score" in i for i in found["items"])
        assert client.get("/v1/catalog/search", params={"q": " "}).status_code == 422
        assert {"seed:1"} <= set(marked)


def test_local_models_and_benchmark_endpoints(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        created = client.post("/v1/catalog/local", json=PAYLOAD)
        assert created.status_code == 201 and created.json()["created"]
        item_id = created.json()["item_id"]
        assert client.post("/v1/catalog/local", json=PAYLOAD).status_code == 200
        missing = client.post("/v1/catalog/local", json={k: v for k, v in PAYLOAD.items() if k != "self_check"})
        assert missing.status_code == 422 and missing.json()["detail"] == "self_check_required"
        assert client.delete("/v1/catalog/local/seed:1").status_code == 422
        assert client.delete("/v1/catalog/local/" + item_id).status_code == 204
        assert client.delete("/v1/catalog/local/" + item_id).status_code == 404
        models = client.get("/v1/catalog/models").json()
        assert models["items"][0]["canonical_id"] == "acme/x" and models["items"][0]["context_window"] is None
        assert client.get("/v1/catalog/models/acme/x").json()["benchmarks"] == []
        assert client.get("/v1/catalog/models/none").status_code == 404
        assert client.get("/v1/catalog/benchmarks").json()["items"] == []
        assert client.get("/v1/catalog/models", params={"sort": "bogus"}).status_code == 422
