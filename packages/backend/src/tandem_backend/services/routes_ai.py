"""`/v1/ai` routes: engines and consent, context preview, jobs, artifacts, facets, ask and
usage. Live job progress reuses ``/v1/events?topics=job`` (``ai.job`` frames)."""

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

    def ask_module():
        try:
            from ..ai import ask
        except ImportError:
            raise ApiError(501, "not_available", "问答模块尚未安装") from None
        return ask

    def reads():
        pool = getattr(gw, "reads", None)
        return pool.read if pool is not None else None

    @api.get("/v1/ai/ask/presets")
    def ask_presets(context: str = "overview"):
        return ask_module().presets(context, reads=reads(), appdb=gw.appdb, scope=None)

    @api.post("/v1/ai/ask")
    def ask(body: AskRequest):
        if body.preset_index is not None:
            return ask_module().preset_answer(body.context, body.preset_index, reads=reads(),
                                              appdb=gw.appdb, scope=body.scope,
                                              session_uid=body.session_uid)
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

    return api
