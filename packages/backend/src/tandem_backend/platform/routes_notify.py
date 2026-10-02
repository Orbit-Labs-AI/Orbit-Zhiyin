"""Notification, attention-queue and collection-pause routes (included by routes_platform).

``gw.platform.notifier`` / ``gw.platform.collection`` are looked up per request, so the
router can be mounted before platform-core finishes starting; missing pieces return 503.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from ..services.auth import ApiError

STATES = {"active": "delivered", "all": None, "acked": "acked", "suppressed": "suppressed",
          "resolved": "resolved"}


class AckRequest(BaseModel):
    snooze_s: int | None = Field(default=None, gt=0, le=86400)
    mute_type: bool = False


class SnoozeRequest(BaseModel):
    seconds: int = Field(ge=60, le=86400)
    scope: str = "global"


class PauseRequest(BaseModel):
    reason: str = Field(default="user", max_length=64)


def _part(gw, name: str):
    part = getattr(getattr(gw, "platform", None), name, None)
    if part is None:
        raise ApiError(503, "service_unavailable", f"{name} is not running", retryable=True)
    return part


def router(gw) -> APIRouter:
    api = APIRouter()

    @api.get("/v1/notifications")
    def notifications(state: Literal["active", "all", "acked", "suppressed", "resolved"] = "active",
                      type: str | None = None, limit: int = Query(50, ge=1, le=200),
                      before_id: int | None = Query(None, ge=1)) -> dict:
        notifier = _part(gw, "notifier")
        try:
            items = notifier.listing(STATES[state], type or None, limit, before_id)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from None
        summary = notifier.summary()
        return {"items": items, "active_count": summary["active"],
                "urgent_count": summary["urgent"], "by_type": summary["by_type"],
                "policy_rev": notifier.policy_rev}

    @api.get("/v1/notifications/attention")
    def attention() -> dict:
        return {"items": _part(gw, "notifier").attention()}

    @api.post("/v1/notifications/ack_all")
    def ack_all() -> dict:
        return {"acked": _part(gw, "notifier").ack_all()}

    @api.get("/v1/notifications/snooze")
    def snoozes() -> dict:
        return {"items": _part(gw, "notifier").snoozes()}

    @api.post("/v1/notifications/snooze")
    def snooze(request: SnoozeRequest) -> dict:
        try:
            return _part(gw, "notifier").snooze(request.seconds, request.scope)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from None

    @api.delete("/v1/notifications/snooze")
    def unsnooze(scope: str = "global") -> dict:
        return _part(gw, "notifier").unsnooze(scope)

    @api.post("/v1/notifications/test")
    def test() -> dict:
        notifier = _part(gw, "notifier")
        id_ = notifier.emit({"type": "system", "key": "test", "title": "测试通知",
                             "body": "看到这条，说明通知工作正常。", "force": True})
        row = notifier.listing(None, None, 1, id_ + 1)[0]
        return {"id": id_, "channels": row["channels"]}

    @api.get("/v1/notifications/policy")
    def policy() -> dict:
        return _part(gw, "notifier").policy()

    @api.put("/v1/notifications/policy")
    def set_policy(patch: Annotated[dict[str, Any] | None, Body()] = None,
                   preset: Literal["quiet", "all"] | None = None) -> dict:
        try:
            return _part(gw, "notifier").set_policy(patch, preset)
        except (ValueError, TypeError, KeyError) as error:
            raise ApiError(422, "invalid_request", f"invalid policy: {error}") from None

    @api.post("/v1/notifications/{id}/ack")
    def ack(id: int, request: AckRequest | None = None) -> dict:
        request = request or AckRequest()
        try:
            return _part(gw, "notifier").ack(id, request.snooze_s, request.mute_type)
        except KeyError:
            raise ApiError(404, "not_found", f"notification {id} not found") from None

    def collection_status() -> dict:
        collection = _part(gw, "collection")
        return {**collection.status(), "intervals": collection.intervals(20)}

    def pause(request: PauseRequest | None = None) -> dict:
        return _part(gw, "collection").pause((request or PauseRequest()).reason)

    def resume() -> dict:
        return _part(gw, "collection").resume()

    for prefix in ("/v1/platform/collection", "/v1/app/collection"):
        api.add_api_route(prefix, collection_status, methods=["GET"])
        api.add_api_route(f"{prefix}/pause", pause, methods=["POST"])
        api.add_api_route(f"{prefix}/resume", resume, methods=["POST"])
    return api
