"""Loopback API for both the existing backend and a standalone catalog worker."""

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import Field

from .contracts import Contract, MatchRequest, SyncRequest
from .store import CatalogBusy


class EnableRequest(Contract):
    enabled: bool


class EmbeddingRequest(Contract):
    max_chunks: int | None = Field(default=256, ge=1, le=1000000)


def catalog_router(service) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["resource catalog"])

    def invoke(operation):
        try:
            return operation()
        except CatalogBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            code = 409 if str(exc) == "catalog_job_already_active" else 422
            raise HTTPException(code, str(exc)) from exc

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

    @router.get("/items/detail")
    def detail(item_id: str = Query(min_length=1, max_length=1000)):
        result = service.store.detail(item_id)
        if result is None:
            raise HTTPException(404, "catalog_item_not_found")
        return result

    return router


def create_catalog_app(service) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()

    app = FastAPI(title="Tandem resource catalog", version="1.0", lifespan=lifespan)
    app.include_router(catalog_router(service))
    return app
