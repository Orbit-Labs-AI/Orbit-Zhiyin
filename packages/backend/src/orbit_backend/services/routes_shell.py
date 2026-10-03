"""``/v1/shell/*``: aggregate reads for the shell surfaces (menu-bar popover, widgets,
onboarding, persona reveal). Creating the router also registers the shell producers:
the bus tap for "first analysis / persona ready" and the hourly maintenance tasks
``source_watch`` and ``weekly_report``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from .routes_analytics import analytics_scope

if TYPE_CHECKING:
    from .gateway import Gateway


def router(gw: Gateway) -> APIRouter:
    from ..shell import local_offset_min, onboarding, popover, producers, reveal, tasks

    api = APIRouter()
    scope_dependency = Depends(analytics_scope)

    watcher = getattr(gw, "shell_watcher", None)
    if watcher is None:
        watcher = gw.shell_watcher = producers.AnalysisWatcher(gw)
        gw.platform.observers.append(watcher.observe)
        tasks.register(gw)

    @api.get("/v1/shell/popover")
    def shell_popover(tz_offset_min: int | None = Query(None, ge=-840, le=840)):
        offset = local_offset_min() if tz_offset_min is None else tz_offset_min
        return popover.build(gw, tz_offset_min=offset)

    @api.get("/v1/shell/onboarding")
    def shell_onboarding():
        return onboarding.build(gw)

    @api.get("/v1/shell/reveal")
    def shell_reveal(scope=scope_dependency):
        from ..shell import default_scope

        return reveal.load(gw, default_scope(gw, 30, scope))

    return api
