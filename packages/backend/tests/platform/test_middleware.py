from __future__ import annotations

import asyncio
import statistics
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from tandem_backend import platform as pf
from tandem_backend.platform import logs
from tandem_backend.platform.middleware import PlatformMiddleware, route_template


def make_app(platform):
    app = FastAPI()
    calls = {"n": 0}

    @app.get("/v1/sessions")
    def sessions(q: str = ""):
        calls["n"] += 1
        return {"items": [1, 2, 3]}

    @app.get("/v1/sessions/{sid}/events")
    def events(sid: str):
        calls["n"] += 1
        return {"sid": sid}

    @app.get("/v1/stream")
    def stream():
        return StreamingResponse(iter([b"data: 1\n\n"]), media_type="text/event-stream")

    @app.get("/v1/plain")
    def plain():
        return {"ok": True}

    app.add_middleware(PlatformMiddleware, platform=platform)
    return app, calls


def enable(platform):
    platform.settings.put_telemetry({"enabled": True})
    platform.refresh()


def test_headers_etag_and_304(started):
    started.gw.revisions.update(data_rev=3, inventory_rev=1)
    app, calls = make_app(started)
    client = TestClient(app)
    first = client.get("/v1/sessions", params={"q": "a"})
    assert first.status_code == 200
    assert first.headers["server-timing"].startswith("app;dur=")
    assert first.headers["x-request-id"].startswith(started.revisions.boot)
    tag = first.headers["etag"]
    assert tag.startswith(f'W/"{started.revisions.boot}-3.1-')
    assert first.headers["cache-control"] == "private, no-cache"
    again = client.get("/v1/sessions", params={"q": "a"}, headers={"If-None-Match": tag})
    assert again.status_code == 304 and calls["n"] == 1
    assert again.headers["etag"] == tag
    # Different query → different tag; nested path follows the same rule.
    other = client.get("/v1/sessions", params={"q": "b"}, headers={"If-None-Match": tag})
    assert other.status_code == 200 and other.headers["etag"] != tag
    nested = client.get("/v1/sessions/abc/events")
    assert "etag" in nested.headers
    # A new revision invalidates.
    started.gw.revisions.update(data_rev=4)
    fresh = client.get("/v1/sessions", params={"q": "a"}, headers={"If-None-Match": tag})
    assert fresh.status_code == 200
    assert "etag" not in client.get("/v1/plain").headers


def test_no_etag_without_data(started):
    app, calls = make_app(started)
    response = TestClient(app).get("/v1/sessions", headers={"If-None-Match": "*"})
    assert response.status_code == 200 and "etag" not in response.headers


def test_register_etag_and_bump(started):
    app, calls = make_app(started)
    assert pf.register_etag("/v1/plain", lambda: pf.rev_token("plain"), exact=True)
    client = TestClient(app)
    tag = client.get("/v1/plain").headers["etag"]
    assert client.get("/v1/plain", headers={"If-None-Match": tag}).status_code == 304
    pf.bump_rev("plain")
    assert client.get("/v1/plain", headers={"If-None-Match": tag}).status_code == 200


def test_slow_log_and_metrics(started):
    enable(started)
    started.slow_ms = 0
    app, _ = make_app(started)
    client = TestClient(app)
    client.get("/v1/sessions/123/events", params={"secret": "s3cr3t-query"})
    client.get("/v1/stream")
    for handler in [started.log_handler]:
        handler.flush()
    text = (started.home / "logs" / "tandem.log").read_text()
    assert "slow_request" in text and "/v1/sessions/{sid}/events" in text
    assert "s3cr3t-query" not in text
    series = {(s["name"], s["tags"].get("route")): s
              for s in started.telemetry.query(None, 600, "total")["series"]}
    assert ("http.request", "/v1/sessions/{sid}/events") in series
    assert ("http.request", "/v1/stream") not in series  # SSE is not a latency.
    assert ("http.slow", "/v1/sessions/{sid}/events") in series


def test_route_template_fallback():
    assert route_template({"path": "/legacy/12345/x"}) == "/legacy/{id}/x"
    assert route_template({"path": "/v1/a/0123456789abcdef0123"}) == "/v1/a/{id}"


def test_overhead_microbenchmark(started):
    enable(started)
    started.gw.revisions.update(data_rev=1, inventory_rev=1)

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"{}"})

    wrapped = PlatformMiddleware(inner, started)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(_):
        return None

    scope = {"type": "http", "method": "GET", "path": "/v1/sessions", "query_string": b"",
             "headers": [(b"host", b"127.0.0.1")]}

    async def bench(app, n=2000):
        samples = []
        for _ in range(n):
            t0 = time.perf_counter()
            await app(dict(scope), receive, send)
            samples.append(time.perf_counter() - t0)
        return statistics.median(samples) * 1000

    base = asyncio.run(bench(inner))
    with_mw = asyncio.run(bench(wrapped))
    print(f"middleware overhead: {with_mw - base:.4f} ms (median)")
    assert with_mw - base < 0.5
    logs.log.handlers[0].flush()
