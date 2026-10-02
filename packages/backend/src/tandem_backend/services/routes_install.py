"""`/v1/install` routes: environment, plans, preview, apply, revert, ledger, lifecycle, fetch.

Shapes follow ``prototypes/advance/src/js/51-install.js``: ``targets[].units[]`` and
``targets[].diff.lines[{n, op, text}]`` (op ``+ - ' ' ai``), ``totals.adds/dels``,
``backup_dir`` / ``backup_path``, ``undo_until_ms``, ``requires_trust`` and ``agents``
(“同时应用到 Codex” = codex in agents; turned off per target via ``disabled_targets``).
Install errors carry ``.code`` / ``.http`` / ``.detail`` and map straight to the response.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway


class InstallApiError(ApiError):
    """ApiError with an optional ``detail`` (stale targets, risk findings, revert results)."""

    def __init__(self, status: int, code: str, message: str, detail: Any = None):
        super().__init__(status, code, message, retryable=status in (423, 500))
        self.detail = detail

    def payload(self) -> dict:
        body = super().payload()
        if self.detail is not None:
            body["error"]["detail"] = self.detail
        return body


class Source(BaseModel):
    type: Literal["candidate", "catalog", "artifact", "spec", "collect"]
    id: str | None = None
    spec: dict | None = None


class PlanRequest(BaseModel):
    source: Source
    agents: list[str] | None = None
    scope: Literal["user", "project"] = "user"
    project_path: str | None = None
    fetch: bool = False


class SelectionRequest(BaseModel):
    selected_units: dict[str, list[str]] | None = None
    disabled_targets: list[int] = Field(default_factory=list)


class PreviewRequest(SelectionRequest):
    plan_id: str | None = None
    source: Source | None = None
    agents: list[str] | None = None
    scope: Literal["user", "project"] = "user"
    project_path: str | None = None
    fetch: bool = False


class ApplyRequest(SelectionRequest):
    plan_id: str
    preview_digest: str
    override_risk: bool = False
    surface: str = "A7"  # recommend exposure surface for candidate installs


class RevertRequest(BaseModel):
    targets: list[int] | None = None


class RevertManyRequest(BaseModel):
    install_ids: list[str] = Field(min_length=1, max_length=100)


class LifecycleRequest(BaseModel):
    to: Literal["installed", "observing", "kept", "idle", "reverted", "archived"]


class FetchRequest(BaseModel):
    source: dict | None = None
    catalog_id: str | None = None
    refresh: bool = False


def _catalog_lookup(gw: Gateway) -> Callable[[str], dict | None]:
    """Catalog item by id: the gateway's CatalogService when it exposes one, else a read-only
    ``catalog.db`` in the Tandem home, else the bundled legacy seed. Every catalog answer is
    mapped through ``install.plan.catalog_item`` (source / install.{mcp|plugin|hook} / license / agents)."""
    from ..install.plan import catalog_item, default_catalog_lookup

    stores: dict = {}

    def detail(item_id: str) -> dict | None:
        service = getattr(gw, "catalog", None)
        if callable(getattr(service, "item", None)):
            return service.item(item_id)
        store = getattr(service, "store", None)
        if store is None:
            path = Path(gw.home) / "catalog.db"
            if not path.is_file():
                return None
            if path not in stores:
                from tandem_catalog.store import CatalogStore

                stores[path] = CatalogStore(path)
            store = stores[path]
        return store.detail(item_id)

    def lookup(item_id: str) -> dict | None:
        found = None
        with contextlib.suppress(Exception):
            found = detail(item_id)
        if found:
            return catalog_item(found) if ("resource" in found or "item_id" in found) else found
        return default_catalog_lookup(item_id)

    return lookup


def router(gw: Gateway) -> APIRouter:
    from ..install import set_default_service
    from ..install.service import InstallService

    api = APIRouter()
    def artifact_status(artifact_id: str, status: str, install_id: str) -> None:
        from ..ai.service import service as ai_service

        ai_service(gw).set_artifact_status(artifact_id, status, install_id=install_id)

    svc = InstallService(gw.appdb, gw.home, reads=gw.reads, jobs=gw.jobs, catalog_lookup=_catalog_lookup(gw),
                         artifact_status=artifact_status)
    set_default_service(svc)
    gw.install = svc
    with contextlib.suppress(Exception):  # settle installs a crash left half-recorded
        svc.reconcile()
    with contextlib.suppress(Exception):  # retention / idle sweep (cheap; no platform hook yet)
        svc.maintain()

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            if code is None:
                raise
            status = int(getattr(error, "http", 400) or 400)
            message = getattr(error, "message", None) or str(error) or code
            raise InstallApiError(status, code, message, getattr(error, "detail", None)) from None

    @api.get("/v1/install/environment")
    def environment(refresh: int = Query(0, ge=0, le=1)):
        return call(svc.environment, bool(refresh))

    @api.get("/v1/install/collect")
    def collect_status():
        from ..install.collect import status

        return call(status, svc)

    @api.post("/v1/install/plans", status_code=201)
    def create_plan(body: PlanRequest):
        return call(svc.plan, body.source.model_dump(), agents=body.agents, scope=body.scope,
                    project_path=body.project_path, fetch=body.fetch)

    @api.get("/v1/install/plans/{plan_id}/preview")
    def get_preview(plan_id: str):
        return call(svc.preview, plan_id)

    @api.post("/v1/install/plans/{plan_id}/preview")
    def post_preview(plan_id: str, body: SelectionRequest):
        return call(svc.preview, plan_id, body.selected_units, body.disabled_targets)

    @api.post("/v1/install/preview")
    def preview_alias(body: PreviewRequest):
        plan = None
        plan_id = body.plan_id
        if plan_id is None:
            if body.source is None:
                raise InstallApiError(422, "invalid_request", "需要 plan_id 或 source")
            plan = call(svc.plan, body.source.model_dump(), agents=body.agents, scope=body.scope,
                        project_path=body.project_path, fetch=body.fetch)
            if plan["status"] not in ("ready", "unmappable"):
                return {"plan": plan, "preview": None}
            plan_id = plan["plan_id"]
        preview = call(svc.preview, plan_id, body.selected_units, body.disabled_targets)
        return {**preview, "plan": plan} if plan else preview

    @api.post("/v1/install/apply")
    def apply(body: ApplyRequest):
        return call(svc.apply, body.plan_id, body.preview_digest, body.selected_units, body.disabled_targets,
                    body.override_risk, body.surface)

    @api.post("/v1/install/revert")
    def revert_many(body: RevertManyRequest):
        return call(svc.revert_many, body.install_ids)

    @api.get("/v1/install/ledger")
    def ledger(install_id: str | None = None, limit: int = Query(50, ge=1, le=500), before: int | None = None):
        return call(svc.ledger, install_id, limit, before)

    @api.get("/v1/install/state")
    def state(state: str | None = None):
        return {"items": call(svc.list_state, state)}

    @api.post("/v1/install/fetch")
    def fetch(body: FetchRequest):
        source = body.source
        if source is None and body.catalog_id:
            item = svc.catalog_lookup(body.catalog_id)
            if not item:
                raise InstallApiError(404, "catalog_unavailable", f"目录条目不可用：{body.catalog_id}")
            source = item.get("source")
        if not source:
            raise InstallApiError(422, "invalid_request", "需要 source 或带来源的 catalog_id")
        return call(svc.fetch, source, body.refresh)

    @api.post("/v1/install/{install_id}/revert")
    def revert(install_id: str, body: RevertRequest | None = None):
        result = call(svc.revert, install_id, body.targets if body else None)
        if not result["ok"]:
            raise InstallApiError(409, "revert_refused", "部分文件在安装后被修改，未自动撤销", result)
        return result

    @api.post("/v1/install/{install_id}/lifecycle")
    def lifecycle(install_id: str, body: LifecycleRequest):
        from ..install import lifecycle as lifecycle_mod

        return call(lifecycle_mod.transition, svc, install_id, body.to)

    @api.get("/v1/install/{install_id}")
    def get_install(install_id: str):
        return call(svc.get, install_id)

    return api
