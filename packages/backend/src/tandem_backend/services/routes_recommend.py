"""`/v1` routes owned by the recommend module (registered in gateway.app()).

Thin handlers: runs are reused or rebuilt by ``recommend.runs``; all SQL lives in
``recommend.store`` / ``recommend.outcomes``. Cards carry a ``ui`` object shaped like the
A7 prototype's RECS rows so the page can bind directly.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..recommend import outcomes, runs, store
from .auth import ApiError
from .routes_analytics import analytics_scope
from .snapshots import scope_hash

if TYPE_CHECKING:
    from .gateway import Gateway

Surface = Literal["A7", "A1", "lite", "menubar", "widget", "palette", "ask", "hud"]
Action = Literal["view", "open", "preview", "copy", "install", "dismiss", "snooze"]
SURFACE_LIMIT = {"A7": 30, "A1": 3, "lite": 3, "menubar": 1}
TOP_SURFACES = ("A1", "lite", "menubar")
TOP_TTL_MS = store.DAY
DIMS = (("all", "全部"), ("rule", "规则与 Prompt"), ("skill", "Skills"), ("hook", "Hooks"),
        ("mcp", "插件 / MCP"), ("agent", "子代理"), ("model", "模型与思考"),
        ("flow", "工作流 / 架构"))


class RecomputeRequest(BaseModel):
    scope: dict = Field(default_factory=dict)
    force: bool = False


class ExposureRequest(BaseModel):
    surface: Surface
    position: int | None = None
    action: Action = "view"


class ExposureItem(BaseModel):
    candidate_id: str
    position: int | None = None
    action: Action = "view"


class ExposureBatch(BaseModel):
    surface: Surface
    items: list[ExposureItem] = Field(min_length=1, max_length=50)


class TrackingRequest(BaseModel):
    install_id: str = Field(min_length=1, max_length=200)
    installed_at: int | None = None


class SettingsRequest(BaseModel):
    ai_generate: bool | None = None
    level: int | None = Field(None, ge=1, le=4)


class LabelRequest(BaseModel):
    target_kind: Literal["candidate", "problem", "profile", "signal", "key_moment", "facet",
                         "narrative", "reader_case"]
    target_id: str = Field(min_length=1, max_length=500)
    label: Literal["not_applicable", "snooze", "useful", "not_useful", "not_me", "inaccurate",
                   "confirm", "mute"]
    reason: Literal["has_equivalent", "dont_want", "wrong_diagnosis", "env_mismatch", "other",
                    "never_triggered", "reverted"] | None = None


def _scope_from_body(scope: dict):
    allowed = set(analytics_scope.__code__.co_varnames[:analytics_scope.__code__.co_argcount])
    unknown = set(scope) - allowed
    if unknown:
        raise ApiError(422, "invalid_request", f"Unknown scope keys: {sorted(unknown)}")
    return analytics_scope(**scope)


def _run_meta(run: dict, freshness: str) -> dict:
    return {k: run.get(k) for k in ("run_id", "status", "created_at", "engine_version",
                                    "kb_version", "inputs_digest")} | {"freshness": freshness}


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    scope_dependency = Depends(analytics_scope)

    @api.get("/v1/recommendations")
    def recommendations(scope=scope_dependency, dim: str | None = None,
                        level: int | None = Query(None, ge=1, le=4),
                        audience: Literal["0", "1", "2", "all"] = "all",
                        surface: Surface = "A7", limit: int | None = Query(None, ge=1, le=50),
                        include_gated: bool = False, wait_ms: int = Query(0, ge=0, le=3000)):
        scope_dict = asdict(scope)
        h = scope_hash(scope_dict, {})
        result = runs.run(gw, scope_dict, wait_ms=wait_ms)
        meta = {"scope_hash": h, "freshness": result["freshness"], "job_id": result["job_id"]}
        with gw.appdb.read() as conn:
            run = (store.get_run(conn, result["run_id"]) if result["run_id"]
                   else store.latest_run(conn, h))
        if run is None:
            body = {"run": None, "items": [], "dims": _dims({}), "problems": [], "meta": meta}
            if result["freshness"] == "none":
                return JSONResponse(body)
            return JSONResponse({"meta": {**meta, "freshness": "computing"}}, status_code=202)
        freshness = result["freshness"] if result["run_id"] else "stale"
        meta["freshness"] = freshness
        now = runs.now_ms()
        limit = limit or SURFACE_LIMIT.get(surface, 30)
        aud = None if audience == "all" else int(audience)
        with gw.appdb.read() as conn:
            items = store.candidates(conn, run["run_id"], level=level, audience=aud, limit=50)
            states = store.states(conn, [c["rec_key"] for c in items])
            items = [c for c in items if store.visible(states.get(c["rec_key"]), now)]
            items = store.apply_decay(items, states)
            gated = (store.candidates(conn, run["run_id"], passed=False, limit=50)
                     if include_gated else None)
        counts: dict[str, int] = {}
        for item in items:
            counts[item.get("dim")] = counts.get(item.get("dim"), 0) + 1
        if surface in TOP_SURFACES:
            items = _top(surface, h, run, items, limit, now)
        else:
            items = [c for c in items if not dim or dim == "all" or c.get("dim") == dim][:limit]
        body = {"run": _run_meta(run, freshness), "items": items, "dims": _dims(counts),
                "problems": run.get("problems") or [], "meta": meta}
        if gated is not None:
            body["gated"] = gated
        return body

    def _top(surface: str, h: str, run: dict, visible: list[dict], limit: int,
             now: int) -> list[dict]:
        keys = {c["rec_key"] for c in visible}
        with gw.appdb.read() as conn:
            top = store.top_get(conn, surface, h)
            if (top and now - top["created_at"] < TOP_TTL_MS and top["rec_keys"]
                    and set(top["rec_keys"]) <= keys and len(top["rec_keys"]) >= min(
                        limit, len(visible))):
                cached = store.by_keys(conn, top["run_id"], top["rec_keys"][:limit])
                if len(cached) == len(top["rec_keys"][:limit]):
                    return cached
        chosen = visible[:limit]
        with gw.appdb.write() as conn:
            store.top_put(conn, surface, h, run["run_id"], [c["rec_key"] for c in chosen], now)
        return chosen

    @api.post("/v1/recommendations/recompute")
    def recompute(request: RecomputeRequest):
        scope = _scope_from_body(request.scope)
        result = runs.run(gw, asdict(scope), force=request.force)
        if result["freshness"] == "none":
            raise ApiError(409, "no_projection", "No published data to analyse", retryable=True)
        if result["run_id"] is None:
            return JSONResponse(result, status_code=202)
        return result

    @api.get("/v1/recommendations/runs")
    def run_history(scope=scope_dependency, limit: int = Query(20, ge=1, le=100)):
        with gw.appdb.read() as conn:
            return {"runs": store.list_runs(conn, scope_hash(asdict(scope), {}), limit)}

    @api.get("/v1/recommendations/relations")
    def relations(candidate_id: Annotated[list[str], Query(min_length=2, max_length=20)]):
        with gw.appdb.read() as conn:
            cards = [c for c in (store.candidate(conn, cid) for cid in candidate_id) if c]
        try:
            from ..recommend.relations import relations as compute_relations
        except ImportError:
            return {"pairs": []}
        result = compute_relations(cards)
        return result if isinstance(result, dict) else {"pairs": list(result or [])}

    @api.get("/v1/recommendations/handoff/{session_uid}")
    def handoff(session_uid: str):
        from ..recommend.handoff import build

        with gw.reads.read() as conn:
            result = build(conn, session_uid)
        if result is None:
            raise ApiError(404, "not_found", "Unknown session")
        return result

    @api.get("/v1/recommendations/metrics")
    def metrics(days: int = Query(90, ge=1, le=365)):
        with gw.appdb.read() as conn:
            return {"rows": outcomes.metrics_ev05(conn, days)}

    @api.get("/v1/recommendations/settings")
    def get_settings():
        return {**runs.settings_for(gw), "ai_available": runs.ai_enabled(gw)}

    @api.put("/v1/recommendations/settings")
    def put_settings(request: SettingsRequest):
        platform = getattr(gw, "platform", None)
        if platform is None:
            raise ApiError(503, "unavailable", "Settings store not ready", retryable=True)
        current = {**runs.DEFAULT_SETTINGS, **(platform.settings.get("recommend", {}) or {})}
        patch = request.model_dump(exclude_unset=True)
        platform.settings.put("recommend", {**current, **patch})
        return get_settings()

    @api.get("/v1/recommendations/{candidate_id}")
    def detail(candidate_id: str):
        with gw.appdb.read() as conn:
            item = store.candidate(conn, candidate_id)
            if item is None:
                raise ApiError(404, "not_found", "Unknown recommendation")
            key = item["rec_key"]
            alternatives = store.by_keys(conn, item["run_id"], item.get("alternatives") or [])
            state = store.states(conn, [key]).get(key)
            tracking = conn.execute("SELECT * FROM tracking WHERE rec_key=? ORDER BY "
                                    "registered_at DESC LIMIT 1", (key,)).fetchone()
            outcome = outcomes.outcome(conn, tracking["install_id"]) if tracking else None
            return {"item": item, "alternatives": alternatives, "state": state,
                    "labels": store.labels_for(conn, key),
                    "exposures": store.exposure_summary(conn, key),
                    "tracking": dict(tracking) if tracking else None,
                    "outcome": {"effect_status": outcome["effect_status"],
                                "windows": outcome["windows"]} if outcome else None}

    @api.post("/v1/recommendations/exposures")
    def exposures(batch: ExposureBatch):
        now, result, missing = runs.now_ms(), {}, []
        with gw.appdb.write() as conn:
            for item in batch.items:
                try:
                    state = store.record_exposure(conn, item.candidate_id, batch.surface,
                                                  item.position, item.action, now)
                except KeyError:
                    missing.append(item.candidate_id)
                    continue
                result[state["rec_key"]] = state
        return {"ok": True, "states": result, "missing": missing}

    @api.post("/v1/recommendations/{candidate_id}/exposure")
    def exposure(candidate_id: str, request: ExposureRequest):
        try:
            with gw.appdb.write() as conn:
                state = store.record_exposure(conn, candidate_id, request.surface,
                                              request.position, request.action, runs.now_ms())
        except KeyError as error:
            raise ApiError(404, "not_found", "Unknown recommendation") from error
        return {"ok": True, "state": state}

    @api.post("/v1/recommendations/{candidate_id}/tracking")
    def tracking(candidate_id: str, request: TrackingRequest):
        try:
            tracking_id = outcomes.register_tracking(gw.appdb, request.install_id, candidate_id,
                                                     request.installed_at)
        except KeyError as error:
            raise ApiError(404, "not_found", "Unknown recommendation") from error
        return {"tracking_id": tracking_id}

    @api.post("/v1/labels")
    def add_label(request: LabelRequest):
        if request.label == "not_applicable" and request.reason is None:
            raise ApiError(422, "invalid_request", "reason is required for not_applicable")
        with gw.appdb.write() as conn:
            if request.target_kind == "candidate" and store.candidate_row(
                    conn, request.target_id) is None:
                raise ApiError(404, "not_found", "Unknown recommendation")
            label_id, effect = store.add_label(conn, request.target_kind, request.target_id,
                                               request.label, request.reason,
                                               now=runs.now_ms())
        return {"label_id": label_id, "effect": effect}

    @api.delete("/v1/labels/{label_id}")
    def undo_label(label_id: str):
        with gw.appdb.write() as conn:
            if not store.undo_label(conn, label_id, runs.now_ms()):
                raise ApiError(404, "not_found", "Unknown label")
        return {"ok": True}

    @api.get("/v1/outcomes/{install_id}")
    def outcome(install_id: str):
        with gw.appdb.read() as conn:
            result = outcomes.outcome(conn, install_id)
        if result is None:
            raise ApiError(404, "not_found", "Unknown install")
        return result

    return api


def _dims(counts: dict[str, int]) -> list[dict]:
    total = sum(counts.values())
    return [{"id": key, "label": label, "count": total if key == "all" else counts.get(key, 0)}
            for key, label in DIMS]
