"""`/v1/ai` routes: engines and consent, context preview, jobs, artifacts, facets, ask and
usage, artifact materialize / to_library (A9-17/A9-18). Live job progress reuses
``/v1/events?topics=job`` (``ai.job`` frames)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway

GoalSource = Literal["candidate", "phrases", "project", "workflow", "ask", "manual"]


class AIApiError(ApiError):
    """ApiError whose body also carries structured details (e.g. ``missing``, ``reason``)."""

    def __init__(self, status: int, code: str, message: str, extra: dict):
        super().__init__(status, code, message, retryable=status in (409, 503))
        self.extra = extra

    def payload(self) -> dict:
        body = super().payload()
        body["error"].update(self.extra)
        return body


class Selection(BaseModel):
    items: dict[str, bool] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    task_id: str
    engine: str | None = None
    scope: dict | None = None
    selection: Selection | None = None
    goal: str | None = None
    goal_source: GoalSource | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    slots: dict[str, Any] | None = None


class JobRequest(PreviewRequest):
    template: Literal["v1", "quick", "strict"] = "v1"
    preview_digest: str | None = None
    override: bool = False
    # 「重新生成」: skip the result cache for this job (a new model call; the new output
    # replaces the cached one). Default False keeps identical requests free.
    fresh: bool = False


class ConsentPatch(BaseModel):
    mode: Literal["stats", "agent", "api"] | None = None
    default_engine: str | None = None
    grants: dict[str, dict[str, bool]] | None = None
    settings: dict[str, Any] | None = None


class ArtifactPatch(BaseModel):
    status: Literal["draft", "archived"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)


class AskRequest(BaseModel):
    context: str
    preset_index: int | None = Field(default=None, ge=0)
    question: str | None = Field(default=None, min_length=1, max_length=500)
    scope: dict | None = None
    session_uid: str | None = None
    engine: str | None = None


def router(gw: Gateway) -> APIRouter:
    from ..ai.errors import AIError
    from ..ai.service import service

    api = APIRouter()

    def call(fn: Callable, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AIError as error:
            raise AIApiError(error.status, error.code, error.message, error.extra) from None

    def ai():
        return service(gw)

    @api.get("/v1/ai/engines")
    def engines(refresh: bool = False):
        return call(ai().engines, refresh)

    @api.get("/v1/ai/consent")
    def consent():
        return ai().consent()

    @api.put("/v1/ai/consent")
    def set_consent(body: ConsentPatch):
        return call(ai().set_consent, body.model_dump(exclude_unset=True))

    @api.post("/v1/ai/preview")
    def preview(body: PreviewRequest):
        return call(ai().preview, body.task_id, body.model_dump(exclude_none=True))

    @api.post("/v1/ai/jobs", status_code=202)
    def submit(body: JobRequest):
        return call(ai().submit, body.task_id, body.model_dump(exclude_none=True))

    @api.get("/v1/ai/jobs")
    def jobs(limit: int = Query(50, ge=1, le=500)):
        return ai().jobs(limit)

    @api.get("/v1/ai/jobs/{job_id}")
    def job(job_id: str):
        return call(ai().job, job_id)

    @api.post("/v1/ai/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return call(ai().cancel, job_id)

    @api.get("/v1/ai/artifacts")
    def artifacts(kind: str | None = None, status: str | None = None,
                  limit: int = Query(50, ge=1, le=500)):
        return ai().artifacts(kind, status, limit)

    @api.get("/v1/ai/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        return call(ai().artifact, artifact_id)

    @api.patch("/v1/ai/artifacts/{artifact_id}")
    def patch_artifact(artifact_id: str, body: ArtifactPatch):
        return call(ai().set_artifact_status, artifact_id, status=body.status, name=body.name)

    @api.get("/v1/ai/facets")
    def facets(session_uid: Annotated[list[str] | None, Query()] = None):
        return ai().facets(session_uid or [])

    @api.get("/v1/ai/narratives")
    def narratives(kind: str, key: str | None = None, session_uid: str | None = None,
                   days: int | None = Query(None, ge=1, le=365), project_id: str | None = None):
        params = {"session_uid": session_uid} if session_uid else {}
        scope = {k: v for k, v in (("days", days), ("project_id", project_id)) if v} or None
        return call(ai().narrative, kind, key or session_uid, params, scope)

    def ask_module():
        from ..ai import ask  # Lazy: keeps jieba & co. out of gateway start-up.

        return ask

    def reads():
        pool = getattr(gw, "reads", None)
        return pool.read if pool is not None else None

    @api.get("/v1/ai/ask/presets")
    def ask_presets(context: str = "overview", session_uid: str | None = None):
        return call(ask_module().presets, context, reads=reads(), appdb=gw.appdb, scope=None,
                    session_uid=session_uid, home=gw.home)

    @api.post("/v1/ai/ask")
    def ask(body: AskRequest):
        if body.preset_index is not None:
            return call(ask_module().preset_answer, body.context, body.preset_index, reads=reads(),
                        appdb=gw.appdb, scope=body.scope, session_uid=body.session_uid, home=gw.home)
        if not body.question:
            raise ApiError(422, "invalid_request", "需要 preset_index 或 question")
        req = {"engine": body.engine, "scope": body.scope, "goal": body.question,
               "goal_source": "ask",
               "params": {"question": body.question, "context": body.context,
                          "session_uid": body.session_uid}}
        submitted = call(ai().submit, "ask.question", req)
        return {"job_id": submitted["job_id"], "status": submitted["status"],
                "cached": submitted["cached"]}

    @api.get("/v1/ai/usage")
    def usage(days: int = Query(30, ge=1, le=365)):
        return ai().usage(days)

    # -- artifact adapters -------------------------------------------------------------
    # Errors map to plain ApiError (no ``extra``), as before the move from routes_settings.
    def stored_artifact(artifact_id: str) -> dict:
        try:
            return service(gw).artifact(artifact_id)
        except AIError as error:
            raise ApiError(error.status, error.code, error.message) from None

    def adapt(fn, *args):
        try:
            return fn(*args)
        except AIError as error:
            raise ApiError(error.status, error.code, error.message) from None

    @api.post("/v1/ai/artifacts/{artifact_id}/materialize")
    def materialize(artifact_id: str):
        from ..ai import artifact_ops

        return adapt(artifact_ops.materialize, stored_artifact(artifact_id), gw.home)

    @api.post("/v1/ai/artifacts/{artifact_id}/to_library", status_code=201)
    def to_library(artifact_id: str):
        from orbit_catalog import get_service

        from ..ai import artifact_ops

        catalog = get_service(gw.home / "catalog.db")
        try:
            return adapt(artifact_ops.to_library, stored_artifact(artifact_id), catalog)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from None

    return api
