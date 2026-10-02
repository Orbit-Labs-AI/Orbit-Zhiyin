"""`/v1/catalog/*` routes owned by the catalog module (registered in gateway.app()).

Registered before the legacy app mounted at "/", so every catalog path (items, search,
facets, local, models, sync jobs) is served by one gateway-level CatalogService on
``home/catalog.db``; only legacy-only paths such as ``/v1/catalog/match-analysis`` fall
through. Cards are decorated with installed/scan state from the features and install
modules when those are available; missing modules degrade to ``installed: null``.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from fastapi import APIRouter

from .. import features, platform

if TYPE_CHECKING:
    from .gateway import Gateway

log = logging.getLogger(__name__)


def _installed_index() -> dict | None:
    """catalog item_id -> {state, agents, scope} from the features linked inventory."""
    try:
        result = features.linked_inventory()
    except Exception:  # noqa: BLE001 - decoration is optional; never fail a catalog read.
        log.debug("linked_inventory unavailable", exc_info=True)
        return None
    found = {}
    for row in result.get("items", []):
        item_id = (row.get("catalog") or {}).get("item_id")
        if item_id:
            entry = found.setdefault(item_id, {"state": row.get("status"), "agents": [], "scope": row.get("scope")})
            if row.get("agent") and row["agent"] not in entry["agents"]:
                entry["agents"].append(row["agent"])
    return found


def decorate(cards: list[dict]) -> None:
    installed = _installed_index() or {}
    for card in cards:
        card["installed"] = installed.get(card["item_id"])
    if len(cards) == 1 and "permissions" in cards[0]:  # Item detail.
        cards[0]["scan"] = None  # install exposes no per-catalog-item scan yet; it scans plans.


# GETs whose bodies depend only on the catalog generation and the installed state.
ETAG_PREFIXES = ("/v1/catalog/items", "/v1/catalog/facets", "/v1/catalog/search",
                 "/v1/catalog/models", "/v1/catalog/benchmarks")


def router(gw: Gateway) -> APIRouter:
    from tandem_catalog import get_service
    from tandem_catalog.api import catalog_router

    try:
        service = get_service(gw.home / "catalog.db")
    except (ValueError, OSError, sqlite3.Error):
        # A foreign or unreadable catalog.db must not stop the gateway; catalog paths 404.
        log.warning("catalog unavailable", exc_info=True)
        return APIRouter()

    def rev():
        with service.store.reader() as conn:
            generation = service.store.generation(conn)
        value = gw.revisions.value
        return f"{generation}.{value.get('data_rev')}.{value.get('inventory_rev') or 0}"

    for prefix in ETAG_PREFIXES:
        platform.register_etag(prefix, rev)

    def on_job_done(job: dict) -> None:
        platform.record(f"catalog.{job['kind']}", job.get("duration_ms") or 0, status=job["status"])
        if job["kind"] == "sync":
            for source in job.get("result") or []:
                platform.record("catalog.sync.source", source.get("duration_ms") or 0,
                                source=source.get("source_id"), status=source.get("status"))

    service.on_job_done = on_job_done
    return catalog_router(service, decorate)
