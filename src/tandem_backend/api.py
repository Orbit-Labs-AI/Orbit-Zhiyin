"""Read-only local API for the future frontend, with a separate evaluation endpoint."""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__
from .analysis import analyze
from .catalog import resources
from .evaluation import SCENE_BUDGETS, evaluate_text
from .narrative import explain
from .recommend import recommend
from .recommend.contracts import Family, RecommendationContext
from .store import Store


class EvaluationRequest(BaseModel):
    text: str = Field(max_length=50_000)
    scene: str = "developer_report"
    required_facts: list[str] = Field(default_factory=list, max_length=50)


class RecommendationRequest(BaseModel):
    context: RecommendationContext = Field(default_factory=RecommendationContext)
    family: Family | None = None
    limit: int = Field(default=6, ge=1, le=20, strict=True)


def create_app(db: str | Path | None = None, catalog_cache: str | Path = ".local/catalog.json",
               recommendation_catalog: str | Path | None = None, *, home: str | Path | None = None) -> FastAPI:
    from tandem_data.paths import default_home

    from .data_access.store import CanonicalStore
    store = Store(db) if db is not None else CanonicalStore(home if home is not None else default_home())
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

    @app.get("/v1/analytics/bottleneck")
    def feature_bottleneck(scope=scope_dependency):
        return analytics_section("bottleneck_features", scope)

    @app.get("/v1/analytics/recommendations")
    def feature_recommendations(
        scope=scope_dependency, target_agent: Literal["generic", "codex", "claude_code"] = "generic",
        kind: Literal["skill", "agent", "hook", "prompt"] | None = None, limit: int = Query(6, ge=1, le=20),
        family: Family | None = None,
    ):
        from .analytics.service import response_section
        from .recommend.service import recommend as recommend_resources

        result = analytics_data(scope, False)
        result["bottleneck_recommendations"] = recommend_resources(result, context={"agent": target_agent}, kind=kind,
                                                                   limit=limit, family=family, catalog_directory=recommendation_catalog)
        return response_section(result, "bottleneck_recommendations")

    @app.post("/v1/analytics/recommendations")
    def contextual_recommendations(request: RecommendationRequest, scope=scope_dependency):
        from .analytics.service import response_section
        from .recommend.service import recommend as recommend_resources

        result = analytics_data(scope, False)
        result["bottleneck_recommendations"] = recommend_resources(
            result, context=request.context, family=request.family, limit=request.limit,
            catalog_directory=recommendation_catalog)
        return response_section(result, "bottleneck_recommendations")

    @app.get("/v1/analytics/sessions")
    def feature_sessions(scope=scope_dependency, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        result = analytics_section("sessions", scope)
        result["total"] = len(result["sessions"])
        fields = ("session_uid", "kind", "project_id", "legacy_project_id", "title", "features",
                  "cluster_id", "novelty", "embedding_x", "embedding_y", "effective_samples", "unknown_counts")
        result["sessions"] = [{**{k: s.get(k) for k in fields}, "usage": {
            k: s["usage"][k] for k in ("status", "request_count", "total_tokens", "cost_usd")}}
            for s in result["sessions"][offset:offset + limit]]
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

    @app.get("/v1/analytics/instruction")
    def feature_instruction(scope=scope_dependency):
        return analytics_section("instruction", scope)

    @app.get("/v1/analytics/text")
    def feature_text(scope=scope_dependency):
        return analytics_section("text", scope)

    @app.get("/v1/analytics/tasks")
    def feature_tasks(scope=scope_dependency):
        return analytics_section("tasks", scope)

    @app.get("/v1/analytics/preferences")
    def feature_preferences(scope=scope_dependency, task_id: str | None = None):
        from .analytics.preference import resolve_effective_preferences
        from .analytics.service import response_section
        data = analytics_data(scope, with_text=False)
        task = None
        if task_id is not None:
            task = next((t for t in data["tasks"]["records"] or [] if t["task_id"] == task_id), None)
            if task is None:
                raise HTTPException(404, "任务不在本次分析范围内")
        result = response_section(data, "preferences")
        result["preferences"]["effective"] = resolve_effective_preferences(
            data["preferences"]["records"], task, at=scope.until_ts - 1 if scope.until_ts is not None else None)
        return result

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "counts": store.counts()}

    @app.get("/v1/projects")
    def projects():
        return analyze(store)["projects"]

    @app.get("/v1/sessions")
    def sessions(project_id: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        # Paths stay in the local ledger; listing sessions does not expose home-directory paths.
        items = (store.session_page(project_id, offset=offset, limit=limit)["items"]
                 if hasattr(store, "session_page") else store.sessions(project_id)[offset:offset + limit])
        return [{k: s[k] for k in ("id", "title", "project_id", "project", "model", "started_at")}
                for s in items]

    @app.get("/v1/sessions/{session_id}/events")
    def events(session_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500), after_seq: int | None = Query(None, ge=-1)):
        if hasattr(store, "event_page"):
            page = store.event_page(session_id, offset=offset, after_seq=after_seq, limit=limit)
            if page is None:
                raise HTTPException(404, "会话不存在或不在分析范围内")
            return page
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
        if hasattr(store, "evidence"):
            item = store.evidence(event_id)
            if item is None:
                raise HTTPException(404, "证据不存在或不在分析范围内")
            return item
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
