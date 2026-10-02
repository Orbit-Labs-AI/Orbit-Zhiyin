"""Application lifecycle under ``/v1/app`` (paths and fields follow docs/backend/mac-app.md
of feat/data-app-integration): state, discovery, sources, settings, jobs, storage, plus
the SSE stream ``/v1/events``."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .auth import ApiError
from .events import TOPICS
from .jobs import JobConflict

if TYPE_CHECKING:
    from .gateway import Gateway

STORAGE_TABLES = ("source", "source_file", "source_revision", "raw_record", "event", "session",
                  "turn", "tool_call", "model_call", "archive_blob")


class SourceRequest(BaseModel):
    agent: str
    root: str
    enabled: bool = True


class JobRequest(BaseModel):
    kind: Literal["import", "inventory", "rebuild", "verify", "backup"]
    source_ids: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1)
    files_by_source: dict[str, list[str]] = Field(default_factory=dict)
    phase: Literal["auto", "full", "head", "window", "rest"] | None = None


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()

    def job_or_404(job_id: str) -> dict:
        try:
            return gw.state.job(job_id)
        except KeyError:
            raise ApiError(404, "not_found", "任务不存在") from None

    @api.get("/v1/app/state")
    def app_state():
        state = gw.state.snapshot()
        return {"sources": list(state["sources"].values()), "settings": state["settings"],
                "jobs": gw.state.jobs()[:50], "storage": gw.revisions.snapshot(),
                "services": gw.supervisor.services(),
                "capabilities": {"sse": True, "phased_import": True, "export": False,
                                 "sync_modes": ["off", "live"]}}

    @api.get("/v1/app/discovery")
    def discovery():
        """Lists candidate roots and counts allowlisted files by name; never reads bodies."""
        from tandem_data.contract import uid
        from tandem_data.discovery import inputs

        configured = gw.state.snapshot()["sources"]
        roots = {(s["agent"], s["root"]) for s in [*gw.discovery(), *configured.values()]}
        result = []
        for agent, root in sorted(roots):
            key = uid("source", agent, root)
            try:
                files = sum(1 for item in inputs(agent, Path(root))
                            if item.role in ("transcript", "subagent_transcript"))
                status = "available" if files else "empty"
            except (OSError, ValueError):
                files, status = None, "permission_denied"
            result.append({"id": key, "agent": agent, "root": root, "files": files,
                           "status": status,
                           "enabled": configured.get(key, {}).get("enabled", False)})
        return result

    @api.post("/v1/app/sources")
    def configure(request: SourceRequest):
        try:
            return gw.state.configure(request.agent, request.root, request.enabled, gw.home)
        except (ValueError, OSError) as error:
            raise ApiError(422, "invalid_request", str(error)) from error

    @api.patch("/v1/app/settings")
    def settings(values: dict[str, Any]):
        try:
            return gw.state.update_settings(values)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from error

    @api.get("/v1/app/jobs")
    def jobs(limit: int = Query(50, ge=1, le=100)):
        return gw.state.jobs()[:limit]

    @api.post("/v1/app/jobs", status_code=202)
    def submit(request: JobRequest):
        if request.kind in ("import", "inventory", "rebuild"):
            gw.supervisor.ingest.worker.reset()  # A user action retries a degraded worker.
        try:
            return gw.jobs.submit(request.kind, request.source_ids, request.limit,
                                  request.files_by_source, request.phase)
        except JobConflict as error:
            raise ApiError(409, "job_conflict", str(error), retryable=True) from error
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from error

    @api.get("/v1/app/jobs/{job_id}")
    def job(job_id: str):
        return job_or_404(job_id)

    @api.post("/v1/app/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        job_or_404(job_id)
        return gw.jobs.cancel(job_id)

    @api.post("/v1/app/jobs/{job_id}/retry", status_code=202)
    def retry(job_id: str):
        job_or_404(job_id)
        gw.supervisor.ingest.worker.reset()
        try:
            return gw.jobs.retry(job_id)
        except JobConflict as error:
            raise ApiError(409, "job_conflict", str(error), retryable=True) from error
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from error

    @api.get("/v1/app/storage")
    def storage():
        """Readable even when the projection needs rebuilding."""
        from tandem_data.query import current_projection

        path = gw.home / "tandem.db"
        if not path.is_file():
            return {"readiness": "absent", "projection_run_id": None, "schema_version": None,
                    "tables": {}, "sources": [], "archive_bytes": 0, "database_bytes": 0,
                    "home": str(gw.home)}
        with gw.reads.read(check=False) as db:
            try:
                _, run = current_projection(db)
                readiness, revision = "ready", run["run_id"]
            except (ValueError, sqlite3.Error):
                readiness, revision = "rebuild_required", None
            return {
                "readiness": readiness, "projection_run_id": revision,
                "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
                "tables": {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                           for t in STORAGE_TABLES},
                "sources": [dict(r) for r in db.execute(
                    "SELECT s.source_id,s.agent,COUNT(t.session_uid) AS sessions FROM source s"
                    " LEFT JOIN session t USING(source_id) GROUP BY s.source_id")],
                "archive_bytes": db.execute("SELECT COALESCE(SUM(stored_len),0) FROM archive_blob"
                                            ).fetchone()[0],
                "database_bytes": path.stat().st_size, "home": str(gw.home)}

    @api.get("/v1/events")
    async def events(topics: str = "job,data,analysis,service,notify",
                     last_event_id: str | None = Header(None)):
        wanted = {t.strip() for t in topics.split(",") if t.strip()}
        if not wanted or wanted - TOPICS:
            raise ApiError(422, "invalid_request", f"topics must be within {sorted(TOPICS)}")
        try:
            cursor = int(last_event_id) if last_event_id else None
        except ValueError:
            raise ApiError(422, "invalid_request", "Last-Event-ID must be an integer") from None
        return StreamingResponse(gw.bus.stream(cursor, wanted), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    return api
