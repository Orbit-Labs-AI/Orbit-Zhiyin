"""Snapshot-backed analytics routes (docs/architecture/app-services.md §4.2).

1. scope → scope_hash; revision from memory (no database round trip)
2. If-None-Match equals the current ETag → 304
3. exact snapshot → 200 ``fresh``
4. older revision of the same section/scope → 200 ``stale`` and an interactive recompute
5. miss → enqueue; wait up to ``wait_ms`` (≤ 3000) then 200, else 202 ``computing``;
   no database yet → 200 with ``meta.freshness = "none"``
6. failures map to 404 / 422 / 503 (+ Retry-After); the old snapshot keeps serving

Every route accepts ``days`` (7 / 30 / 90 / 0 = all time) as shorthand for ``from_ts`` at a
UTC day boundary. ``/v1/analytics/overview`` without ``days``, ``from_ts`` or ``until_ts``
uses the first-open fast path (``services.fastpath``): the widest ready window, else the
last 7 days now and wider windows in the background; ``meta.window`` reports both.

Responses keep the existing section keys and only add a top-level ``meta``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..recommend.contracts import Family
from .auth import ApiError
from .sections import SECTIONS, rules_digest
from .snapshots import Snapshot, SnapshotKey, scope_hash

if TYPE_CHECKING:
    from .gateway import Gateway

CONTRACT = "tandem-app-analytics-v1"
PLAIN_SECTIONS = ("overview", "tools", "projects", "text", "tasks", "instruction", "statistics",
                  "lexical", "bottleneck")
PAGED_ROWS = {"products": "sessions"}  # Sections whose paged list is not their section key.
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
    days: int | None = None,
    agent_ids: Annotated[list[str] | None, Query()] = None,
):
    """Same parameters as api/routes.py; an explicit empty value (``x=``) means [].
    ``days`` (7 / 30 / 90 / 0) sets ``from_ts`` to that window's first UTC day."""
    from ..analytics.inputs import Scope
    from ..appdata.sources_scope import default_source_ids
    from ..sessionops.exclusion import merged

    def explicit(values):
        return [] if values == [""] else values

    if days is not None:
        from . import fastpath

        fastpath.check_days(days)
        if from_ts is not None or until_ts is not None:
            raise ApiError(422, "invalid_request", "days cannot be combined with from_ts/until_ts")
        from_ts = fastpath.window_start(days)
    try:
        return Scope(display_timezone=display_timezone,
                     source_ids=default_source_ids(explicit(source_ids)),
                     project_ids=explicit(project_ids),
                     legacy_project_ids=explicit(legacy_project_ids),
                     model_ids=explicit(model_ids), effort_raw=effort_raw,
                     from_ts=from_ts, until_ts=until_ts,
                     root_session_uids=explicit(root_session_uids),
                     excluded_session_uids=merged(excluded_session_uids),
                     include_children=include_children, scene=scene,
                     agent_ids=explicit(agent_ids))
    except ValueError as error:
        raise ApiError(422, "invalid_request", str(error)) from error


def failure_error(error: dict | None) -> ApiError:
    error = error or {}
    code = error.get("code") or "analysis_unavailable"
    message = error.get("message") or "Analysis is unavailable for this scope"
    if code in CLIENT_ERRORS:
        return ApiError(CLIENT_ERRORS[code], code, message)
    if code == "projection_pending":
        # The supervisor waits ``transient_retry_s`` before re-running the same key; asking
        # again every second only re-read this failure (and used to re-run the analysis).
        return ApiError(503, code, message, retryable=True,
                        retry_after=max(1, round(error.get("retry_after") or 1)))
    return ApiError(503, "analysis_unavailable", f"{code}: {message}", retryable=True,
                    retry_after=5)


class RecommendationBody(BaseModel):
    context: dict = Field(default_factory=dict)
    family: Family | None = None
    limit: int = Field(default=6, ge=1, le=20, strict=True)


