"""Loopback API for both the existing backend and a standalone catalog worker.

Errors are ``HTTPException(status, detail=<snake_code>)``. ``decorate(cards)`` lets the
gateway attach installed/scan state from other modules without this package importing them.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Query, Response
from pydantic import Field

from . import query
from .contracts import Contract, LocalItem, MatchRequest, SyncRequest
from .store import CatalogBusy

Strs = Annotated[list[str] | None, Query()]
Risk = Annotated[int | None, Query(ge=0, le=3)]


class EnableRequest(Contract):
    enabled: bool


class EmbeddingRequest(Contract):
    max_chunks: int | None = Field(default=256, ge=1, le=1000000)


def catalog_router(service, decorate: Callable[[list[dict]], None] | None = None,
                   profile: Callable[[dict], dict | None] | None = None,
                   installed_summary: Callable[[], dict | None] | None = None) -> APIRouter:
    """``profile(scope)`` returns the library profile (see query.library) or None; both hooks are
    supplied by the gateway so this package never imports the features module."""
    router = APIRouter(prefix="/v1/catalog", tags=["resource catalog"])

    def invoke(operation):
        try:
            return operation()
        except CatalogBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            code = 409 if str(exc) == "catalog_job_already_active" else 422
            raise HTTPException(code, str(exc) if str(exc).replace("_", "").isalnum() else "invalid_query") from exc

    def decorated(cards: list[dict]) -> list[dict]:
        if decorate is not None and cards:
            decorate(cards)
        return cards

    def filters(kind, agent, license, max_risk, origin, official, source_id, exclude, include_duplicates):
        return {"kinds": kind or [], "agents": agent or [], "license": license, "max_risk": max_risk, "origin": origin,
                "official": official, "source_id": source_id, "exclude": exclude or [],
                "include_duplicates": include_duplicates}

    @router.get("/status")
    def status():
        return service.store.stats()

    @router.get("/sources")
    def sources():
        return service.store.sources()

    @router.put("/sources/{source_id}")
    def configure_source(source_id: str, request: EnableRequest):
        invoke(lambda: service.set_enabled(source_id, request.enabled))
        return {"source_id": source_id, "enabled": request.enabled}

    @router.post("/sync", status_code=202)
    def sync(request: SyncRequest):
        return invoke(lambda: service.start_sync(request))

    @router.post("/embeddings", status_code=202)
    def embeddings(request: EmbeddingRequest):
        return invoke(lambda: service.start_embeddings(request.max_chunks))

    @router.get("/jobs/{job_id}")
    def job(job_id: str):
        result = service.job(job_id)
        if result is None:
            raise HTTPException(404, "catalog_job_not_found")
        return result

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        if not service.cancel(job_id):
            raise HTTPException(404, "catalog_job_not_found")
        return {"job_id": job_id, "cancel_requested": True}

    @router.post("/search")
    def match(request: MatchRequest):
        return invoke(lambda: service.match(request))

    @router.get("/search")
    def search_cards(q: Annotated[str, Query(max_length=2000)] = "", kind: Strs = None,
                     agent: Strs = None, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                     prefix: bool = True):
        if not q.strip():
            raise HTTPException(422, "invalid_query")
        result = invoke(lambda: service.search_cards(q, kind or [], agent or [], limit, prefix))
        decorated(result["items"])
        return result

    @router.get("/library")
    def library(tab: str = "for", kind: Strs = None, agent: Strs = None,
                q: Annotated[str, Query(max_length=2000)] = "", sort: str = "fit", exclude: Strs = None,
                limit: Annotated[int, Query(ge=1, le=50)] = 20, cursor: str | None = None,
                project_id: Strs = None, window_days: Annotated[int, Query(ge=1, le=365)] = 30):
        basis = profile({"project_ids": project_id or None, "window_days": window_days}) if profile else None
        result = invoke(lambda: service.library(profile=basis, tab=tab, kinds=kind or [], agents=agent or [], q=q,
                                                sort=sort, exclude=exclude or [], limit=limit, cursor=cursor))
        if basis is None:
            result["profile_basis"]["window_days"] = window_days
        decorated(result["items"])
        result["installed_summary"] = installed_summary() if installed_summary else None
        return result

    @router.get("/items")
    def items(kind: Strs = None, agent: Strs = None, license: str | None = None,
              max_risk: Risk = None, origin: str | None = None,
              official: bool | None = None, source_id: str | None = None, exclude: Strs = None,
              sort: str = "updated", order: str = "desc", limit: Annotated[int, Query(ge=1, le=100)] = 30,
              cursor: str | None = None, include_duplicates: bool = False, id: Strs = None,
              type_: Annotated[list[str] | None, Query(alias="type")] = None):
        kind = [*(kind or []), *(type_ or [])] or None  # ``?type=`` was silently ignored
        if id:
            if len(id) > 50:
                raise HTTPException(422, "too_many_ids")
            result = query.cards_by_id(service.store, id)
            decorated(result["items"])
            return result
        result = invoke(lambda: query.list_items(
            service.store, sort=sort, order=order, limit=limit, cursor=cursor,
            **filters(kind, agent, license, max_risk, origin, official, source_id, exclude, include_duplicates)))
        decorated(result["items"])
        return result

    @router.get("/facets")
    def facets(kind: Strs = None, agent: Strs = None, license: str | None = None,
               max_risk: Risk = None, origin: str | None = None,
               official: bool | None = None, source_id: str | None = None, exclude: Strs = None,
               include_duplicates: bool = False):
        return invoke(lambda: query.facets(service.store, **filters(
            kind, agent, license, max_risk, origin, official, source_id, exclude, include_duplicates)))

    @router.get("/items/detail")
    def detail(item_id: str = Query(min_length=1, max_length=1000)):
        result = service.store.detail(item_id)
        if result is None:
            raise HTTPException(404, "catalog_item_not_found")
        return result

    @router.get("/items/{item_id:path}")
    def item(item_id: str):
        result = query.get_item(service.store, item_id)
        if result is None:
            raise HTTPException(404, "catalog_item_not_found")
        decorated([result])
        return result

    @router.post("/local", status_code=201)
    def add_local(request: LocalItem, response: Response):
        result = invoke(lambda: service.add_local(request))
        if not result["created"]:
            response.status_code = 200
        return result

    @router.delete("/local/{item_id:path}", status_code=204)
    def remove_local(item_id: str):
        if not item_id.startswith("local:"):
            raise HTTPException(422, "not_a_local_item")
        if not invoke(lambda: service.remove_local(item_id)):
            raise HTTPException(404, "catalog_item_not_found")
        return Response(status_code=204)

    @router.get("/models")
    def models(provider: str | None = None, q: str | None = None, sort: str = "name",
               limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None):
        return invoke(lambda: query.models(service.store, provider=provider, q=q, sort=sort, limit=limit, cursor=cursor))

    @router.get("/models/{canonical_id:path}")
    def model(canonical_id: str):
        result = query.get_model(service.store, canonical_id)
        if result is None:
            raise HTTPException(404, "catalog_model_not_found")
        return result

    @router.get("/benchmarks")
    def benchmarks(model: str | None = None, benchmark: str | None = None, effort: str | None = None,
                   harness: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 100, cursor: str | None = None):
        return invoke(lambda: query.benchmarks(service.store, model=model, benchmark=benchmark, effort=effort,
                                               harness=harness, limit=limit, cursor=cursor))

    return router


def create_catalog_app(service, decorate=None) -> FastAPI:  # Standalone worker: library without profile.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()

    app = FastAPI(title="Tandem resource catalog", version="1.0", lifespan=lifespan)
    app.include_router(catalog_router(service, decorate))
    return app
