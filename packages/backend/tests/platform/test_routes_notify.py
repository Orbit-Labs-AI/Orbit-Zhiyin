"""HTTP surface of notifications, attention queue and collection pause."""
# ruff: noqa: F811  (fixtures are imported from notify_fake and then used as parameters)

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

from notify_fake import clock, gw  # noqa: E402,F401

from tandem_backend.platform.collection import Collection  # noqa: E402
from tandem_backend.platform.notify import Notifier  # noqa: E402
from tandem_backend.platform.routes_notify import router  # noqa: E402
from tandem_backend.services.gateway import install_error_handlers  # noqa: E402


@pytest.fixture
def client(gw, clock):
    gw.platform.notifier = Notifier(gw, clock=clock).start()
    gw.platform.collection = Collection(gw, clock=clock)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router(gw))
    return TestClient(app)


def test_listing_attention_and_ack(client, gw):
    notifier = gw.platform.notifier
    wait = notifier.emit({"type": "waiting", "title": "等待审批", "session_uid": "s1"})
    notifier.emit({"type": "stuck", "title": "失败", "session_uid": "s2"})
    notifier.emit({"type": "done", "title": "完成", "session_uid": "s3"})
    body = client.get("/v1/notifications").json()
    assert body["active_count"] == 3 and body["urgent_count"] == 1
    assert body["by_type"] == {"awaiting_approval": 1, "failing": 1, "just_finished": 1}
    assert body["policy_rev"] > 0
    assert set(body["items"][0]) >= {"id", "type", "channels", "state", "count", "ts"}
    assert len(client.get("/v1/notifications?type=done").json()["items"]) == 1
    assert client.get("/v1/notifications?type=bogus").status_code == 422
    assert client.get("/v1/notifications?state=nope").status_code == 422
    page = client.get(f"/v1/notifications?state=all&limit=1&before_id={wait + 1}").json()
    assert [i["id"] for i in page["items"]] == [wait]
    items = client.get("/v1/notifications/attention").json()["items"]
    assert [i["type"] for i in items] == ["awaiting_approval", "failing"]
    assert set(items[0]) == {"id", "type", "severity", "session_uid", "title", "body", "count",
                             "since", "last_ts", "payload"}
    acked = client.post(f"/v1/notifications/{wait}/ack", json={"snooze_s": 3600}).json()
    assert acked["state"] == "acked" and acked["snoozed_until"] > 0
    muted = client.post(f"/v1/notifications/{items[1]['id']}/ack",
                        json={"mute_type": True}).json()
    assert muted["muted_type"] == "failing"
    assert client.post("/v1/notifications/999/ack").status_code == 404
    assert client.post("/v1/notifications/1/ack", json={"snooze_s": 0}).status_code == 422
    assert client.post("/v1/notifications/ack_all").json() == {"acked": 1}
    assert len(client.get("/v1/notifications?state=acked").json()["items"]) == 3


def test_snooze_test_and_policy(client):
    out = client.post("/v1/notifications/snooze", json={"seconds": 1800}).json()
    assert out["scope"] == "global" and out["until"] > 0
    assert client.post("/v1/notifications/snooze", json={"seconds": 10}).status_code == 422
    assert client.post("/v1/notifications/snooze",
                       json={"seconds": 600, "scope": "type:ctx"}).json()["scope"] == \
        "type:context_pressure"
    assert client.post("/v1/notifications/snooze",
                       json={"seconds": 600, "scope": "bad"}).status_code == 422
    assert len(client.get("/v1/notifications/snooze").json()["items"]) == 2
    assert client.delete("/v1/notifications/snooze?scope=global").json() == {"scope": "global"}
    test = client.post("/v1/notifications/test").json()
    assert test["channels"] == ["banner", "badge"] and test["id"] > 0
    policy = client.get("/v1/notifications/policy").json()
    assert policy["matrix"]["context_pressure"] == ["hud"] and "updated_at" in policy
    put = client.put("/v1/notifications/policy", json={"quiet_hours": {"enabled": True}})
    assert put.status_code == 200 and put.json()["quiet_hours"]["enabled"] is True
    bad = client.put("/v1/notifications/policy", json={"matrix": {"failing": ["sms"]}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    quiet = client.put("/v1/notifications/policy?preset=quiet").json()
    assert quiet["matrix"]["ai_job_done"] == [] and quiet["matrix"]["just_finished"] == ["badge"]
    assert client.put("/v1/notifications/policy?preset=loud").status_code == 422


def test_collection_routes_and_alias(client, gw):
    status = client.get("/v1/platform/collection").json()
    assert status["paused"] is False and status["intervals"] == []
    paused = client.post("/v1/platform/collection/pause", json={"reason": "meeting"}).json()
    assert paused["paused"] is True and paused["reason"] == "meeting"
    assert client.get("/v1/app/collection").json()["paused"] is True
    resumed = client.post("/v1/app/collection/resume").json()
    assert set(resumed) == {"paused", "resumed_at", "paused_ms", "catch_up_job_id",
                            "catch_up_pending"}
    assert resumed["paused"] is False
    assert client.post("/v1/app/collection/pause").json()["reason"] == "user"
    assert len(client.get("/v1/platform/collection").json()["intervals"]) == 2


def test_sse_frames_on_notify_topic(client, gw):
    gw.platform.notifier.emit({"type": "waiting", "title": "x", "session_uid": "s"})
    frames, gap = gw.bus.since(0, {"notify"})
    assert not gap and [f.event for f in frames] == ["notification", "attention"]
    assert frames[0].data["channels"] == ["banner", "hud", "badge"]
    assert frames[1].data == {"active": 1, "urgent": 1, "by_type": {"awaiting_approval": 1}}
    assert b"event: notification" in frames[0].encode()


def test_missing_platform_returns_503(gw):
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router(SimpleNamespace(platform=None)))
    client = TestClient(app)
    response = client.get("/v1/notifications")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert client.post("/v1/platform/collection/pause").status_code == 503


def test_gateway_mounts_routes(tmp_path):
    """routes_platform includes the notify router over the Platform's notifier/collection."""
    from tandem_backend.services.gateway import Gateway

    token = "synthetic-test-token-0123456789abcdef"
    gateway = Gateway(tmp_path / "home", discovery=lambda: [])
    gateway.platform.notifier.start()
    try:
        client = TestClient(gateway.app(token=token, port=8765), base_url="http://127.0.0.1:8765",
                            headers={"Authorization": f"Bearer {token}"})
        assert client.post("/v1/notifications/test").status_code == 200
        assert client.get("/v1/notifications").json()["active_count"] == 1
        assert client.post("/v1/app/collection/pause").json()["paused"] is True
        frames, _ = gateway.bus.since(0, {"notify", "service"})
        assert {f.topic for f in frames} == {"notify", "service"}
    finally:
        gateway.close()
