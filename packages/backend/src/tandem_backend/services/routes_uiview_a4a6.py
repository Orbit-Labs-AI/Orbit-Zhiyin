"""``/v1/uiview/*`` presentation adapters for A4–A6 and the Lite tools/projects/mood pages.

Each ``uiview/a4a6_*`` module that exists adds its own routes (``a4a6_common.register_all``),
so later adapters need no change here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..uiview.a4a6_common import register_all

if TYPE_CHECKING:
    from .gateway import Gateway


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    register_all(api, gw)
    return api
