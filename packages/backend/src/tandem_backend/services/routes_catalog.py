"""`/v1/catalog/*` routes owned by the catalog module (registered in gateway.app()).

Registered before the legacy app mounted at "/", so every catalog path (items, search,
facets, local, models, sync jobs) is served by one gateway-level CatalogService on
``home/catalog.db``; only legacy-only paths such as ``/v1/catalog/match-analysis`` fall
through. Cards are decorated with installed state from the features module when available
(missing modules degrade to ``installed: null``); ``/v1/catalog/library`` gets the session
profile and the installed summary from features through the hooks passed to catalog_router.
"""

from __future__ import annotations

import logging
import sqlite3
import time
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
    """A8-02 counts: Tandem-installed (ledger, undoable) vs manually installed components."""
    try:
        result = features.linked_inventory()
    except Exception:  # noqa: BLE001
        log.debug("linked_inventory unavailable", exc_info=True)
        return None
    items = result.get("items", [])
    tandem = sum(1 for row in items if row.get("tandem_installed"))
    return {"tandem": tandem, "manual": len(items) - tandem}


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
    return catalog_router(service, decorate, profile=library_profile, installed_summary=installed_summary)
