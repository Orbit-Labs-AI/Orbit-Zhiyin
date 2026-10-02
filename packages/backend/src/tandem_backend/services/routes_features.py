"""`/v1` routes owned by the features module (registered in gateway.app())."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()

    def linked_inventory(project_ids=None, agent=None) -> dict:
        """DT-09 x catalog x usage (AN-11 installed_unused, RC-07 subtraction)."""
        from ..features import linked

        if not (gw.home / "tandem.db").is_file():
            raise ApiError(503, "no_projection", "No canonical database yet; import a source",
                           retryable=True, retry_after=2)

        def write(fn) -> None:
            with gw.appdb.write() as db:
                fn(db)

        revisions = gw.revisions.snapshot()
        try:
            conn = linked.open_connection(gw.home)
        except sqlite3.Error as error:
            raise ApiError(503, "service_unavailable", f"Database busy: {error}",
                           retryable=True, retry_after=1) from error
        try:
            revs = {"data": revisions["data_rev"], "inventory": revisions["inventory_rev"],
                    "catalog": linked.catalog_rev(conn)}
            return linked.compute_linked(conn, revs=revs, project_ids=project_ids, agent=agent,
                                         write=write)
        finally:
            conn.close()

    @api.get("/v1/features/linked")
    def features_linked(project_ids: str | None = None, agent: str | None = None):
        projects = [p for p in project_ids.split(",") if p] if project_ids else None
        return linked_inventory(projects, agent)

    @api.get("/v1/search")
    def search(q: str = Query(..., max_length=400), kinds: str | None = None,
               project_ids: str | None = None, agent_ids: str | None = None,
               from_ts: int | None = None, until_ts: int | None = None,
               limit: int = Query(20, ge=1, le=50)):
        from ..features import search as unified

        scope = unified.scope_from_query(project_ids, agent_ids, from_ts, until_ts)
        wanted = [k for k in kinds.split(",") if k] if kinds else None
        try:
            return unified.search(gw.home, q, kinds=wanted, scope=scope, limit=limit,
                                  data_rev=gw.revisions.snapshot()["data_rev"] or 0,
                                  linked=lambda: linked_inventory())
        except ValueError as error:
            raise ApiError(400, "invalid_request", str(error)) from error

    return api
