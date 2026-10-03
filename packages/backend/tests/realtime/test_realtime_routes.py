from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from realtime_fixtures import Orbit

from orbit_backend.services.gateway import Gateway
from orbit_backend.services.routes_realtime import stream

TOKEN = "synthetic-test-token-0123456789abcdef"
PORT = 8765
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(home):
    gateway = Gateway(home, discovery=lambda: [], prewarm_debounce_s=3600.0)
    with TestClient(gateway.app(token=TOKEN, port=PORT), base_url=f"http://127.0.0.1:{PORT}",
                    headers=AUTH) as test_client:
        yield test_client, gateway
    gateway.realtime.close()


def seed(home):
    now = int(time.time() * 1000)
    t = Orbit(home)
    t.session("live", started=now - 60_000, title="修复构建")
    t.event("live", now - 50_000, actor="human")
    for i in range(3):
        t.call("live", now - 40_000 + i * 1000, head="npm install", status="failed",
               error_class="timeout")
    t.event("live", now - 5_000, actor="tool")
    t.session("done", started=now - 300_000)
    t.event("done", now - 200_000, actor="assistant")
    t.db.close()


def test_snapshot_before_orbit_db_is_idle(client):
    test_client, _ = client
    body = test_client.get("/v1/analytics/realtime").json()
    assert body["status"] == "idle" and body["sessions"] == []
    assert set(body["counts"]) == {"running", "awaiting_approval", "failing", "just_finished",
                                   "context_pressure", "idle"}


def test_snapshot_shape_lanes_and_dismiss(client, home):
    seed(home)
    test_client, _ = client
    body = test_client.get("/v1/analytics/realtime").json()
    assert body["status"] == "active" and isinstance(body["generated_at"], int)
    assert [s["state"] for s in body["sessions"]] == ["failing", "just_finished"]
    item = body["sessions"][0]
    assert item["project"] == "demo" and item["agent"] == "claude_code"
    assert len(item["density"]) == 10 and "lanes" not in item
    assert item["failure"] == {"n": 3, "command_head": "npm install",
                               "error_class_share": {"timeout": 1.0}, "cause_hint": "超时"}
    assert item["approval"] is None and item["outcome"] is None
    assert body["today"]["sessions_started"] >= 0
    lanes = test_client.get("/v1/analytics/realtime", params={"lanes": 1}).json()
    assert set(lanes["sessions"][0]["lanes"]) == {"human", "tool", "error"}
    assert len(lanes["sessions"][0]["lanes"]["error"]) == 3

    missing = test_client.post("/v1/analytics/realtime/nope/dismiss", json={"seconds": 600})
    assert missing.status_code == 404
    bad = test_client.post("/v1/analytics/realtime/live/dismiss", json={"seconds": 5})
    assert bad.status_code == 422
    ok = test_client.post("/v1/analytics/realtime/live/dismiss").json()
    assert ok["session_uid"] == "live" and ok["until"] > body["generated_at"]
    after = test_client.get("/v1/analytics/realtime").json()["sessions"][0]
    assert after["state"] == "failing" and "failing" not in after["flags"]


def test_stream_first_frame(client, home):
    seed(home)
    _, gateway = client
    calls = 0

    async def disconnected():
        nonlocal calls
        calls += 1
        return calls > 1

    async def collect():
        return [chunk async for chunk in stream(gateway.realtime, disconnected, poll_s=0.01)]

    chunks = asyncio.run(collect())
    text = chunks[0].decode()
    assert text.startswith("retry: 2000\n\nevent: realtime\ndata: ")
    snapshot = json.loads(text.split("data: ", 1)[1])
    assert snapshot["counts"]["failing"] == 1
    assert gateway.realtime.clients == 0


def test_stream_route_headers(client, home):
    seed(home)
    _, gateway = client
    gateway.realtime.stop.set()  # The generator ends after the first frame.
    test_client, _ = client
    with test_client.stream("GET", "/v1/analytics/realtime/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first = next(response.iter_lines())
    assert first == "retry: 2000"
