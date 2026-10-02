"""`/v1/analytics/realtime` routes (AN-13): live snapshot, SSE stream and card dismissal."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import StreamingResponse

from ..realtime.service import Realtime, content_hash
from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway

POLL_S = 1.0
KEEPALIVE_S = 15.0


def frame(snapshot: dict) -> bytes:
    data = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: realtime\ndata: {data}\n\n".encode()


async def stream(rt: Realtime, disconnected: Callable[[], Awaitable[bool]], lanes: bool = False,
                 poll_s: float = POLL_S, keepalive_s: float = KEEPALIVE_S) -> AsyncIterator[bytes]:
    """Full snapshot first, then a frame only when the content hash changes."""
    rt.attach()
    try:
        snap = await asyncio.to_thread(rt.snapshot, None, lanes)
        last_hash, last_sent = content_hash(snap), time.monotonic()
        yield b"retry: 2000\n\n" + frame(snap)
        while not rt.stopping():
            await asyncio.sleep(poll_s)
            if await disconnected():
                break
            latest = rt.latest()
            if latest is not None:
                snap = latest if lanes else rt.strip(latest)
                digest = content_hash(snap)
                if digest != last_hash:
                    last_hash, last_sent = digest, time.monotonic()
                    yield frame(snap)
                    continue
            if time.monotonic() - last_sent >= keepalive_s:
                last_sent = time.monotonic()
                yield b": keepalive\n\n"
    finally:
        rt.detach()


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    rt = getattr(gw, "realtime", None) or Realtime(gw)
    gw.realtime = rt

    @api.get("/v1/analytics/realtime")
    def snapshot(lanes: int = Query(0, ge=0, le=1)):
        return rt.snapshot(lanes=bool(lanes))

    @api.get("/v1/analytics/realtime/stream")
    async def realtime_stream(request: Request, lanes: int = Query(0, ge=0, le=1)):
        return StreamingResponse(stream(rt, request.is_disconnected, bool(lanes)),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @api.get("/v1/analytics/realtime/approvals")
    def approvals(since: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        return rt.approvals(since, limit)

    @api.post("/v1/analytics/realtime/{session_uid}/dismiss")
    def dismiss(session_uid: str, body: Annotated[dict | None, Body()] = None):
        seconds = (body or {}).get("seconds", 3600)
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 60 <= seconds <= 86_400:
            raise ApiError(422, "invalid_request", "seconds 必须是 60 到 86400 之间的整数")
        return rt.dismiss(session_uid, seconds)

    return api
