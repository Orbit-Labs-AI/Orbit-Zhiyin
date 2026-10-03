"""Signal-layer and metric endpoints as a standalone ``APIRouter``.

``routes.create_app`` mounts it with a small adapter (task package b owns that file)::

    def insight_result(scope):
        context = AnalysisContext.select(store.analysis_bundle(scope), scope)
        return context, analyze_context(context, False, with_recommendations=False)

    app.include_router(build_router(insight_result, scope_dependency=analytics_scope))

``get_result(scope)`` must return ``(AnalysisContext, analyze_context result)``; raising
``ValueError`` becomes HTTP 422. The router never computes the eight families itself.
"""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ..analytics.context import AnalysisContext
from ..analytics.drilldown import MAX_LIMIT, tool_calls
from ..analytics.inputs import Scope
from ..analytics.metrics import METRICS, metrics
from ..analytics.signals import SignalLayer, build_signal_layer
from ..analytics.signals.dictionary import RULES_VERSION, SIGNAL_KINDS

Record = dict[str, Any]
GetResult = Callable[[Scope], tuple[AnalysisContext, Record | None]]
GetLabels = Callable[[Scope], list[Record] | None]
ListQuery = Annotated[list[str] | None, Query()]


def insights_scope(
    display_timezone: str = "UTC", project_ids: ListQuery = None, source_ids: ListQuery = None,
    from_ts: int | None = None, until_ts: int | None = None, root_session_uids: ListQuery = None,
    excluded_session_uids: ListQuery = None, include_children: bool = True,
) -> Scope:
    """A minimal Scope parser; ``create_app`` may pass its own dependency instead."""
    try:
        return Scope(display_timezone=display_timezone, project_ids=project_ids,
                     source_ids=source_ids, from_ts=from_ts, until_ts=until_ts,
                     root_session_uids=root_session_uids,
                     excluded_session_uids=excluded_session_uids or [],
                     include_children=include_children)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def build_router(get_result: GetResult, *, get_labels: GetLabels | None = None,
                 scope_dependency: Callable[..., Scope] | None = None) -> APIRouter:
    router = APIRouter(prefix="/v1/analytics", tags=["insights"])
    scope_param = Depends(scope_dependency or insights_scope)

    def load(scope: Scope) -> tuple[AnalysisContext, Record | None, SignalLayer]:
        try:
            context, result = get_result(scope)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return context, result, build_signal_layer(context, result)

    @router.get("/metrics")
    def get_metrics(scope: Scope = scope_param, metric: ListQuery = None,
                    bucket: Literal["day", "week"] | None = None,
                    group_by: Literal["agent", "source", "project", "model", "effort", "day",
                                      "week"] | None = None):
        unknown = [m for m in metric or [] if m not in METRICS]
        if unknown:
            raise HTTPException(422, f"未知指标：{', '.join(unknown)}")
        context, result, layer = load(scope)
        return metrics(context, result, metric, bucket, group_by, layer=layer)

    @router.get("/signals")
    def get_signals(scope: Scope = scope_param, kind: ListQuery = None):
        unknown = [k for k in kind or [] if k not in SIGNAL_KINDS]
        if unknown:
            raise HTTPException(422, f"未知 signal.kind：{', '.join(unknown)}")
        _, _, layer = load(scope)
        rows = [s for s in layer.signals if not kind or s["kind"] in kind]
        return {"rules_version": RULES_VERSION, "signal_kinds": SIGNAL_KINDS, "signals": rows,
                "summary": {sid: f["signals_summary"] for sid, f in layer.facts.items()}}

    @router.get("/problems")
    def get_problems(scope: Scope = scope_param, include_candidates: bool = False):
        _, _, layer = load(scope)
        out = layer.problems(get_labels(scope) if get_labels else None)
        if not include_candidates:
            out.pop("candidates")
        return out

    @router.get("/sessions/{session_uid}/facts")
    def get_session_facts(session_uid: str, scope: Scope = scope_param):
        _, _, layer = load(scope)
        if session_uid not in layer.facts:
            raise HTTPException(404, "会话不在当前范围内，或不是根会话")
        return {"rules_version": RULES_VERSION, "facts": layer.facts[session_uid],
                "key_moments": layer.moments[session_uid],
                "signals": [s for s in layer.signals if s["session_uid"] == session_uid]}

    @router.get("/tools/{name}/calls")
    def get_tool_calls(name: str, scope: Scope = scope_param,
                       limit: int = Query(20, ge=1, le=MAX_LIMIT), command_head: str | None = None):
        context, result, _ = load(scope)
        out = tool_calls(context, name, limit=limit, command_head=command_head, result=result)
        if out["status"] == "available" and out["total"] == 0:
            raise HTTPException(404, "当前范围内没有该工具的调用")
        return out

    return router
