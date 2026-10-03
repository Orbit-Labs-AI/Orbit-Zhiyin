"""`/v1/catalog/*` routes owned by the catalog module (registered in gateway.app()).

Registered before the legacy app mounted at "/", so every catalog path (items, search,
facets, local, models, sync jobs) is served by one gateway-level CatalogService on
``home/catalog.db``; only legacy-only paths such as ``/v1/catalog/match-analysis`` fall
through. Cards are decorated with installed state from the features module when available
(missing modules degrade to ``installed: null``); ``/v1/catalog/library`` gets the session
profile and the installed summary from features through the hooks passed to catalog_router.

First start and refresh (no network in ``router()``): the offline sources (bundled seed
list and the recommend KB as ``orbit-kb`` official items) are published synchronously, so
the library is never empty. Once the gateway has started, a background refresher imports
the bundled library snapshot (a fresh home only) and then asks the catalog to sync due
sources every ``REFRESH_TICK_S`` (a library with no network data syncs right after start and
reports it as ``first_sync`` in ``/v1/catalog/status``); each source's ``refresh_seconds`` (24 h, MCP 1 h) decides
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
DAY_MS = 86_400_000


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


def installed_summary() -> dict | None:
    """A8-02 counts: Orbit-installed (ledger, undoable) vs manually installed components."""
    try:
        result = features.linked_inventory()
    except Exception:  # noqa: BLE001
        log.debug("linked_inventory unavailable", exc_info=True)
        return None
    items = result.get("items", [])
    orbit = sum(1 for row in items if row.get("orbit_installed"))
    return {"orbit": orbit, "manual": len(items) - orbit}


def library_profile(scope: dict) -> dict | None:
    """features.profile over the last ``window_days`` (day-aligned for cache reuse) → catalog pairs.

    Returns None when the features module is not bound; ``ok`` is False when the window holds no
    session features, so the catalog side never fabricates personal reasons.
    """
    if features.current() is None:
        return None
    from ..features.scope import normalize
    from ..features.vocab import label, to_catalog_pairs
    from .snapshots import scope_hash

    window = int(scope.get("window_days") or 30)
    wanted = {"from_ts": (int(time.time() * 1000) // DAY_MS - window) * DAY_MS}
    if scope.get("project_ids"):
        wanted["project_ids"] = list(scope["project_ids"])
    try:
        body = features.profile(wanted)
    except Exception:  # noqa: BLE001 - library must render without a profile.
        log.debug("profile unavailable", exc_info=True)
        return None
    entries = {e["id"]: e for e in body.get("tags", [])}
    for group in (body.get("groups") or {}).values():
        for e in group:
            entries.setdefault(e["id"], e)
    pairs = []
    for fid, weight in (body.get("vector") or {}).items():
        entry = entries.get(fid, {})
        for feature, value in to_catalog_pairs(fid):
            pairs.append({"fid": fid, "feature": feature, "value": value, "weight": float(weight),
                          "sessions": entry.get("sessions"), "label": entry.get("label") or label(fid)})
    n = int(body.get("n_sessions") or 0)
    return {"ok": bool(n and pairs), "n_sessions": n, "window_days": window, "features": pairs,
            "scope_hash": scope_hash(normalize(wanted))}


# GETs whose bodies depend only on the catalog generation and the installed state.
ETAG_PREFIXES = ("/v1/catalog/items", "/v1/catalog/library", "/v1/catalog/facets", "/v1/catalog/search",
                 "/v1/catalog/models", "/v1/catalog/benchmarks")


REFRESH_TICK_S = 15 * 60  # How often due sources are checked; sources decide their own cadence.
FIRST_SYNC_DELAY_S = 60.0  # Let the app settle (and the seed land) before the first network sync.
FIRST_RUN_DELAY_S = 3.0  # Empty library (no network source ever completed): sync almost at once.
KB_SOURCE = "orbit-kb"


def register_kb(service) -> None:
    """Point the catalog's official ``orbit-kb`` source at the recommend KB (sole authority)."""
    from orbit_catalog.contracts import SourceSpec

    path = Path(str(files("orbit_backend").joinpath("data/recommend/remedies.v1.json")))
    if not path.is_file():
        return  # Packaged catalog falls back to its bundled official.v1.json export.
    current = next((s for s in service.store.sources() if s["source_id"] == KB_SOURCE), None)
    spec = SourceSpec(source_id=KB_SOURCE, kind="kb", url="bundled:kb", priority=100,
                      config={"file": str(path.resolve())},
                      enabled=bool(current["enabled"]) if current else True)
    service.store.register([spec])


