"""`/v1/export/*` (FE-19 / AN-14 / EXP-01..05 / MB-06): CSV tables, report, snapshots and
the share-card payload. Thin handlers over ``tandem_backend.exporting``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..exporting import csv_export, report, sharecard, snapshots
from ..exporting.tables import SCOPE_FILTERS, TABLES, describe, header
from ..sessionops.exclusion import excluded_uids
from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway

SHARE_WINDOW_DAYS = 30


class ReportRequest(BaseModel):
    sections: list[str] = Field(default_factory=lambda: list(report.DEFAULT_SECTIONS))
    scope: dict = Field(default_factory=dict)
    format: Literal["markdown", "json"] = "markdown"
    save: bool = True


class ShareCardRequest(BaseModel):
    scope: dict | None = None  # only display_timezone is read; the window is ``period``
    period: str = str(SHARE_WINDOW_DAYS)
    agents: list[str] | None = None
    project: str | None = None
    hide_numbers: bool = False
    theme: Literal["light", "dark", "system"] = "system"
    save: bool = True


def _scope(raw: dict) -> dict:
    try:
        return report.build_scope(raw)
    except (ValueError, TypeError) as error:  # analytics_scope raises ApiError itself
        raise ApiError(422, "invalid_request", str(error)) from error


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()

    @api.get("/v1/export/tables")
    def tables():
        return {"tables": [describe(t, csv_export.approx_rows(gw.reads.path, t))
                           for t in TABLES.values()]}

    @api.get("/v1/export/csv")
    def export_csv(request: Request, table: str,
                   project_id: Annotated[list[str] | None, Query()] = None,
                   agent: Annotated[list[str] | None, Query()] = None,
                   from_ts: int | None = None, until_ts: int | None = None,
                   limit: int = Query(100_000, ge=1, le=1_000_000),
                   include_excluded: bool = False):
        spec = TABLES.get(table)
        if spec is None:
            raise ApiError(422, "invalid_request", f"Unknown table {table!r}")
        unknown = set(request.query_params) - {"table", *SCOPE_FILTERS}
        if unknown:
            raise ApiError(422, "invalid_request", f"Unknown filters: {sorted(unknown)}")
        excluded = [] if include_excluded else excluded_uids(gw.appdb)
        sql, params = csv_export.query(spec, project_ids=project_id or [], agents=agent or [],
                                       from_ts=from_ts, until_ts=until_ts, excluded=excluded,
                                       limit=limit)
        try:
            connection = csv_export.open_snapshot(gw.reads.path)
        except csv_export.ExportError as error:
            raise ApiError(error.status, error.code, error.message, retryable=True,
                           retry_after=2) from error
        day = datetime.now(UTC).strftime("%Y%m%d")
        return StreamingResponse(
            csv_export.stream(connection, spec, sql, params, header(spec)),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="tandem-{table}-{day}.csv"'})

    @api.post("/v1/export/report")
    def export_report(body: ReportRequest):
        unknown = [s for s in body.sections if s not in report.SECTION_IDS]
        if unknown or not body.sections:
            raise ApiError(422, "invalid_request", f"Unknown sections: {unknown}")
        scope = _scope(body.scope)
        result = report.assemble(gw, list(dict.fromkeys(body.sections)), scope)
        result["format"] = body.format
        if body.format == "markdown":
            result["markdown"] = report.document(result)
        result["snapshot_id"] = None
        if body.save:
            from .sections import rules_digest

            result["snapshot_id"] = snapshots.save(gw.appdb, "report", scope,
                                                   result["scope_hash"], result, rules_digest())
        return result

    @api.get("/v1/export/snapshots")
    def list_snapshots(kind: str | None = None, limit: int = Query(20, ge=1, le=100)):
        if kind is not None and kind not in snapshots.KINDS:
            raise ApiError(422, "invalid_request", f"Unknown kind {kind!r}")
        return {"items": snapshots.list_(gw.appdb, kind, limit)}

    @api.get("/v1/export/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str):
        row = snapshots.get(gw.appdb, snapshot_id)
        if row is None:
            raise ApiError(404, "not_found", "Unknown snapshot")
        return row

    @api.delete("/v1/export/snapshots/{snapshot_id}")
    def delete_snapshot(snapshot_id: str):
        if not snapshots.delete(gw.appdb, snapshot_id):
            raise ApiError(404, "not_found", "Unknown snapshot")
        return {"ok": True}

    @api.post("/v1/export/share_card")
    def share_card(body: ShareCardRequest):
        from ..uiview import fetch, overview

        tz = (body.scope or {}).get("display_timezone")
        scope = fetch.default_scope(tz)
        params = {"period": body.period, "agents": body.agents or None,
                  "project": body.project or None, "vs": None}
        try:
            page, freshness, _ = fetch.persona_page(gw, scope, params, overview.today_in(tz),
                                                    wait_ms=3000)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from error
        result = sharecard.payload(page, hide_numbers=body.hide_numbers, theme=body.theme)
        h = (page or {}).get("meta", {}).get("scope_hash")
        result["scope_hash"] = h
        if freshness == "computing":
            result["freshness"] = "computing"
        if result["eligible"] and body.save:
            from .sections import rules_digest

            result["snapshot_id"] = snapshots.save(gw.appdb, "share_card", scope, h, result,
                                                   rules_digest())
        return result

    return api
