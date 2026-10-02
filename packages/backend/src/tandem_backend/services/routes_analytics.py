"""Snapshot-backed analytics routes (docs/architecture/app-services.md §4.2).

1. scope → scope_hash; revision from memory (no database round trip)
2. If-None-Match equals the current ETag → 304
3. exact snapshot → 200 ``fresh``
4. older revision of the same section/scope → 200 ``stale`` and an interactive recompute
5. miss → enqueue; wait up to ``wait_ms`` (≤ 3000) then 200, else 202 ``computing``;
   no database yet → 200 with ``meta.freshness = "none"``
6. failures map to 404 / 422 / 503 (+ Retry-After); the old snapshot keeps serving

Responses keep the existing section keys and only add a top-level ``meta``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .auth import ApiError
from .sections import SECTIONS, rules_digest
from .snapshots import Snapshot, SnapshotKey, scope_hash

if TYPE_CHECKING:
    from .gateway import Gateway

CONTRACT = "tandem-app-analytics-v1"
PLAIN_SECTIONS = ("overview", "tools", "projects", "text", "tasks", "instruction")
CLIENT_ERRORS = {"not_found": 404, "invalid_request": 422, "analysis_scope_too_large": 422}


def analytics_scope(
    display_timezone: str = "UTC",
    project_ids: Annotated[list[str] | None, Query()] = None,
    legacy_project_ids: Annotated[list[str] | None, Query()] = None,
    model_ids: Annotated[list[str] | None, Query()] = None,
    effort_raw: Annotated[list[str] | None, Query()] = None,
    from_ts: int | None = None, until_ts: int | None = None,
    root_session_uids: Annotated[list[str] | None, Query()] = None,
    excluded_session_uids: Annotated[list[str] | None, Query()] = None,
    include_children: bool = True, scene: str | None = None,
    source_ids: Annotated[list[str] | None, Query()] = None,
):
    """Same parameters as api/routes.py; an explicit empty value (``x=``) means []."""
    from ..analytics.inputs import Scope

    def explicit(values):
        return [] if values == [""] else values

    try:
        return Scope(display_timezone=display_timezone, source_ids=explicit(source_ids),
                     project_ids=explicit(project_ids),
                     legacy_project_ids=explicit(legacy_project_ids),
                     model_ids=explicit(model_ids), effort_raw=effort_raw,
                     from_ts=from_ts, until_ts=until_ts,
                     root_session_uids=explicit(root_session_uids),
                     excluded_session_uids=excluded_session_uids or [],
                     include_children=include_children, scene=scene)
    except ValueError as error:
        raise ApiError(422, "invalid_request", str(error)) from error


def failure_error(error: dict | None) -> ApiError:
    error = error or {}
    code = error.get("code") or "analysis_unavailable"
    message = error.get("message") or "Analysis is unavailable for this scope"
    if code in CLIENT_ERRORS:
        return ApiError(CLIENT_ERRORS[code], code, message)
    if code == "projection_pending":
        return ApiError(503, code, message, retryable=True, retry_after=1)
    return ApiError(503, "analysis_unavailable", f"{code}: {message}", retryable=True,
                    retry_after=5)


class RecomputeRequest(BaseModel):
    sections: list[str] = Field(min_length=1, max_length=len(SECTIONS))
    scope: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    scope_dependency = Depends(analytics_scope)

    def meta(h: str, rules: str, freshness: str, snapshot: Snapshot | None, rev: dict,
             source: str, **extra) -> dict:
        body = snapshot.body if snapshot else {}
        return {"contract": CONTRACT, "scope_hash": h,
                "data_rev": snapshot.key.data_rev if snapshot else rev["data_rev"],
                "inventory_rev": snapshot.key.inventory_rev if snapshot else rev["inventory_rev"],
                "rules_version": rules, "freshness": freshness,
                "computed_at": snapshot.computed_at if snapshot else None, "source": source,
                "duration_ms": snapshot.duration_ms if snapshot else None,
                "coverage": body.get("coverage"), "selection": body.get("selection"), **extra}

    def etag(rules: str, data_rev, inventory_rev, h: str, token: str) -> str:
        return f'W/"{rules}:{data_rev}.{inventory_rev}:{h}:{token}"'

    def render(snapshot: Snapshot, meta_: dict, tag: str, page) -> JSONResponse:
        body = dict(snapshot.body)
        if page is not None:
            offset, limit = page
            rows = body.get("sessions") or []
            body["sessions"] = rows[offset:offset + limit]
            body["total"] = len(rows)
            body["next_offset"] = offset + limit if offset + limit < len(rows) else None
        body["meta"] = meta_
        return JSONResponse(body, headers={"ETag": tag})

    def serve(name: str, scope, params: dict, wait_ms: int, if_none_match: str | None,
              page: tuple[int, int] | None = None):
        section = SECTIONS[name]
        rules = rules_digest()
        scope_dict = asdict(scope)
        h = scope_hash(scope_dict, params)
        rev = gw.revisions.snapshot()
        token = name if page is None else f"{name}[{page[0]}:{page[1]}]"
        if rev["data_rev"] is None:
            return JSONResponse({section.key: None, "meta": meta(
                h, rules, "none", None, rev, "none", reason="no_projection")})
        gw.state.remember_scope(scope_dict)
        current = SnapshotKey(name, h, rev["data_rev"], rev["inventory_rev"], rules)
        tag = etag(rules, rev["data_rev"], rev["inventory_rev"], h, token)
        snapshot = gw.snapshots.get(current)
        if snapshot is not None:
            if if_none_match is not None and tag in [t.strip() for t in if_none_match.split(",")]:
                return Response(status_code=304, headers={"ETag": tag})
            return render(snapshot, meta(h, rules, "fresh", snapshot, rev, "cache"), tag, page)
        analysis = gw.supervisor.analysis
        revision = (rev["data_rev"], rev["inventory_rev"])
        old = gw.snapshots.latest(name, h, rules)
        if old is not None:
            task = analysis.submit(name, scope_dict, params, h, "interactive", revision, rules)
            extra = {"job_id": task.id} if task else {"circuit": "open"}
            old_tag = etag(rules, old.key.data_rev, old.key.inventory_rev, h, token)
            return render(old, meta(h, rules, "stale", old, rev, "cache", **extra), old_tag, page)
        failure = analysis.failure(name, h, revision)
        if failure and (failure["error"].get("code") in CLIENT_ERRORS
                        or analysis.circuit_open(name, h, revision)):
            raise failure_error(failure["error"])
        task = analysis.submit(name, scope_dict, params, h, "interactive", revision, rules)
        if task is None:
            raise failure_error((failure or {}).get("error"))
        if wait_ms:
            task.done.wait(wait_ms / 1000)
            if task.status == "completed":
                snapshot = gw.snapshots.get(current)
                if snapshot is not None:
                    return render(snapshot, meta(h, rules, "fresh", snapshot, rev, "computed"),
                                  tag, page)
            elif task.status == "failed":
                raise failure_error(task.error)
        return JSONResponse({"meta": meta(h, rules, "computing", None, rev, "none",
                                          job_id=task.id, progress=None)}, status_code=202)

    wait = Query(0, ge=0, le=3000)

    def plain_route(name: str):
        def plain(scope=scope_dependency, wait_ms: int = wait,
                  if_none_match: str | None = Header(None)):
            return serve(name, scope, {}, wait_ms, if_none_match)

        return plain

    for name in PLAIN_SECTIONS:
        api.add_api_route(f"/v1/analytics/{name}", plain_route(name), methods=["GET"], name=name)

    @api.get("/v1/analytics/sessions")
    def sessions(scope=scope_dependency, offset: int = Query(0, ge=0),
                 limit: int = Query(50, ge=1, le=200), wait_ms: int = wait,
                 if_none_match: str | None = Header(None)):
        return serve("sessions", scope, {}, wait_ms, if_none_match, page=(offset, limit))

    @api.get("/v1/analytics/sessions/{session_id}")
    def session(session_id: str, scope=scope_dependency, wait_ms: int = wait,
                if_none_match: str | None = Header(None)):
        return serve("session", scope, {"session_id": session_id}, wait_ms, if_none_match)

    @api.get("/v1/analytics/preferences")
    def preferences(scope=scope_dependency, task_id: str | None = None, wait_ms: int = wait,
                    if_none_match: str | None = Header(None)):
        params = {"task_id": task_id} if task_id is not None else {}
        return serve("preferences", scope, params, wait_ms, if_none_match)

    @api.post("/v1/analytics/recompute", status_code=202)
    def recompute(request: RecomputeRequest):
        unknown = [s for s in request.sections if s not in SECTIONS]
        if unknown:
            raise ApiError(422, "invalid_request", f"Unknown sections: {unknown}")
        allowed = set(analytics_scope.__code__.co_varnames[:analytics_scope.__code__.co_argcount])
        if set(request.scope) - allowed:
            raise ApiError(422, "invalid_request", f"Unknown scope keys: "
                           f"{sorted(set(request.scope) - allowed)}")
        scope = analytics_scope(**request.scope)
        rev = gw.revisions.snapshot()
        if rev["data_rev"] is None:
            raise ApiError(409, "no_projection", "No published data to analyse", retryable=True)
        rules = rules_digest()
        scope_dict = asdict(scope)
        jobs = []
        for name in request.sections:
            h = scope_hash(scope_dict, request.params)
            gw.supervisor.analysis.clear_failures(name, h)  # Manual recompute resets the circuit.
            task = gw.supervisor.analysis.submit(name, scope_dict, request.params, h,
                                                 "interactive",
                                                 (rev["data_rev"], rev["inventory_rev"]), rules)
            jobs.append({"section": name, "scope_hash": h, "job_id": task.id if task else None})
        return {"jobs": jobs, "data_rev": rev["data_rev"]}

    return api
