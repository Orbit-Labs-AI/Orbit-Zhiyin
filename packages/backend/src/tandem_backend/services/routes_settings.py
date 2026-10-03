"""Settings-page backends: redaction rules (SET-10), data lifecycle (SET-12), about (SET-13),
tool map (SET-11), plus the artifact adapters (A9-17/A9-18).

Endpoints: ``GET|PUT /v1/privacy/rules``, ``POST /v1/privacy/preview``, ``GET /v1/app/data``,
``POST /v1/app/data/clear``, ``GET /v1/app/about``, ``GET /v1/app/tool_map``,
``POST /v1/ai/artifacts/{id}/materialize`` and ``POST /v1/ai/artifacts/{id}/to_library``.
The router also installs the source-visibility provider used by analytics scopes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway


class RulesPut(BaseModel):
    enabled: dict[str, bool] = Field(default_factory=dict)
    custom: list[dict[str, Any]] | None = None


class PreviewBody(BaseModel):
    text: str = Field(max_length=20_000)
    enabled: dict[str, bool] | None = None
    custom: list[dict[str, Any]] | None = None


class ClearBody(BaseModel):
    confirm: str
    cancel_jobs: bool = False


def router(gw: Gateway) -> APIRouter:
    from .. import privacy_rules
    from ..appdata import about, sources_scope, toolmap, wipe

    api = APIRouter()
    privacy_rules.bind(gw.platform.settings)
    sources_scope.set_provider(lambda: list(gw.state.snapshot()["sources"].values()))

    def rule_error(error: privacy_rules.RuleError) -> ApiError:
        return ApiError(422, error.code, str(error))

    # -- redaction rules ---------------------------------------------------------------
    @api.get("/v1/privacy/rules")
    def get_rules():
        return privacy_rules.describe()

    @api.put("/v1/privacy/rules")
    def put_rules(body: RulesPut):
        try:
            config = privacy_rules.merge(privacy_rules.current(), body.enabled, body.custom)
        except privacy_rules.RuleError as error:
            raise rule_error(error) from None
        privacy_rules.save(config)
        return privacy_rules.describe(config)

    @api.post("/v1/privacy/preview")
    def preview(body: PreviewBody):
        """Applies the proposed (unsaved) rules to ``text``; nothing is stored or logged."""
        try:
            config = privacy_rules.merge(privacy_rules.current(), body.enabled, body.custom)
        except privacy_rules.RuleError as error:
            raise rule_error(error) from None
        return privacy_rules.preview(body.text, config)

    # -- data lifecycle ----------------------------------------------------------------
    @api.get("/v1/app/data")
    def data():
        return wipe.describe(gw.home, gw.appdb, gw.state)

    @api.post("/v1/app/data/clear", status_code=202)
    def clear(body: ClearBody):
        if body.confirm != wipe.CONFIRM_WORD:
            raise ApiError(422, "invalid_request", f"请输入「{wipe.CONFIRM_WORD}」确认")
        active = gw.state.active_job()
        if active is not None:
            if not body.cancel_jobs:
                raise ApiError(409, "job_active", "有任务正在进行，先取消或等待完成", retryable=True)
            gw.jobs.cancel(active["id"])
        return wipe.mark(gw.home)

    @api.post("/v1/storage/purge")
    def legacy_purge():
        # The legacy app's purge deletes tandem.db behind the gateway's back (open read
        # pool, revisions, snapshot cache, running jobs). Shadow it: clearing goes through
        # /v1/app/data/clear, which cancels jobs and wipes on restart.
        raise ApiError(404, "not_found", "请改用 POST /v1/app/data/clear 清除数据")

    # -- descriptive -------------------------------------------------------------------
    @api.get("/v1/app/about")
    def app_about():
        return about.about()

    @api.get("/v1/app/tool_map")
    def tool_map():
        reads = gw.reads if (gw.home / "tandem.db").is_file() else None
        return toolmap.tool_map(reads)

    # -- artifact adapters -------------------------------------------------------------
    def artifact(artifact_id: str) -> dict:
        from ..ai.errors import AIError
        from ..ai.service import service

        try:
            return service(gw).artifact(artifact_id)
        except AIError as error:
            raise ApiError(error.status, error.code, error.message) from None

    def adapt(fn, *args):
        from ..ai.errors import AIError

        try:
            return fn(*args)
        except AIError as error:
            raise ApiError(error.status, error.code, error.message) from None

    @api.post("/v1/ai/artifacts/{artifact_id}/materialize")
    def materialize(artifact_id: str):
        from ..ai import artifact_ops

        return adapt(artifact_ops.materialize, artifact(artifact_id), gw.home)

    @api.post("/v1/ai/artifacts/{artifact_id}/to_library", status_code=201)
    def to_library(artifact_id: str):
        from tandem_catalog import get_service

        from ..ai import artifact_ops

        catalog = get_service(gw.home / "catalog.db")
        try:
            return adapt(artifact_ops.to_library, artifact(artifact_id), catalog)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from None

    return api