class ComparisonBody(BaseModel):
    first: dict = Field(default_factory=dict)
    second: dict = Field(default_factory=dict)


SCOPE_PARAMS = frozenset(analytics_scope.__code__.co_varnames[:analytics_scope.__code__.co_argcount])
ROUTE_PARAMS = frozenset({"wait_ms", "offset", "limit", "task_id"})
# Filters callers have tried that snapshot sections cannot apply; named so the 422 says why.
UNSUPPORTED_FILTERS = frozenset({"weekday", "hour", "query", "q", "agent"})


def _declared(request: Request) -> set[str]:
    """Query parameters the matched route itself declares (e.g. ``first``/``second``)."""
    route = request.scope.get("route")
    names: set[str] = set()
    pending = [route.dependant] if route is not None and hasattr(route, "dependant") else []
    while pending:
        dependant = pending.pop()
        names.update(param.alias for param in dependant.query_params)
        pending.extend(dependant.dependencies)
    return names


def reject_unknown_params(request: Request) -> None:
    """A filter the snapshot cannot apply must fail, not silently return the unfiltered scope."""
    unknown = sorted(set(request.query_params) - SCOPE_PARAMS - ROUTE_PARAMS - _declared(request))
    if not unknown:
        return
    unsupported = [k for k in unknown if k in UNSUPPORTED_FILTERS]
    hint = (f"; unsupported filters {unsupported} (use agent_ids, from_ts/until_ts, or "
            f"/v1/search for text)") if unsupported else ""
    raise ApiError(422, "invalid_request", f"Unknown query parameters: {unknown}{hint}")


class RecomputeRequest(BaseModel):
    sections: list[str] = Field(min_length=1, max_length=len(SECTIONS))
    scope: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)


