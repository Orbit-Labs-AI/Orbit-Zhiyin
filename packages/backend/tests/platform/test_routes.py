from __future__ import annotations

import stat
from pathlib import Path


def test_platform_endpoints(gateway_client, tmp_path):
    client, gateway = gateway_client
    health = client.get("/v1/platform/health")
    assert health.status_code == 200 and health.json()["status"] in ("ok", "degraded")
    assert "server-timing" in health.headers and "x-request-id" in health.headers
    deep = client.get("/v1/platform/health", params={"deep": 1}).json()
    assert any(c["id"] == "app_db" for c in deep["checks"])

    assert client.get("/v1/platform/metrics").json() == {"enabled": False, "window_s": 3600,
                                                         "series": []}
    tele = client.get("/v1/platform/telemetry").json()
    assert tele["enabled"] is False and set(tele["stats"]) == {"series", "rows", "bytes_est",
                                                               "since"}
    bad = client.put("/v1/platform/telemetry", json={"retention_days": 99})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    assert client.put("/v1/platform/telemetry", json={"bogus": 1}).status_code == 422
    on = client.put("/v1/platform/telemetry", json={"enabled": True, "slow_ms": 200}).json()
    assert on["enabled"] is True and on["slow_ms"] == 200 and gateway.platform.slow_ms == 200
    client.get("/v1/platform/flags")
    gateway.platform.telemetry.flush(force=True)
    metrics = client.get("/v1/platform/metrics",
                         params={"name": "http.request", "step": "total",
                                 "tag.route": "/v1/platform/flags"}).json()
    assert metrics["enabled"] is True and metrics["series"][0]["count"] >= 1
    assert client.delete("/v1/platform/telemetry/data").json()["deleted_rows"] >= 1

    flags = client.get("/v1/platform/flags").json()
    assert flags == {"notifications": True, "slow_log": True, "maintenance": True,
                     "json_logs": True}
    assert client.put("/v1/platform/flags", json={"slow_log": False}).json()["slow_log"] is False
    assert client.put("/v1/platform/flags", json={"nope": True}).status_code == 422

    storage = client.get("/v1/platform/storage").json()
    assert {c["id"] for c in storage["components"]} >= {"orbit_db", "app_db", "logs"}

    status = client.get("/v1/platform/maintenance").json()
    assert status["wal_checkpoint"]["interval_s"] == 300
    run = client.post("/v1/platform/maintenance/run", json={"task": "optimize"}).json()
    assert run["ok"] is True and run["task"] == "optimize"
    unknown = client.post("/v1/platform/maintenance/run", json={"task": "nope"})
    assert unknown.status_code == 422

    diag = client.get("/v1/platform/diagnostics").json()
    assert diag["app"]["version"] and diag["home"] == "~" or diag["home"].startswith("~")
    export = client.post("/v1/platform/diagnostics/export").json()
    assert set(export) == {"path", "bytes", "sha256", "files"}
    assert stat.S_IMODE(Path(export["path"]).stat().st_mode) == 0o600


def test_data_routes_conditional_get(gateway_client):
    client, gateway = gateway_client
    gateway.revisions.update(data_rev=None)
    # No canonical database: the rule yields no tag and the request is not short-circuited.
    response = client.get("/v1/sources", headers={"If-None-Match": "*"})
    assert response.status_code != 304 and "etag" not in response.headers


def test_job_events_feed_metrics(gateway_client):
    _, gateway = gateway_client
    gateway.platform.settings.put_telemetry({"enabled": True})
    gateway.platform.refresh()
    gateway._emit("job", "job", {"id": "j1", "kind": "import", "status": "running"})
    gateway._emit("job", "job", {"id": "j1", "kind": "import", "status": "failed",
                                 "error": {"code": "boom"}})
    names = {s["name"]: s for s in gateway.platform.telemetry.query(None, 600, "total")["series"]}
    assert names["job.duration"]["tags"] == {"kind": "import", "status": "failed"}
    assert names["error"]["tags"] == {"area": "job", "code": "boom"}


def test_status_reports_collection_and_badge(gateway_client):
    client, gateway = gateway_client
    body = client.get("/v1/status").json()
    assert body["collection"] == {"paused": False} and body["badge"] == 0
    gateway.platform.collection.pause()
    gateway.platform.notifier.emit({"type": "system", "kind": "test", "title": "t",
                                    "dedupe_key": "test:1"})
    body = client.get("/v1/status").json()
    assert body["collection"] == {"paused": True} and body["badge"] == 1


def test_recommend_settings_route(gateway_client):
    client, gateway = gateway_client
    assert client.get("/v1/platform/recommend").json() == {"ai_generate": False, "level": None}
    out = client.put("/v1/platform/recommend", json={"ai_generate": True, "level": 2}).json()
    assert out == {"ai_generate": True, "level": 2} == gateway.rec_settings
    for bad in ({"level": 9}, {"ai_generate": "yes"}, {"nope": 1}):
        assert client.put("/v1/platform/recommend", json=bad).status_code == 422


def test_close_releases_area_services(tmp_path):
    from orbit_backend import features
    from orbit_backend.services.gateway import Gateway

    gateway = Gateway(tmp_path / "gw", discovery=lambda: [])
    closed = []

    class Closable:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    features.bind(Closable("features"))
    gateway._ai = Closable("ai")
    gateway.close()
    assert closed == ["features", "ai"] and features._service is None
