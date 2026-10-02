"""Authenticated desktop commands and paged product queries; no native log parsing."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from tandem_data.analysis_input import decoded
from tandem_data.connectors import MAPPERS
from tandem_data.inventory import read_inventory

from .analytics.cache import AnalyticsCache
from .analytics.inputs import Scope
from .api import create_app
from .app_contracts import JobResponse, SourceResponse, StorageResponse
from .application import DesktopService
from .data_access.store import CanonicalStore


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCommand(Command):
    agent: str
    root: str = Field(min_length=1, max_length=4096)
    enabled: bool = True


class JobCommand(Command):
    kind: Literal["import", "inventory", "rebuild", "verify", "backup"] = "import"
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    limit: int | None = Field(default=None, ge=1, le=10000)
    files_by_source: dict[str, list[str]] = Field(default_factory=dict)


class SettingsCommand(Command):
    onboarded: bool | None = None
    recent_days: Literal[0, 7, 30, 90] | None = None
    sync_mode: Literal["manual", "live"] | None = None


def create_desktop_app(home: Path, token: str, assets: Path) -> FastAPI:
    if len(token) < 32:
        raise ValueError("Desktop token must contain at least 32 characters")
    service = DesktopService(home)
    app = create_app(home=home)
    store, cache = CanonicalStore(home), AnalyticsCache()
    app.state.desktop = service

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        if request.url.hostname not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"error": {"code": "invalid_host"}}, status_code=403)
        if request.url.path != "/app":
            provided = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(provided, token):
                return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": {"code": "invalid_origin"}}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(ValueError)
    async def bad_request(request, error):
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": str(error), "retryable": False}},
            status_code=422,
        )

    @app.exception_handler(RuntimeError)
    async def busy(request, error):
        return JSONResponse(
            {"error": {"code": "job_conflict", "message": str(error), "retryable": True}},
            status_code=409,
        )

    @app.get("/app", response_class=HTMLResponse)
    def frontend():
        html = assets.read_text()
        # The product shell is fully offline; fonts fall back to the existing system stack.
        import re

        html = re.sub(r"<link[^>]+https://fonts.googleapis.com[^>]+>", "", html)
        return html.replace("<title>Tandem 交互 Demo</title>", "<title>Tandem</title>")

    @app.get("/v1/app/state")
    def state():
        return {
            "contract": "tandem-app-v1",
            **service.snapshot(),
            "storage": service.storage(),
            "capabilities": {
                "agents": list(MAPPERS),
                "inventory": ["codex", "claude_code"],
                "install": False,
                "generation": False,
                "personality_score": False,
            },
        }

    @app.get("/v1/app/discovery")
    def discovery():
        return {"items": service.discover()}

    @app.post("/v1/app/sources", response_model=SourceResponse)
    def source(command: SourceCommand):
        return service.configure(command.agent, command.root, command.enabled)

    @app.patch("/v1/app/settings")
    def settings(command: SettingsCommand):
        return service.settings(command.model_dump(exclude_none=True))

    @app.post("/v1/app/jobs", status_code=202, response_model=JobResponse)
    def submit(command: JobCommand):
        return service.submit(
            command.kind, command.source_ids, command.limit, command.files_by_source
        )

    @app.get("/v1/app/jobs/{job_id}", response_model=JobResponse)
    def job(job_id: str):
        value = service.snapshot()["jobs"].get(job_id)
        if value is None:
            raise HTTPException(404, "任务不存在")
        return value

    @app.post("/v1/app/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel(job_id: str):
        try:
            return service.cancel(job_id)
        except KeyError:
            raise HTTPException(404, "任务不存在") from None

    @app.post("/v1/app/jobs/{job_id}/retry", status_code=202, response_model=JobResponse)
    def retry(job_id: str):
        try:
            return service.retry(job_id)
        except KeyError:
            raise HTTPException(404, "任务不存在") from None

    @app.get("/v1/app/storage", response_model=StorageResponse)
    def storage():
        return service.storage()

    @app.get("/v1/app/inventory")
    def inventory():
        return read_inventory(home)

    def selection(agent=None, project=None, from_ts=None, until_ts=None):
        roots = None
        if agent:
            with store.connect() as db:
                roots = [
                    r[0]
                    for r in db.execute(
                        "SELECT DISTINCT root_uid FROM session JOIN source USING(source_id) WHERE agent=?",
                        (agent,),
                    )
                ]
        return Scope(
            display_timezone="Asia/Shanghai",
            project_ids=[project] if project else None,
            root_session_uids=roots,
            from_ts=from_ts,
            until_ts=until_ts,
        )

    @app.get("/v1/app/sessions")
    def sessions(
        agent: str | None = None,
        project: str | None = None,
        q: str = "",
        from_ts: int | None = None,
        until_ts: int | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        selection(agent, project, from_ts, until_ts)
        clauses, params = [], []
        for condition, value in [
            ("src.agent=?", agent),
            ("s.project_id=?", project),
            ("s.started_at>=?", from_ts),
            ("s.started_at<?", until_ts),
        ]:
            if value is not None:
                clauses.append(condition)
                params.append(value)
        if q:
            clauses.append("COALESCE(s.title,'') LIKE ?")
            params.append("%" + q + "%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        base = (
            " FROM session s JOIN source src USING(source_id) LEFT JOIN project p ON p.project_id=s.project_id"
            + where
        )
        with store.connect() as db:
            total = db.execute("SELECT COUNT(*)" + base, params).fetchone()[0]
            items = [
                dict(r)
                for r in db.execute(
                    "SELECT s.session_uid,s.kind,s.title,s.started_at,s.ended_at,s.status,s.project_id,src.agent,p.name AS project"
                    + base
                    + " ORDER BY s.started_at DESC,s.session_uid LIMIT ? OFFSET ?",
                    [*params, limit, offset],
                )
            ]
        return {
            "items": items,
            "total": total,
            "next_offset": offset + len(items) if offset + len(items) < total else None,
        }

    @app.get("/v1/app/sessions/{session_uid}/events")
    def events(
        session_uid: str, after_seq: int = Query(-1, ge=-1), limit: int = Query(100, ge=1, le=500)
    ):
        with store.connect() as db:
            if not db.execute(
                "SELECT 1 FROM session WHERE session_uid=?", (session_uid,)
            ).fetchone():
                raise HTTPException(404, "会话不存在")
            rows = [
                decoded(r)
                for r in db.execute(
                    "SELECT * FROM event WHERE session_uid=? AND seq>? ORDER BY seq LIMIT ?",
                    (session_uid, after_seq, limit),
                )
            ]
            more = bool(
                rows
                and db.execute(
                    "SELECT 1 FROM event WHERE session_uid=? AND seq>? LIMIT 1",
                    (session_uid, rows[-1]["seq"]),
                ).fetchone()
            )
        return {"items": rows, "next_after_seq": rows[-1]["seq"] if more else None}

    @app.get("/v1/app/projects")
    def projects():
        with store.connect() as db:
            return {
                "items": [
                    dict(r)
                    for r in db.execute(
                        "SELECT p.project_id,p.name,COUNT(s.session_uid) AS sessions FROM project p JOIN session s USING(project_id) GROUP BY p.project_id ORDER BY sessions DESC"
                    )
                ]
            }

    @app.get("/v1/app/analysis")
    def analysis(
        section: Literal[
            "overview",
            "preferences",
            "tasks",
            "instruction",
            "tools",
            "projects",
            "bottleneck_features",
            "recommendations",
        ] = "overview",
        agent: str | None = None,
        project: str | None = None,
        from_ts: int | None = None,
        until_ts: int | None = None,
    ):
        from .analytics.service import response_section

        data = cache.read(store, selection(agent, project, from_ts, until_ts))
        if section == "recommendations":
            from .recommend.service import recommend

            data[section] = recommend(data)
        return response_section(data, section)

    @app.get("/v1/app/export")
    def export(
        agent: str | None = None,
        project: str | None = None,
        from_ts: int | None = None,
        until_ts: int | None = None,
    ):
        data = cache.read(store, selection(agent, project, from_ts, until_ts))
        # Export the selected, redacted analysis, never raw archives or discovery paths.
        data.pop("sample_boundary", None)
        return JSONResponse(
            data, headers={"Content-Disposition": 'attachment; filename="tandem-analysis.json"'}
        )

    return app
