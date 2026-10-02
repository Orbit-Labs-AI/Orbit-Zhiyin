"""`/v1/uiview/*`: prototype-shaped payloads for A1 overview, A2 persona, Lite and reveal.

The heavy part (``uiview_facts``) runs once per data revision in the analysis worker; every
handler here only filters those rows and re-derives the page (milliseconds), so filters,
brushing and window switches never wait for the analysis engine.

- ``GET /v1/uiview/facts`` — one columnar row per main session (ETag / 304 on data_rev).
- ``GET /v1/uiview/overview`` — A1 / Lite home (tiles, outcome, trend, heat, tools, insight).
- ``GET /v1/uiview/persona`` and ``/persona/reveal`` — A2 / Lite persona and reveal subset.
- ``/v1/uiview/sessions*`` — A3 / Lite list and detail (``uiview.routes_sessions``), overlaid
  with the newest cached fact rows (clock fields stay the request's own timezone).

Freshness follows the analytics snapshots: ``fresh`` / ``stale`` (200) or ``computing``
(202 with ``job_id``).
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from ..uiview import facts, fetch, overview, persona, routes_sessions
from .auth import ApiError
from .routes_analytics import analytics_scope

if TYPE_CHECKING:
    from .gateway import Gateway

RANGES = (7, 30, 90, 0)


def facts_scope(display_timezone: str = "UTC",
                excluded_session_uids: Annotated[list[str] | None, Query()] = None):
    return analytics_scope(display_timezone=display_timezone,
                           excluded_session_uids=excluded_session_uids)


def _agents(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None
    return [a for a in (part.strip() for part in value.split(",")) if a]


def _today(value: str | None, tz: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ApiError(422, "invalid_request", f"Invalid today: {value}") from error
    return overview.today_in(tz)


def router(gw: Gateway) -> APIRouter:
    from dataclasses import asdict

    api = APIRouter()
    scope_dependency = Depends(facts_scope)

    def load(scope, wait_ms: int):
        body, freshness, job_id = fetch.fetch(gw, asdict(scope), wait_ms=wait_ms)
        if body is None:
            if freshness == "none":
                return None, {"freshness": "none", "job_id": None}
            return None, JSONResponse({"meta": {"freshness": "computing", "job_id": job_id}},
                                      status_code=202)
        realtime = getattr(gw, "realtime", None)
        latest = realtime.latest() if realtime is not None else None
        body = facts.overlay_live(body, latest)
        body["meta"] = {**body.get("meta", {}), "freshness": freshness, "job_id": job_id}
        return body, None

    def empty(meta: dict) -> dict:
        return {"meta": {**meta, "contract": facts.CONTRACT}, "rows": [], "aux": {},
                "agents": [], "projects": []}

    @api.get("/v1/uiview/facts")
    def get_facts(request: Request, scope=scope_dependency,
                  wait_ms: int = Query(0, ge=0, le=3000)):
        body, early = load(scope, wait_ms)
        if isinstance(early, Response):
            return early
        if body is None:
            return facts.compact(empty(early))
        tag = f'"{body["meta"].get("data_rev")}:{body["meta"].get("scope_hash")}"'
        if request.headers.get("if-none-match") == tag and body["meta"]["freshness"] == "fresh":
            return Response(status_code=304, headers={"ETag": tag})
        headers = {"ETag": tag} if body["meta"]["freshness"] == "fresh" else {}
        raw = json.dumps(facts.compact(body), ensure_ascii=False, separators=(",", ":"),
                         default=str).encode()
        if "gzip" in (request.headers.get("accept-encoding") or "") and len(raw) > 1024:
            headers.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
            raw = gzip.compress(raw, 5)
        return Response(raw, media_type="application/json", headers=headers)

    @api.get("/v1/uiview/overview")
    def get_overview(scope=scope_dependency, range_: int = Query(30, alias="range"),
                     agents: str | None = None, project: str | None = None,
                     topic: str | None = None, outcome: str | None = None,
                     fric: str | None = None, hour: int | None = Query(None, ge=0, le=23),
                     compare: int = Query(0, ge=0, le=1),
                     metric: Literal["n", "h", "tok"] = "n",
                     from_ts: int | None = None, until_ts: int | None = None,
                     edition: Literal["advance", "lite"] = "advance",
                     today: str | None = None, wait_ms: int = Query(0, ge=0, le=3000)):
        if range_ not in RANGES:
            raise ApiError(422, "invalid_request", f"range must be one of {RANGES}")
        if from_ts is not None and until_ts is not None and until_ts <= from_ts:
            raise ApiError(422, "invalid_request", "until_ts must be after from_ts")
        body, early = load(scope, wait_ms)
        if isinstance(early, Response):
            return early
        body = body or empty(early)
        day = _today(today, scope.display_timezone)
        params = {"range": range_, "agents": _agents(agents), "project": project or None,
                  "topic": topic or None, "outcome": outcome or None, "fric": fric or None,
                  "hour": hour, "compare": bool(compare), "metric": metric,
                  "from_ts": from_ts, "until_ts": until_ts, "edition": edition}
        payload = overview.build(body, params, day)
        payload["meta"].update({k: body["meta"].get(k) for k in
                                ("freshness", "job_id", "data_rev", "scope_hash")})
        return payload

    def persona_params(period: str, agents: str | None, project: str | None,
                       vs: str | None) -> dict:
        return {"period": period, "agents": _agents(agents), "project": project or None,
                "vs": vs}

    def persona_call(fn, scope, params: dict, today: str | None, wait_ms: int):
        body, early = load(scope, wait_ms)
        if isinstance(early, Response):
            return early
        body = body or empty(early)
        try:
            payload = fn(body, params, _today(today, scope.display_timezone))
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from error
        payload["meta"].update({k: body["meta"].get(k) for k in
                                ("freshness", "job_id", "data_rev", "scope_hash")})
        return payload

    @api.get("/v1/uiview/persona")
    def get_persona(scope=scope_dependency, period: str = "90", agents: str | None = None,
                    project: str | None = None, vs: Literal["past"] | None = None,
                    today: str | None = None, wait_ms: int = Query(0, ge=0, le=3000)):
        return persona_call(persona.page, scope, persona_params(period, agents, project, vs),
                            today, wait_ms)

    @api.get("/v1/uiview/persona/reveal")
    def get_reveal(scope=scope_dependency, period: str = "90", agents: str | None = None,
                   project: str | None = None, today: str | None = None,
                   wait_ms: int = Query(0, ge=0, le=3000)):
        return persona_call(persona.reveal, scope, persona_params(period, agents, project, None),
                            today, wait_ms)

    def fact_overlay() -> dict | None:
        rows = fetch.latest_rows(gw)
        clock = ("d", "h", "mi", "live", "excluded")
        return {uid: {k: v for k, v in r.items() if k not in clock}
                for uid, r in rows.items()} if rows else None

    api.include_router(routes_sessions.router(gw, facts_provider=fact_overlay))
    return api
