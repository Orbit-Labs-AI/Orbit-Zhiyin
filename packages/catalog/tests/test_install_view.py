"""B16: install lookups read only the stored document; ``?type=`` filters like ``?kind=``."""

from fastapi.testclient import TestClient

from orbit_catalog.api import create_catalog_app
from orbit_catalog.contracts import Record, Resource
from orbit_catalog.service import CatalogService

from .test_storage import publish

HOOKS = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "sh \"${CLAUDE_PLUGIN_ROOT}/h.sh\""}]}]}}


def make(tmp_path):
    service = CatalogService(tmp_path / "catalog.db")
    publish(service.store, [
        Record(native_id="p", resource=Resource(item_id="plugin:x", type="plugin", name="x", url="https://x",
                                                components=["hook:x"])),
        Record(native_id="h", resource=Resource(item_id="hook:x", type="hook", name="x hooks", url="https://x/h",
                                                manifest=HOOKS, body="secret body")),
        Record(native_id="s", resource=Resource(item_id="skill:y", type="skill", name="y", url="https://y")),
    ], source="orbit-seeds")
    return service


def test_install_view_is_lean_and_names_parent(tmp_path, monkeypatch):
    service = make(tmp_path)
    store = service.store
    monkeypatch.setattr(type(store), "index", lambda *a, **k: (_ for _ in ()).throw(AssertionError("index built")))
    view = store.install_view("hook:x")
    assert view["resource"]["item_id"] == "hook:x" and view["resource"]["type"] == "hook"
    assert view["resource"]["manifest"] == HOOKS and "body" not in view["resource"]
    assert view["resource"]["status"] == "active" and view["parents"] == ["plugin:x"]
    assert store.install_view("nope") is None


def test_items_type_param_filters(tmp_path):
    service = make(tmp_path)
    with TestClient(create_catalog_app(service)) as client:
        by_type = client.get("/v1/catalog/items", params={"type": "hook"}).json()
        assert [i["item_id"] for i in by_type["items"]] == ["hook:x"]
        assert client.get("/v1/catalog/items", params={"kind": "hook"}).json()["items"] == by_type["items"]
