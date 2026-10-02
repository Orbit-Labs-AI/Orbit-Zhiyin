"""`/v1/catalog/*` routes owned by the catalog module (registered in gateway.app()).

Registered before the legacy app mounted at "/", so every catalog path (items, search,
facets, local, models, sync jobs) is served by one gateway-level CatalogService on
``home/catalog.db``; only legacy-only paths such as ``/v1/catalog/match-analysis`` fall
through. Cards are decorated with installed/scan state from the features and install
modules when those are available; missing modules degrade to ``installed: null``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from .gateway import Gateway

log = logging.getLogger(__name__)


def _installed_index() -> dict | None:
    try:
        from tandem_backend.features import linked_inventory  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return None
    try:
        rows = linked_inventory() or []
    except Exception:  # noqa: BLE001 - decoration is optional; never fail a catalog read.
        log.debug("linked_inventory unavailable", exc_info=True)
        return None
    found = {}
    for row in rows:
        item_id = row.get("catalog_item_id") if isinstance(row, dict) else None
        if item_id:
            entry = found.setdefault(item_id, {"state": row.get("state", "installed"), "agents": [], "scope": row.get("scope")})
            agent = row.get("agent")
            if agent and agent not in entry["agents"]:
                entry["agents"].append(agent)
    return found


def _scan(item_id: str):
    try:
        from tandem_backend.install import scan_item  # type: ignore[attr-defined]
        return scan_item(item_id)
    except Exception:  # noqa: BLE001 - optional enrichment.
        return None


def decorate(cards: list[dict]) -> None:
    installed = _installed_index() or {}
    for card in cards:
        card["installed"] = installed.get(card["item_id"])
    if len(cards) == 1 and "permissions" in cards[0]:  # Item detail.
        cards[0]["scan"] = _scan(cards[0]["item_id"])


def router(gw: Gateway) -> APIRouter:
    from tandem_catalog import get_service
    from tandem_catalog.api import catalog_router

    return catalog_router(get_service(gw.home / "catalog.db"), decorate)
