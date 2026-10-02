"""One pure-ASGI layer for timing, request ids, conditional GETs and request telemetry.

Pure ASGI so SSE is never buffered. A matching ``If-None-Match`` short-circuits to 304
before routing (no DB read, no JSON encoding). Only route templates and status classes
are recorded — never query strings or bodies.
"""

from __future__ import annotations

import itertools
import re
import time
import zlib

from . import logs, telemetry

_ID = re.compile(r"^(\d+|[0-9a-fA-F]{12,}|[0-9a-fA-F-]{32,36})$")


def route_template(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    parts = [p for p in scope.get("path", "/").split("/") if p][:3]
    return "/" + "/".join("{id}" if _ID.match(p) else p for p in parts)


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class PlatformMiddleware:
    def __init__(self, app, platform):
        self.app = app
        self.platform = platform
        self.counter = itertools.count(1)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        t0 = time.perf_counter()
        p = self.platform
        boot = p.revisions.boot
        request_id = f"{boot}-{next(self.counter):x}"
        method = scope["method"]
        tag = None
        if method in ("GET", "HEAD"):
            fn = p.etag_rules.match(scope["path"])
            if fn is not None:
                try:
                    rev = fn()
                except Exception:  # noqa: BLE001 - a failing rule only disables caching.
                    rev = None
                if rev is not None:
                    target = scope["path"].encode() + b"?" + scope.get("query_string", b"")
                    tag = f'W/"{boot}-{rev}-{zlib.crc32(target):x}"'
                    supplied = _header(scope, b"if-none-match")
                    if supplied and (supplied.strip() == "*" or tag in (
                            t.strip() for t in supplied.split(","))):
                        await self._not_modified(send, tag, request_id, t0)
                        return

        state = {"status": 0, "sse": False, "done": False}

        async def wrapped(message):
            kind = message["type"]
            if kind == "http.response.start":
                status = message["status"]
                state["status"] = status
                headers = list(message.get("headers", ()))
                names = set()
                for key, value in headers:
                    lower = key.lower()
                    names.add(lower)
                    if lower == b"content-type" and value.startswith(b"text/event-stream"):
                        state["sse"] = True
                ms = (time.perf_counter() - t0) * 1000
                headers.append((b"server-timing", f"app;dur={ms:.1f}".encode()))
                headers.append((b"x-request-id", request_id.encode()))
                if tag is not None and status == 200 and b"etag" not in names:
                    headers.append((b"etag", tag.encode()))
                    if b"cache-control" not in names:
                        headers.append((b"cache-control", b"private, no-cache"))
                message = {**message, "headers": headers}
            elif kind == "http.response.body" and not message.get("more_body", False):
                if not state["done"]:
                    state["done"] = True
                    self._finish(scope, method, state, t0, request_id)
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        except Exception as error:
            telemetry.record("error", 1, area="http", code=type(error).__name__)
            raise

    async def _not_modified(self, send, tag: str, request_id: str, t0: float) -> None:
        ms = (time.perf_counter() - t0) * 1000
        await send({"type": "http.response.start", "status": 304, "headers": [
            (b"etag", tag.encode()), (b"cache-control", b"private, no-cache"),
            (b"server-timing", f"app;dur={ms:.1f}".encode()),
            (b"x-request-id", request_id.encode())]})
        await send({"type": "http.response.body", "body": b""})
        telemetry.record("etag.hit")

    def _finish(self, scope, method: str, state: dict, t0: float, request_id: str) -> None:
        if state["sse"]:
            return  # Streams live for minutes; their duration is not a latency.
        try:
            ms = (time.perf_counter() - t0) * 1000
            status = state["status"]
            route = route_template(scope)
            telemetry.record("http.request", ms, route=route, method=method,
                             status=f"{status // 100}xx")
            p = self.platform
            if ms > p.slow_ms and p.slow_log:
                telemetry.record("http.slow", 1, route=route)
                logs.log_event("slow_request", route=route, method=method, status=status,
                               ms=round(ms, 1), req=request_id)
        except Exception:  # noqa: BLE001 - observability never fails a request.
            pass
