import sqlite3

import pytest

from orbit_backend.appdb import AppDB
from orbit_backend.services.routes_analytics import analytics_scope
from orbit_backend.sessionops import exclusion


def test_add_is_idempotent_and_list_orders_newest_first(home):
    db = AppDB(home / "app.db")
    try:
        first = exclusion.add(db, "s1", "test", now_ms=100)
        again = exclusion.add(db, "s1", "private", "note", now_ms=900)
        assert first["excluded_at"] == again["excluded_at"] == 100
        exclusion.add(db, "s2", now_ms=200)
        items = exclusion.list(db)
        assert [i["session_uid"] for i in items] == ["s2", "s1"]
        assert items[1]["reason"] == "private" and items[1]["note"] == "note"
        assert exclusion.excluded_uids(db) == ["s1", "s2"]
        assert exclusion.remove(db, "s1") and not exclusion.remove(db, "s1")
    finally:
        db.close()


def test_provider_merges_into_analytics_scope(home):
    db = AppDB(home / "app.db")
    try:
        exclusion.add(db, "s9", now_ms=1)
        exclusion.add(db, "s1", now_ms=2)
        exclusion.set_provider(lambda: exclusion.excluded_uids(db))
        scope = analytics_scope(excluded_session_uids=["s1", "x"])
        assert scope.excluded_session_uids == ["s1", "x", "s9"]
        assert analytics_scope().excluded_session_uids == ["s1", "s9"]
        # A broken provider is fail-closed: excluded (private) sessions must not leak back in.
        exclusion.set_provider(lambda: 1 / 0)
        with pytest.raises(exclusion.ExclusionsUnavailable) as failed:
            analytics_scope(excluded_session_uids=["x"])
        assert (failed.value.status, failed.value.code, failed.value.retryable) == (
            503, "exclusions_unavailable", True)
        exclusion.set_provider(None)  # no provider at all (CLI/tests): only the explicit list
        assert exclusion.merged(["x"]) == ["x"]
    finally:
        exclusion.set_provider(None)
        db.close()


def test_exclusion_endpoints(orbit, client):
    orbit.session("s1")
    orbit.session("s2", agent="codex", project="p2")
    assert client.post("/v1/sessions/nope/exclude", json={}).json()["error"]["code"] == "not_found"
    first = client.post("/v1/sessions/s1/exclude", json={"reason": "test", "note": "demo"})
    assert first.status_code == 200 and first.json()["excluded"] is True
    second = client.post("/v1/sessions/s1/exclude", json={"reason": "private"}).json()
    assert second["excluded_at"] == first.json()["excluded_at"]
    assert client.post("/v1/sessions/s2/exclude").status_code == 200
    bad = client.post("/v1/sessions/s2/exclude", json={"reason": "nope"})
    assert bad.status_code == 422
    assert client.post("/v1/sessions/s2/exclude", json={"note": "x" * 201}).status_code == 422
    body = client.get("/v1/sessions/excluded").json()
    assert body["count"] == 2
    s1 = next(i for i in body["items"] if i["session_uid"] == "s1")
    assert s1 | {"excluded_at": 0} == {
        "session_uid": "s1", "title": "Title s1", "agent": "claude_code", "project_id": "p1",
        "project": "Proj p1", "started_at": 1_760_000_000_000, "reason": "private",
        "note": None, "excluded_at": 0, "source": "user"}
    assert client.delete("/v1/sessions/s1/exclude").json() == {"session_uid": "s1",
                                                               "excluded": False}
    missing = client.delete("/v1/sessions/s1/exclude")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.get("/v1/sessions/excluded").json()["count"] == 1


def test_exclude_without_database_is_503(client):
    response = client.post("/v1/sessions/s1/exclude", json={})
    assert response.status_code == 503 and response.json()["error"]["code"] == "no_projection"
    assert client.get("/v1/sessions/excluded").json() == {"count": 0, "items": []}


def test_excluded_list_etag_changes_on_exclusion(orbit, client):
    orbit.session("s1")
    first = client.get("/v1/sessions/excluded")
    tag = first.headers["etag"]
    assert client.get("/v1/sessions/excluded", headers={"If-None-Match": tag}).status_code == 304
    client.post("/v1/sessions/s1/exclude", json={})
    fresh = client.get("/v1/sessions/excluded", headers={"If-None-Match": tag})
    assert fresh.status_code == 200 and fresh.json()["count"] == 1


def test_broken_exclusion_store_returns_503_not_private_sessions(orbit, client, gateway):
    orbit.session("s1")
    assert client.get("/v1/quota").status_code == 200

    def broken():
        raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

    exclusion.set_provider(broken)
    response = client.get("/v1/quota")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "exclusions_unavailable"
