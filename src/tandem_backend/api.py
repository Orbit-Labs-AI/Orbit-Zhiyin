"""Read-only local API for the future frontend, with a separate evaluation endpoint."""

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__
from .analysis import analyze
from .catalog import resources
from .evaluation import SCENE_BUDGETS, evaluate_text
from .narrative import explain
from .recommend import recommend
from .store import Store


class EvaluationRequest(BaseModel):
    text: str = Field(max_length=50_000)
    scene: str = "developer_report"
    required_facts: list[str] = Field(default_factory=list, max_length=50)


def create_app(db: str | Path = ".local/tandem.sqlite", catalog_cache: str | Path = ".local/catalog.json") -> FastAPI:
    store = Store(db)
    app = FastAPI(title="Tandem 本地轨迹分析", version=__version__)

    def analytics_scope(
        display_timezone: str = "UTC", project_ids: Annotated[list[str] | None, Query()] = None,
        legacy_project_ids: Annotated[list[str] | None, Query()] = None, model_ids: Annotated[list[str] | None, Query()] = None,
        effort_raw: Annotated[list[str] | None, Query()] = None, from_ts: int | None = None, until_ts: int | None = None,
        root_session_uids: Annotated[list[str] | None, Query()] = None, excluded_session_uids: Annotated[list[str] | None, Query()] = None,
        include_children: bool = True, scene: str | None = None,
    ):
        from .analytics.inputs import Scope
        try:
            # Repeated parameters are lists; an explicit empty value means [].
            return Scope(display_timezone=display_timezone,
                         project_ids=[] if project_ids == [""] else project_ids,
                         legacy_project_ids=[] if legacy_project_ids == [""] else legacy_project_ids,
                         model_ids=[] if model_ids == [""] else model_ids, effort_raw=effort_raw,
                         from_ts=from_ts, until_ts=until_ts,
                         root_session_uids=[] if root_session_uids == [""] else root_session_uids,
                         excluded_session_uids=excluded_session_uids or [], include_children=include_children, scene=scene)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    scope_dependency = Depends(analytics_scope)

    def analytics_data(scope, with_text=True):
        from .analytics.service import analyze_store
        try:
            return analyze_store(store, scope, with_text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def analytics_section(key, scope):
        from .analytics.service import response_section
        return response_section(analytics_data(scope, key in ("sessions", "text", "projects")), key)

    @app.get("/v1/analytics/overview")
    def feature_overview(scope=scope_dependency):
        return analytics_section("overview", scope)

    @app.get("/v1/analytics/sessions")
    def feature_sessions(scope=scope_dependency, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        result = analytics_section("sessions", scope)
        result["total"] = len(result["sessions"])
        result["sessions"] = result["sessions"][offset:offset + limit]
        return result

    @app.get("/v1/analytics/sessions/{session_id}")
    def feature_session(session_id: str, scope=scope_dependency):
        result = analytics_section("sessions", scope)
        row = next((s for s in result.pop("sessions") if s["session_uid"] == session_id), None)
        if row is None:
            raise HTTPException(404, "会话不在本次分析范围内")
        return {**result, "session": row}

    @app.get("/v1/analytics/tools")
    def feature_tools(scope=scope_dependency):
        return analytics_section("tools", scope)

    @app.get("/v1/analytics/projects")
    def feature_projects(scope=scope_dependency):
        return analytics_section("projects", scope)

    @app.get("/v1/analytics/text")
    def feature_text(scope=scope_dependency):
        return analytics_section("text", scope)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "counts": store.counts()}

    @app.get("/v1/projects")
    def projects():
        return analyze(store)["projects"]

    @app.get("/v1/sessions")
    def sessions(project_id: str | None = None, limit: int = Query(50, ge=1, le=200)):
        # Paths stay in the local ledger; listing sessions does not expose home-directory paths.
        return [{k: s[k] for k in ("id", "title", "project_id", "project", "model", "started_at")}
                for s in store.sessions(project_id)[:limit]]

    @app.get("/v1/sessions/{session_id}/events")
    def events(session_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        items = store.events(session_id=session_id)
        if not any(s["id"] == session_id for s in store.sessions()):
            raise HTTPException(404, "会话不存在")
        return {"total": len(items), "items": [e.to_dict() for e in items[offset:offset + limit]]}

    @app.get("/v1/analysis")
    def analysis(project_id: str | None = None, model: str | None = None, before: str | None = None,
                 audience: str = "user", scene: str = "auto"):
        try:
            data = analyze(store, project_id, model, before, scene if scene != "auto" else None)
            return explain(data, recommend(data, scene, catalog=resources(catalog_cache)), audience)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/v1/catalog")
    def catalog():
        return resources(catalog_cache)

    @app.get("/v1/evidence/{event_id}")
    def evidence(event_id: str):
        with store.connect() as conn:
            row = conn.execute("SELECT data FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "证据不存在")
        import json
        return json.loads(row[0])

    @app.post("/v1/evaluation")
    def evaluation(request: EvaluationRequest):
        if request.scene not in SCENE_BUDGETS:
            raise HTTPException(422, "未知的评价场景")
        return evaluate_text(request.text, request.scene, request.required_facts)

    return app
