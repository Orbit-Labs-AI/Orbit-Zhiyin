import pytest

from tandem_catalog import query
from tandem_catalog.contracts import MatchRequest
from tandem_catalog.service import CatalogService

PAYLOAD = {"kind": "skill", "name": "Flaky test triage", "summary": "Generated retry triage skill",
           "body": "# Triage\r\nRe-run the failing pytest case with -x and bisect flaky fixtures.\r\n",
           "agents": ["claude_code"], "features": [{"feature": "domain", "value": "testing", "origin": "declared"}],
           "template_id": "skill-basic", "template_version": "1", "job_id": "job-1",
           "self_check": {"passed": True, "checks": [{"name": "frontmatter", "ok": True}]}}


@pytest.fixture
def service(tmp_path):
    service = CatalogService(tmp_path / "catalog.db")
    yield service
    service.close()


def test_local_item_is_idempotent_searchable_and_listed(service):
    first = service.add_local(PAYLOAD)
    assert first["created"] and first["item_id"].startswith("local:")
    again = service.add_local({**PAYLOAD, "body": PAYLOAD["body"].replace("\r\n", "\n") + "\n\n", "name": "Renamed"})
    assert again == {**first, "created": False}
    detail = query.get_item(service.store, first["item_id"])
    assert detail["origin"] == "local" and detail["license"] == "user-generated" and detail["name"] == "Flaky test triage"
    assert detail["readme"].startswith("# Triage\nRe-run")
    assert {"feature": "generic", "value": "0"}.items() <= next(f for f in detail["features"] if f["feature"] == "generic").items()
    assert detail["install"]["installable"]
    assert query.list_items(service.store, origin="local")["total"] == 1
    hits = service.match(MatchRequest(text="flaky fixtures bisect"))["items"]
    assert hits[0]["item_id"] == first["item_id"]
    assert all(s["source_id"] != "local" or s["enabled"] == 0 for s in service.store.sources())  # Never synced.


@pytest.mark.parametrize(("self_check", "error"), [(None, "self_check_required"), ({"passed": False}, "self_check_failed"),
                                                    ({"checks": []}, "self_check_failed")])
def test_self_check_is_required(service, self_check, error):
    with pytest.raises(ValueError, match=error):
        service.add_local({**PAYLOAD, "self_check": self_check})


def test_remove_local_retires_item_and_rejects_remote_ids(service):
    item_id = service.add_local(PAYLOAD)["item_id"]
    assert service.remove_local(item_id)
    assert query.get_item(service.store, item_id)["status"] == "deleted"
    assert not service.match(MatchRequest(text="flaky fixtures bisect"))["items"]
    assert not service.remove_local(item_id)
    with pytest.raises(ValueError, match="not_a_local_item"):
        service.remove_local("tandem-seeds:x")
    assert service.add_local(PAYLOAD)["created"]  # Re-adding restores it.
    assert service.store.verify()["ok"]