def router(gw: Gateway) -> APIRouter:
    api = APIRouter(dependencies=[Depends(reject_unknown_params)])
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

    def render(snapshot: Snapshot, meta_: dict, tag: str, page, view=None) -> Response:
        body = dict(snapshot.body)
        if view is not None:
            try:
                body = view[1](body)
            except ValueError as error:
                raise ApiError(422, "invalid_request", str(error)) from error
            if isinstance(body, Response):
                return body
        if page is not None:
            offset, limit = page
            key = PAGED_ROWS.get(snapshot.key.section) or SECTIONS[snapshot.key.section].key
            rows = body.get(key) or []
            body[key] = rows[offset:offset + limit]
            body["total"] = len(rows)
            body["next_offset"] = offset + limit if offset + limit < len(rows) else None
        body["meta"] = meta_
        return JSONResponse(body, headers={"ETag": tag})

    def serve(name: str, scope, params: dict, wait_ms: int, if_none_match: str | None,
              page: tuple[int, int] | None = None, view=None,
              window: dict | None = None):
        """``view`` = (etag token, body → body): a cheap gateway-side projection of the
        worker's snapshot (search page, two-session compare, catalog match)."""
        section = SECTIONS[name]

        def meta_(*args, **extra):  # adds the fast-path window to every meta
            return meta(*args, **extra, **({"window": window} if window is not None else {}))
        rules = rules_digest()
        scope_dict = asdict(scope)
        h = scope_hash(scope_dict, params)
        rev = gw.revisions.snapshot()
        token = name if page is None else f"{name}[{page[0]}:{page[1]}]"
        if view is not None:
            token = f"{token}{view[0]}"
        if rev["data_rev"] is None:
            return JSONResponse({section.key: None, "meta": meta_(
                h, rules, "none", None, rev, "none", reason="no_projection")})
        gw.state.remember_scope(scope_dict)
        current = SnapshotKey(name, h, rev["data_rev"], rev["inventory_rev"], rules)
        tag = etag(rules, rev["data_rev"], rev["inventory_rev"], h, token)
        snapshot = gw.snapshots.get(current)
        if snapshot is not None:
            if if_none_match is not None and tag in [t.strip() for t in if_none_match.split(",")]:
                return Response(status_code=304, headers={"ETag": tag})
            return render(snapshot, meta_(h, rules, "fresh", snapshot, rev, "cache"), tag, page,
                          view)
        analysis = gw.supervisor.analysis
        revision = (rev["data_rev"], rev["inventory_rev"])
        old = gw.snapshots.latest(name, h, rules)
        if old is not None:
            task = analysis.submit(name, scope_dict, params, h, "interactive", revision, rules)
            extra = {"job_id": task.id} if task else {"circuit": "open"}
            old_tag = etag(rules, old.key.data_rev, old.key.inventory_rev, h, token)
            return render(old, meta_(h, rules, "stale", old, rev, "cache", **extra), old_tag, page,
                          view)
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
                    return render(snapshot, meta_(h, rules, "fresh", snapshot, rev, "computed"),
                                  tag, page, view)
            elif task.status == "failed":
                raise failure_error(task.error)
        return JSONResponse({"meta": meta_(h, rules, "computing", None, rev, "none",
                                          job_id=task.id, progress=analysis.progress(task))},
                            status_code=202)

    wait = Query(0, ge=0, le=3000)

    def plain_route(name: str):
        def plain(scope=scope_dependency, wait_ms: int = wait,
                  if_none_match: str | None = Header(None)):
            return serve(name, scope, {}, wait_ms, if_none_match)

        def windowed(scope=scope_dependency, wait_ms: int = wait,
                     if_none_match: str | None = Header(None), days: int | None = None):
            from ..analytics.inputs import Scope
            from . import fastpath

            if days is not None or scope.from_ts is not None or scope.until_ts is not None:
                return serve(name, scope, {}, wait_ms, if_none_match)
            base = asdict(scope)
            chosen, window = fastpath.choose(gw, name, base, None)
            response = serve(name, Scope(**chosen), {}, wait_ms, if_none_match, window=window)
            fastpath.follow_up(gw, name, base, window)
            return response

        return windowed if name == "overview" else plain

    for name in PLAIN_SECTIONS:
        api.add_api_route(f"/v1/analytics/{name}", plain_route(name), methods=["GET"], name=name)

    @api.get("/v1/analytics/sessions")
    def sessions(scope=scope_dependency, offset: int = Query(0, ge=0),
                 limit: int = Query(50, ge=1, le=200), wait_ms: int = wait,
                 if_none_match: str | None = Header(None)):
        return serve("sessions", scope, {}, wait_ms, if_none_match, page=(offset, limit))

    @api.get("/v1/analytics/sample_files")
    def sample_files(scope=scope_dependency, offset: int = Query(0, ge=0),
                     limit: int = Query(200, ge=1, le=1000), wait_ms: int = wait,
                     if_none_match: str | None = Header(None)):
        return serve("sample_files", scope, {}, wait_ms, if_none_match, page=(offset, limit))

    @api.get("/v1/analytics/sessions/{session_id}")
    def session(session_id: str, scope=scope_dependency, wait_ms: int = wait,
                if_none_match: str | None = Header(None)):
        return serve("session", scope, {"session_id": session_id}, wait_ms, if_none_match)

    @api.get("/v1/analytics/preferences")
    def preferences(scope=scope_dependency, task_id: str | None = None, wait_ms: int = wait,
                    if_none_match: str | None = Header(None)):
        params = {"task_id": task_id} if task_id is not None else {}
        return serve("preferences", scope, params, wait_ms, if_none_match)

    @api.get("/v1/analytics/work-graph")
    def work_graph(scope=scope_dependency, wait_ms: int = wait,
                   if_none_match: str | None = Header(None)):
        return serve("work_graph", scope, {}, wait_ms, if_none_match)

    @api.get("/v1/analytics/tasks/{task_uid}/trajectory")
    def task_trajectory(task_uid: str, scope=scope_dependency, wait_ms: int = wait,
                        if_none_match: str | None = Header(None)):
        from hashlib import sha256

        from ..analytics.work_graph import task_subgraph

        def view(body: dict) -> dict:
            graph = body.pop("work_graph")
            trajectory = next((t for t in graph["task_trajectories"] if t["task_uid"] == task_uid), None)
            if trajectory is None:
                raise ApiError(404, "not_found", "任务不在本次分析范围内")
            return {**body, "trajectory": trajectory, **task_subgraph(graph, trajectory)}

        tag = f"/trajectory?{sha256(task_uid.encode()).hexdigest()[:12]}"
        return serve("work_graph", scope, {}, wait_ms, if_none_match, view=(tag, view))

    @api.post("/v1/analytics/warmup")
    def warmup():
        """Queue the first-screen prewarm (7 days → 30 days → all time) on the analysis
        worker. Overrides the create_app() route, which warmed inside the gateway process."""
        rev = gw.revisions.snapshot()
        if rev["data_rev"] is None:
            raise ApiError(409, "no_projection", "No published data to analyse", retryable=True)
        queued = gw.prewarm()
        return {"status": "queued" if queued else "ready", "queued": len(queued),
                "job_ids": queued, "data_rev": rev["data_rev"]}

    @api.get("/v1/analytics/products")
    def products(scope=scope_dependency, bucket: Literal["day", "week", "month"] = "day",
                 with_text: bool = False, compare_previous: bool = False,
                 offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                 wait_ms: int = wait, if_none_match: str | None = Header(None)):
        """Worker-computed products; ``sessions`` is paged like /v1/analytics/sessions."""
        if compare_previous and (scope.from_ts is None or scope.until_ts is None):
            raise ApiError(422, "invalid_request", "上期比较需要明确的 from_ts 和 until_ts")
        params = {"bucket": bucket, "with_text": with_text, "compare_previous": compare_previous}
        return serve("products", scope, params, wait_ms, if_none_match, page=(offset, limit))

    def drop_none(**values) -> dict:
        return {k: v for k, v in values.items() if v is not None}

    def product_params() -> dict:  # Same params as /v1/analytics/products defaults: one cache.
        return {"bucket": "day", "with_text": False, "compare_previous": False}

    @api.get("/v1/analytics/products/sessions")
    def product_sessions(scope=scope_dependency, query: str = "", offset: int = Query(0, ge=0),
                         limit: int = Query(50, ge=1, le=200), wait_ms: int = wait,
                         if_none_match: str | None = Header(None)):
        from hashlib import sha256

        from ..analytics.products import session_page

        def view(body: dict) -> dict:
            return {"scope": body.get("scope"), "analysis_digest": body.get("analysis_digest"),
                    **session_page(body, query=query, offset=offset, limit=limit)}

        tag = f"/sessions?{sha256(query.encode()).hexdigest()[:8]}:{offset}:{limit}"
        return serve("products", scope, product_params(), wait_ms, if_none_match,
                     view=(tag, view))

    @api.get("/v1/analytics/products/compare")
    def product_compare(first: str, second: str, scope=scope_dependency, wait_ms: int = wait,
                        if_none_match: str | None = Header(None)):
        from hashlib import sha256

        from ..analytics.products.summaries import compare_sessions

        tag = f"/compare?{sha256(f'{first}|{second}'.encode()).hexdigest()[:12]}"
        return serve("products", scope, product_params(), wait_ms, if_none_match,
                     view=(tag, lambda body: compare_sessions(body, first, second)))

    @api.post("/v1/analytics/compare")
    def scope_comparison(request: ComparisonBody, wait_ms: int = wait):
        from ..analytics.inputs import Scope

        try:
            first, second = Scope(**request.first), Scope(**request.second)
        except (TypeError, ValueError) as error:
            raise ApiError(422, "invalid_request", str(error)) from error
        return serve("comparison", Scope(), {"first": asdict(first), "second": asdict(second)},
                     wait_ms, None)

    @api.get("/v1/catalog/match-analysis")
    def match_analysis(project_id: str | None = None, model: str | None = None,
                       scene: str | None = None, limit: int = Query(10, ge=1, le=100),
                       wait_ms: int = wait, if_none_match: str | None = Header(None)):
        """Bottleneck → catalog requests come from the worker; matching stays in the gateway."""
        from ..analytics.inputs import Scope

        def view(body: dict) -> dict:
            from tandem_catalog import get_service
            from tandem_catalog.contracts import MatchRequest

            service = get_service(gw.home / "catalog.db")
            return {"contract": "catalog-analysis-match-v1",
                    "batches": [service.match(MatchRequest.model_validate(r))
                                for r in body.get("requests") or []]}

        params = drop_none(project_id=project_id, model=model, scene=scene, limit=limit)
        return serve("catalog_requests", Scope(), params, wait_ms, if_none_match,
                     view=("/match", view))

    @api.get("/v1/analytics/presentation")
    def presentation(scope=scope_dependency, window: str | None = None,
                     target_agent: Literal["generic", "codex", "claude_code"] = "generic",
                     family: Family | None = None, wait_ms: int = wait,
                     if_none_match: str | None = Header(None)):
        from ..analytics.presentation.metrics import window_scope

        try:
            window_scope(scope, window)  # Reject invalid windows before queueing work.
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from error
        params = {"window": window, "target_agent": target_agent, "family": family}
        return serve("presentation", scope, params, wait_ms, if_none_match)

    @api.get("/v1/analytics/recommendations")
    def recommendations(scope=scope_dependency,
                        target_agent: Literal["generic", "codex", "claude_code"] = "generic",
                        kind: Literal["skill", "agent", "hook", "prompt"] | None = None,
                        limit: int = Query(6, ge=1, le=20), family: Family | None = None,
                        wait_ms: int = wait, if_none_match: str | None = Header(None)):
        params = drop_none(context={"agent": target_agent}, kind=kind, limit=limit, family=family)
        return serve("recommendations", scope, params, wait_ms, if_none_match)

    @api.post("/v1/analytics/recommendations")
    def contextual_recommendations(request: RecommendationBody, scope=scope_dependency,
                                   wait_ms: int = wait):
        from ..recommend.contracts import RecommendationContext

        try:
            context = RecommendationContext.model_validate(request.context)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from error
        params = drop_none(context=context.model_dump(mode="json"), family=request.family,
                           limit=request.limit)
        return serve("recommendations", scope, params, wait_ms, None)

    @api.get("/v1/analysis")
    def analysis(project_id: str | None = None, model: str | None = None,
                 before: str | None = None, audience: str = "user", scene: str = "auto",
                 wait_ms: int = wait, if_none_match: str | None = Header(None)):
        from ..analytics.inputs import Scope

        params = drop_none(project_id=project_id, model=model, before=before,
                           audience=audience, scene=scene)
        return serve("analysis", Scope(), params, wait_ms, if_none_match)

    @api.get("/v1/analytics/jobs/{job_id}")
    def analysis_job(job_id: str):
        """Poll target for the ``job_id`` of a 202: queued / running / completed / failed
        (with ``error.code`` such as ``timeout``); failed on-demand jobs are not re-run until
        the data changes or ``/v1/analytics/recompute`` is called."""
        job = gw.supervisor.analysis.job(job_id)
        if job is None:
            raise ApiError(404, "not_found", "分析任务不存在或已过期")
        return job

    @api.post("/v1/analytics/recompute", status_code=202)
    def recompute(request: RecomputeRequest):
        unknown = [s for s in request.sections if s not in SECTIONS]
        if unknown:
            raise ApiError(422, "invalid_request", f"Unknown sections: {unknown}")
        allowed = SCOPE_PARAMS
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