def refresh_tick(service) -> dict | None:
    """Start one background sync of due sources; None when another catalog job is running."""
    from orbit_catalog.contracts import SyncRequest

    try:
        return service.start_sync(SyncRequest(concurrency=3))
    except ValueError as exc:
        if str(exc) == "catalog_job_already_active":
            return None
        raise


def _autosync_enabled() -> bool:
    return os.environ.get("ORBIT_CATALOG_AUTOSYNC", "1").lower() not in ("0", "false", "no")


def _refresher(ref: weakref.ref, service, poll_s: float = 1.0) -> None:
    """Waits for the gateway to start; holds only a weak reference so test gateways can go.

    First run (G7): while no network source has ever completed, the sync starts
    ``FIRST_RUN_DELAY_S`` after start (retried each poll while another catalog job runs) and is
    reported by ``service.first_sync_state()``; afterwards due sources sync every tick.
    """
    seeded, next_sync, first = False, None, False
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
                first = _needs_first_sync(service)
                next_sync = time.monotonic() + (FIRST_RUN_DELAY_S if first else FIRST_SYNC_DELAY_S)
                due_at = int((time.time() + FIRST_RUN_DELAY_S) * 1000) if first else None
                _track(service, "disabled" if not _autosync_enabled() else "scheduled" if first else "not_needed",
                       due_at=due_at)
            if _autosync_enabled() and time.monotonic() >= next_sync:
                next_sync = time.monotonic() + REFRESH_TICK_S
                try:
                    job = refresh_tick(service)
                    if first and job is None:  # Another catalog job: retry soon, not in 15 min.
                        next_sync = time.monotonic() + FIRST_RUN_DELAY_S
                        _track(service, "deferred")
                    elif first:
                        _track(service, "started", job_id=job["job_id"])
                        first = False
                except Exception:  # noqa: BLE001
                    log.warning("catalog refresh failed to start", exc_info=True)
        if stopping.wait(poll_s):
            return


def _needs_first_sync(service) -> bool:
    try:
        return bool(service.needs_network_sync())
    except Exception:  # noqa: BLE001 - a stand-in or busy store: treat as already synced.
        return False


def _track(service, state: str, **fields) -> None:
    track = getattr(service, "track_first_sync", None)
    if track is not None:
        track(state, **fields)


def bootstrap(service) -> None:
    """Synchronous, offline, ~0.1 s: official KB items and the bundled seed list."""
    try:
        register_kb(service)
        service.bootstrap(import_seed=False)
    except Exception:  # noqa: BLE001 - CatalogBusy (another process syncing) or a bad file.
        log.warning("catalog bootstrap skipped", exc_info=True)


def router(gw: Gateway) -> APIRouter:
    from orbit_catalog import get_service
    from orbit_catalog.api import catalog_router

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
        profile_rev = features.current().etag() if features.current() is not None else "unbound"
        return f"{generation}.{value.get('data_rev')}.{value.get('inventory_rev') or 0}.{profile_rev}"

    for prefix in ETAG_PREFIXES:
        # The library window is day-aligned, so its tag also moves when the day rolls over.
        platform.register_etag(prefix, (lambda: f"{rev()}.{int(time.time() * 1000) // DAY_MS}")
                               if prefix == "/v1/catalog/library" else rev)

    def on_job_done(job: dict) -> None:
        platform.record(f"catalog.{job['kind']}", job.get("duration_ms") or 0, status=job["status"])
        if job["kind"] == "sync":
            for source in job.get("result") or []:
                platform.record("catalog.sync.source", source.get("duration_ms") or 0,
                                source=source.get("source_id"), status=source.get("status"))

    service.on_job_done = on_job_done
    bootstrap(service)
    threading.Thread(target=_refresher, args=(weakref.ref(gw), service), daemon=True,
                     name="orbit-catalog-refresh").start()

    outer = APIRouter()

    def status_summary():
        return {**service.store.stats(), "coverage": service.coverage(), "first_sync": service.first_sync_state()}

    outer.include_router(catalog_router(service, decorate, profile=library_profile,
                                       installed_summary=installed_summary, status_summary=status_summary))
    return outer
