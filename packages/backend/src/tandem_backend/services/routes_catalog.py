"""`/v1/catalog/*` routes owned by the catalog module (registered in gateway.app()).

Registered before the legacy app mounted at "/", so every catalog path (items, search,
facets, local, models, sync jobs) is served by one gateway-level CatalogService on
``home/catalog.db``; only legacy-only paths such as ``/v1/catalog/match-analysis`` fall
through. Cards are decorated with installed/scan state from the features and install
modules when those are available; missing modules degrade to ``installed: null``.

First start and refresh (no network in ``router()``): the offline sources (bundled seed
list and the recommend KB as ``tandem-kb`` official items) are published synchronously, so
the library is never empty. Once the gateway has started, a background refresher imports
the bundled library snapshot (a fresh home only) and then asks the catalog to sync due
sources every ``REFRESH_TICK_S``; each source's ``refresh_seconds`` (24 h, MCP 1 h) decides
what is due, and an active catalog job skips the tick.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import weakref
from importlib.resources import files
from pathlib import Path
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


REFRESH_TICK_S = 15 * 60  # How often due sources are checked; sources decide their own cadence.
FIRST_SYNC_DELAY_S = 60.0  # Let the app settle (and the seed land) before the first network sync.
KB_SOURCE = "tandem-kb"


def register_kb(service) -> None:
    """Point the catalog's official ``tandem-kb`` source at the recommend KB (sole authority)."""
    from tandem_catalog.contracts import SourceSpec

    path = Path(str(files("tandem_backend").joinpath("data/recommend/remedies.v1.json")))
    if not path.is_file():
        return  # Packaged catalog falls back to its bundled official.v1.json export.
    current = next((s for s in service.store.sources() if s["source_id"] == KB_SOURCE), None)
    spec = SourceSpec(source_id=KB_SOURCE, kind="kb", url="bundled:kb", priority=100,
                      config={"file": str(path.resolve())},
                      enabled=bool(current["enabled"]) if current else True)
    service.store.register([spec])


def refresh_tick(service) -> dict | None:
    """Start one background sync of due sources; None when another catalog job is running."""
    from tandem_catalog.contracts import SyncRequest

    try:
        return service.start_sync(SyncRequest(concurrency=3))
    except ValueError as exc:
        if str(exc) == "catalog_job_already_active":
            return None
        raise


def _autosync_enabled() -> bool:
    return os.environ.get("TANDEM_CATALOG_AUTOSYNC", "1").lower() not in ("0", "false", "no")


def _refresher(ref: weakref.ref, service, poll_s: float = 1.0) -> None:
    """Waits for the gateway to start; holds only a weak reference so test gateways can go."""
    seeded, next_sync = False, None
    while True:
        gw = ref()
        if gw is None or gw.stopping.is_set():
            return
        stopping, started = gw.stopping, bool(getattr(gw.platform, "started", False))
        del gw
        if started:
            if not seeded:
                seeded = True
                try:
                    service.bootstrap()
                except Exception:  # noqa: BLE001 - a broken seed never stops the gateway.
                    log.warning("catalog seed import failed", exc_info=True)
                next_sync = time.monotonic() + FIRST_SYNC_DELAY_S
            if _autosync_enabled() and time.monotonic() >= next_sync:
                next_sync = time.monotonic() + REFRESH_TICK_S
                try:
                    refresh_tick(service)
                except Exception:  # noqa: BLE001
                    log.warning("catalog refresh failed to start", exc_info=True)
        if stopping.wait(poll_s):
            return


def bootstrap(service) -> None:
    """Synchronous, offline, ~0.1 s: official KB items and the bundled seed list."""
    try:
        register_kb(service)
        service.bootstrap(import_seed=False)
    except Exception:  # noqa: BLE001 - CatalogBusy (another process syncing) or a bad file.
        log.warning("catalog bootstrap skipped", exc_info=True)


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
    bootstrap(service)
    threading.Thread(target=_refresher, args=(weakref.ref(gw), service), daemon=True,
                     name="tandem-catalog-refresh").start()

    outer = APIRouter()

    @outer.get("/v1/catalog/status", tags=["resource catalog"])
    def status():  # Registered before catalog_router's /status, so this one answers.
        return {**service.store.stats(), "coverage": service.coverage()}

    outer.include_router(catalog_router(service, decorate))
    return outer
