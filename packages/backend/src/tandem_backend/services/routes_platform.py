"""`/v1/platform` routes: health, local metrics, telemetry settings, flags, storage,
maintenance and diagnostics (registered in gateway.app())."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from ..platform import diagnostics, storage
from ..platform.health import health
from ..platform.maintenance import UnknownTask
from ..platform.settings import SettingsError
from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway


class MaintenanceRequest(BaseModel):
    task: str


def router(gw: Gateway) -> APIRouter:
    from ..platform import routes_notify

    api = APIRouter()
    p = gw.platform

    def telemetry_view() -> dict:
        return {**p.settings.get("telemetry"), "stats": p.telemetry.stats()}

    @api.get("/v1/platform/health")
    async def platform_health(deep: bool = False):
        if deep:
            return await asyncio.to_thread(health, p, True)
        return health(p)

    @api.get("/v1/platform/metrics")
    def metrics(request: Request, name: str | None = None,
                window: int = Query(3600, ge=60, le=30 * 86_400),
                step: Literal["minute", "hour", "total"] = "minute"):
        if not p.telemetry.enabled:
            return {"enabled": False, "window_s": window, "series": []}
        tags = {k[4:]: v for k, v in request.query_params.items() if k.startswith("tag.")}
        return {"enabled": True, "window_s": window,
                **p.telemetry.query(name or None, window, step, tags or None)}

    @api.get("/v1/platform/telemetry")
    def get_telemetry():
        return telemetry_view()

    @api.put("/v1/platform/telemetry")
    def put_telemetry(patch: dict[str, Any]):
        try:
            p.settings.put_telemetry(patch)
        except SettingsError as error:
            raise ApiError(422, "invalid_request", str(error)) from None
        p.refresh()
        return telemetry_view()

    @api.delete("/v1/platform/telemetry/data")
    def delete_telemetry():
        return {"deleted_rows": p.telemetry.clear()}

    @api.get("/v1/platform/flags")
    def get_flags():
        return p.settings.get("flags")

    @api.put("/v1/platform/flags")
    def put_flags(patch: dict[str, Any]):
        try:
            flags = p.settings.put_flags(patch)
        except SettingsError as error:
            raise ApiError(422, "invalid_request", str(error)) from None
        p.refresh()
        return flags

    @api.get("/v1/platform/recommend")
    def get_recommend():
        return p.settings.get("recommend")

    @api.put("/v1/platform/recommend")
    def put_recommend(patch: dict[str, Any]):
        try:
            return p.settings.put_recommend(patch)
        except SettingsError as error:
            raise ApiError(422, "invalid_request", str(error)) from None

    @api.get("/v1/platform/storage")
    def platform_storage():
        report = storage.latest_report(p.appdb)
        if report is None:
            report = storage.storage_report(p.home)
            storage.save_report(p.appdb, report)
        return report

    @api.get("/v1/platform/maintenance")
    def maintenance_status():
        return p.maintenance.status()

    @api.post("/v1/platform/maintenance/run")
    def maintenance_run(request: MaintenanceRequest):
        try:
            return p.maintenance.run(request.task)
        except UnknownTask:
            raise ApiError(422, "invalid_request", f"unknown task: {request.task}") from None

    @api.get("/v1/platform/diagnostics")
    def diagnostics_view():
        return diagnostics.collect(p)

    @api.post("/v1/platform/diagnostics/export")
    def diagnostics_export():
        return diagnostics.export(p)

    api.include_router(routes_notify.router(gw))
    return api
