"""Read-only local API for the future frontend, with a separate evaluation endpoint."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
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
            data = analyze(store, project_id, model, before)
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
