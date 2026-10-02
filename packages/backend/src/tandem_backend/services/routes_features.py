"""`/v1` routes owned by the features module (registered in gateway.app()): user profile,
shared vocabulary, linked inventory and unified search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query

from .. import features
from ..features.service import FeatureService
from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway

PROFILE_EXTRAS = {"vector", "centroid", "evidence"}
Many = Annotated[list[str] | None, Query()]


def scope_from(project_id: list[str] | None, agent: list[str] | None,
               source_id: list[str] | None = None, since: int | None = None,
               until: int | None = None, include_children: bool = True) -> dict:
    if since is not None and until is not None and since >= until:
        raise ApiError(400, "invalid_request", "since 必须早于 until")
    return {"project_ids": project_id or None, "agent_ids": agent or None,
            "source_ids": source_id or None, "from_ts": since, "until_ts": until,
            "include_children": include_children}


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    svc = FeatureService(gw.home, gw.appdb, gw.revisions.snapshot)
    features.bind(svc)

    @api.get("/v1/features/profile")
    def profile(project_id: Many = None, agent: Many = None,
                source_id: Many = None, since: int | None = None,
                until: int | None = None, include_children: bool = True,
                include: str = "", refresh: bool = False):
        extras = {part.strip() for part in include.split(",") if part.strip()}
        if extras - PROFILE_EXTRAS:
            raise ApiError(400, "invalid_request",
                           f"include 只接受 {', '.join(sorted(PROFILE_EXTRAS))}")
        scope = scope_from(project_id, agent, source_id, since, until, include_children)
        body = svc.profile(scope, include=tuple(extras), refresh=refresh)
        for key in ("vector", "centroid"):
            if key not in extras:
                body.pop(key, None)
        return body

    @api.get("/v1/features/vocab")
    def vocab():
        return svc.vocab()

    @api.get("/v1/features/linked")
    @api.get("/v1/inventory/linked")
    def linked(project_id: Many = None, agent: Many = None,
               type: str | None = None, status: str | None = None):
        try:
            return svc.linked_inventory(scope_from(project_id, agent), type=type, status=status)
        except NotImplementedError as exc:
            raise ApiError(501, "not_implemented", str(exc)) from None

    @api.get("/v1/search")
    def search(q: str = "", kinds: str = "", project_id: Many = None,
               agent: Many = None, since: int | None = None,
               until: int | None = None, limit: int = Query(20, ge=1, le=100)):
        q = q.strip()
        if not q or len(q) > 200:
            raise ApiError(400, "invalid_request", "q 不能为空且不超过 200 字")
        kind_list = [k.strip() for k in kinds.split(",") if k.strip()] or None
        try:
            return svc.search(q, kinds=kind_list, scope=scope_from(project_id, agent, None,
                                                                   since, until), limit=limit)
        except NotImplementedError as exc:
            raise ApiError(501, "not_implemented", str(exc)) from None

    return api
