"""`/v1` routes owned by the ai module (registered in gateway.app())."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from .gateway import Gateway


def router(gw: Gateway) -> APIRouter:
    return APIRouter()
