"""SECTIONS registry: which analysis slices the gateway serves and how a worker computes them.

The default computation calls the existing ``analyze_store`` + ``response_section`` so
response keys match ``api/routes.py``. The analysis package adds sections by calling
``register`` (for example metrics / profile / signals); the gateway routes stay generic.
Runs inside the analysis worker; the gateway only imports names and costs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Compute = Callable[[Any, Any, dict, "ResultMemo"], dict]
SESSION_SUMMARY_FIELDS = ("session_uid", "kind", "project_id", "legacy_project_id", "title",
                          "features", "cluster_id", "novelty", "embedding_x", "embedding_y",
                          "effective_samples", "unknown_counts")
SESSION_USAGE_FIELDS = ("status", "request_count", "total_tokens", "cost_usd")


class SectionNotFound(KeyError):
    """The requested record is not part of the analysed scope."""


@dataclass(frozen=True)
class Section:
    name: str
    key: str
    cost: Literal["light", "heavy"]
    compute: Compute
    with_text: bool = False
    timeout_s: float | None = None  # Overrides the supervisor's per-cost budget.
    prewarm: bool = True
    # Strikes before the circuit opens (None: SupervisorConfig.max_failures). Expensive
    # on-demand sections use 1 so a timed-out / killed run is reported, not re-run in a loop.
    max_failures: int | None = None


class ResultMemo:
    """Keeps the last full analysis per (scope, with_text, revision) inside one worker so
    several sections of the same scope do not each re-run the 10-second engine."""

    def __init__(self, size: int = 2):
        self.size = size
        self.entries: list[tuple[str, dict]] = []

    def analysis(self, store, scope, with_text: bool, revision: Any) -> dict:
        from dataclasses import asdict

        from ..analytics.service import analyze_store

        key = json.dumps([asdict(scope), with_text, revision], sort_keys=True, default=str)
        for cached_key, value in self.entries:
            if cached_key == key:
                return value
        value = analyze_store(store, scope, with_text)
        self.entries = [(key, value), *self.entries][: self.size]
        return value


def _section(key: str, with_text: bool) -> Compute:
    def compute(store, scope, params, memo):
        from ..analytics.service import response_section

        return response_section(memo.analysis(store, scope, with_text, params.get("_rev")), key)

    return compute


def _sessions(store, scope, params, memo):
    """Compact summary rows for every session; the gateway pages them (≤ 200 per page)."""
    from ..analytics.service import response_section

    result = response_section(memo.analysis(store, scope, True, params.get("_rev")), "sessions")
    result["sessions"] = [
        {**{k: s.get(k) for k in SESSION_SUMMARY_FIELDS},
         "usage": {k: (s.get("usage") or {}).get(k) for k in SESSION_USAGE_FIELDS}}
        for s in result["sessions"]]
    return result


def _session_detail(store, scope, params, memo):
    from ..analytics.service import response_section

    result = response_section(memo.analysis(store, scope, True, params.get("_rev")), "sessions")
    row = next((s for s in result.pop("sessions") if s["session_uid"] == params["session_id"]),
               None)
    if row is None:
        raise SectionNotFound("会话不在本次分析范围内")
    return {**result, "session": row}


def _preferences(store, scope, params, memo):
    from ..analytics.preference import resolve_effective_preferences
    from ..analytics.service import response_section

    data = memo.analysis(store, scope, False, params.get("_rev"))
    task = None
    if params.get("task_id") is not None:
        task = next((t for t in data["tasks"]["records"] or []
                     if t["task_id"] == params["task_id"]), None)
        if task is None:
            raise SectionNotFound("任务不在本次分析范围内")
    result = response_section(data, "preferences")
    result["preferences"] = {**result["preferences"], "effective": resolve_effective_preferences(
        data["preferences"]["records"], task,
        at=scope.until_ts - 1 if scope.until_ts is not None else None)}
    return result


SECTIONS: dict[str, Section] = {}


def register(section: Section) -> Section:
    SECTIONS[section.name] = section
    return section


# with_text mirrors api/routes.py (sessions, text and projects include text features).
for _name, _cost, _text in (("overview", "light", False), ("tools", "light", False),
                            ("projects", "light", True), ("instruction", "light", False),
                            ("text", "heavy", True), ("tasks", "heavy", False)):
    register(Section(_name, _name, _cost, _section(_name, _text), _text))
register(Section("sessions", "sessions", "light", _sessions, True))
register(Section("session", "session", "heavy", _session_detail, True))
register(Section("preferences", "preferences", "light", _preferences, False))

def _compact_section(key: str) -> Compute:
    def compute(store, scope, params, memo):
        from ..analytics.products.payload import compact
        from ..analytics.service import response_section

        result = response_section(memo.analysis(store, scope, False, params.get("_rev")), key)
        result[key] = compact(result[key])
        return result

    return compute


def _products(store, scope, params, memo):
    """Former synchronous gateway fallback; the gateway pages ``sessions`` of this body."""
    from ..analytics.products import analyze_product_store

    return analyze_product_store(store, scope, bucket=params.get("bucket", "day"),
                                 with_text=bool(params.get("with_text")),
                                 compare_previous=bool(params.get("compare_previous")))


def _presentation(store, scope, params, memo):
    from ..analytics.presentation import build_presentation
    from ..analytics.presentation.metrics import window_scope

    selected = window_scope(scope, params.get("window"))
    result = dict(memo.analysis(store, selected, False, params.get("_rev")))
    target, family = params.get("target_agent", "generic"), params.get("family")
    if target != "generic" or family:
        from ..recommend.service import recommend

        result["bottleneck_recommendations"] = recommend(result, context={"agent": target},
                                                         family=family)
    return build_presentation(result)


def _recommendations(store, scope, params, memo):
    from ..analytics.service import response_section
    from ..recommend.service import recommend

    result = dict(memo.analysis(store, scope, False, params.get("_rev")))
    options = {k: params[k] for k in ("kind", "family") if params.get(k) is not None}
    result["bottleneck_recommendations"] = recommend(
        result, context=params.get("context") or {}, limit=params.get("limit", 6), **options)
    return response_section(result, "bottleneck_recommendations")


def _legacy_report(store, scope, params, memo):
    """``/v1/analysis``: the CLI report use case; the scope is unused (params carry filters)."""
    from ..application.reports import build_report

    scene = params.get("scene", "auto")
    _, result = build_report(store, project_id=params.get("project_id"),
                             model=params.get("model"), before=params.get("before"),
                             scene=scene if scene != "auto" else None,
                             recommendation_scene=scene, audience=params.get("audience", "user"),
                             catalog_cache=".local/catalog.json")
    return result  # Legacy body shape: the report itself at top level, plus ``meta``.


# Legacy create_app() analyses that used to run synchronously inside the gateway process
# (analyze_store / build_report on the gateway threadpool: no timeout, no RSS cap, GIL
# starvation). On demand only (never prewarmed); products may run for minutes on a large home.
_ON_DEMAND = {"prewarm": False, "max_failures": 1}
for _name in ("statistics", "lexical"):
    register(Section(_name, _name, "light", _compact_section(_name), **_ON_DEMAND))
register(Section("bottleneck", "bottleneck_features", "heavy",
                 _compact_section("bottleneck_features"), **_ON_DEMAND))
register(Section("recommendations", "bottleneck_recommendations", "heavy", _recommendations,
                 **_ON_DEMAND))
register(Section("analysis", "analysis", "heavy", _legacy_report, **_ON_DEMAND))
register(Section("products", "products", "heavy", _products, timeout_s=1800, **_ON_DEMAND))
register(Section("presentation", "presentation", "heavy", _presentation, timeout_s=1800,
                 **_ON_DEMAND))

LIGHT = tuple(name for name, s in SECTIONS.items()
              if s.cost == "light" and name != "session" and s.prewarm)
HEAVY = tuple(name for name, s in SECTIONS.items()
              if s.cost == "heavy" and name != "session" and s.prewarm)

_RULES: str | None = None


def rules_digest() -> str:
    """Changes whenever rule versions, the feature schema or the engine version change."""
    global _RULES
    if _RULES is None:
        from .. import __version__
        from ..analytics import FEATURE_VERSION
        from ..analytics.products.contracts import RULE_VERSIONS

        payload = json.dumps([RULE_VERSIONS, FEATURE_VERSION, __version__, sorted(SECTIONS)],
                             sort_keys=True)
        _RULES = hashlib.sha256(payload.encode()).hexdigest()[:12]
    return _RULES


def compute_section(name: str, store, scope, params: dict, memo: ResultMemo) -> dict:
    section = SECTIONS.get(name)
    if section is None:
        raise SectionNotFound(f"Unknown section {name}")
    return section.compute(store, scope, params, memo)

from ..recommend import section as _recommend_section  # noqa: E402,F401  registers recommend_inputs
from ..uiview import section as _uiview_section  # noqa: E402,F401  registers uiview_facts
