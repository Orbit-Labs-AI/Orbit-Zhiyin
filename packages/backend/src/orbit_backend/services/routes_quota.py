"""Usage & quota endpoints (DT-17 / RC-14 / FE-22), read-only over orbit.db.

GET /v1/quota          per-agent quota windows (Codex observed, Claude Code estimated)
GET /v1/quota/advice   cross-agent allocation advice; ``insufficient`` when data is missing
GET /v1/usage          tokens / cost / cache grouped by agent, model or day + quota_window
Excluded sessions (AN-16.1) are left out everywhere.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Query

from .. import quota
from ..sessionops import exclusion

if TYPE_CHECKING:
    from .gateway import Gateway


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()

    def now_ms() -> int:
        return int(time.time() * 1000)

    @api.get("/v1/quota")
    def get_quota():
        with gw.reads.read() as db:
            return quota.snapshot(db, now_ms(), exclusion.merged(None))

    @api.get("/v1/quota/advice")
    def get_advice():
        now, excluded = now_ms(), exclusion.merged(None)
        with gw.reads.read() as db:
            snap = quota.snapshot(db, now, excluded)
            mix = quota.model_mix(db, now, excluded)
        return quota.advise(snap, mix)

    @api.get("/v1/usage")
    def get_usage(group_by: Literal["agent", "model", "day"] = "day",
                  days: Annotated[int, Query(ge=1, le=366)] = 30,
                  tz_offset_min: Annotated[int, Query(ge=-840, le=840)] = 0):
        now, excluded = now_ms(), exclusion.merged(None)
        with gw.reads.read() as db:
            payload = quota.usage(db, group_by=group_by, now_ms=now, days=days,
                                  tz_offset_min=tz_offset_min, excluded=excluded)
            payload["quota_window"] = quota.snapshot(db, now, excluded)["quota_window"]
        return payload

    return api
