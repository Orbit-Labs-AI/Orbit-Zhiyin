"""SECTIONS registry: which analysis slices the gateway serves and how a worker computes them.

Each section reads ``analyze_sections`` (the read-through cache on canonical stores) and
``response_section``, so response keys match ``api/routes.py`` and both share cached results. The analysis package adds sections by calling
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
                          "agent", "source_id", "parent_uid", "root_uid", "started_at",
                          "ended_at", "status",
                          "features", "cluster_id", "novelty", "embedding_x", "embedding_y",
                          "effective_samples", "unknown_counts")
SESSION_USAGE_FIELDS = ("status", "request_count", "total_tokens", "cost_usd")
MOMENT_EVENT_KINDS = ("permission.request", "context.compaction", "turn.interrupted")
MAX_KEY_MOMENTS = 200


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

    def without_recommendations(self, store, scope, revision: Any) -> dict:
        """Every section but the default recommendations, for callers that rerun
        ``recommend()`` with their own context (canonical stores skip computing the
        default set only to discard it; legacy stores reuse the memoised full pass)."""
        from ..analytics.cache import supports_cache
        from ..analytics.service import SECTIONS

        if supports_cache(store):
            keys = [n for n in SECTIONS if n != "bottleneck_recommendations"]
            return self.sections(store, scope, keys, False, revision)
        return self.analysis(store, scope, False, revision)

    def sections(self, store, scope, keys: list[str], with_text: bool, revision: Any) -> dict:
        """Canonical stores read only ``keys`` through the analysis read-through cache, which
        is keyed by the session-tree fingerprint and shared with ``api/routes.py``; other
        stores fall back to the memoised full analysis."""
        from ..analytics.cache import supports_cache
        from ..analytics.service import analyze_sections

        if supports_cache(store):
            return analyze_sections(store, scope, keys, with_text)
        return self.analysis(store, scope, with_text, revision)


def _section(key: str, with_text: bool) -> Compute:
    def compute(store, scope, params, memo):
        from ..analytics.service import response_section

        return response_section(
            memo.sections(store, scope, [key], with_text, params.get("_rev")), key)

    return compute


def _sessions(store, scope, params, memo):
    """Compact summary rows for every session; the gateway pages them (≤ 200 per page)."""
    from ..analytics.service import response_section

    result = response_section(
        memo.sections(store, scope, ["sessions"], True, params.get("_rev")), "sessions")
    result["sessions"] = [
        {**{k: s.get(k) for k in SESSION_SUMMARY_FIELDS},
         "usage": {k: (s.get("usage") or {}).get(k) for k in SESSION_USAGE_FIELDS},
         "outcome": session_outcome(s)}
        for s in result["sessions"]]
    return result


def session_outcome(row: dict) -> dict:
    """Compact, separately sourced outcome facts; never a single inferred success verdict."""
    objective = row.get("objective_outcomes") or {}
    feedback = (row.get("subjective_outcomes") or {}).get("counts") or {}
    totals = (row.get("tools") or {}).get("totals") or {}
    outcome = (row.get("bottleneck_features") or {}).get("outcome") or {}
    return {"session_status": row.get("status"),
            "task_success": objective.get("task_success"),
            "tool_failure_count": totals.get("known_failure_count"),
            "explicit_tool_failures": objective.get("explicit_tool_failures"),
            "validation_result_counts": outcome.get("validation_result_counts"),
            "accepted_feedback_count": feedback.get("accepted_feedback_count"),
            "rejected_feedback_count": feedback.get("rejected_feedback_count"),
            "rework_feedback_count": feedback.get("rework_feedback_count")}


def _store_facts(store, session_uids: list[str]) -> dict:
    """Model/effort mix and notable protocol events read straight from the canonical store."""
    connect = getattr(store, "connect", None)
    if connect is None or not session_uids:
        return {"status": "unavailable", "models": None, "efforts": None, "events": None}
    marks = ",".join("?" * len(session_uids))
    try:
        with connect() as db:
            rows = db.execute(
                f"SELECT c.model_raw, c.effort_raw, COUNT(*) FROM event e JOIN event_context c "
                f"USING(event_uid) WHERE e.session_uid IN ({marks}) AND e.kind='model.usage' "
                f"GROUP BY 1, 2", session_uids).fetchall()
            if not rows:  # no usage events: fall back to the context of any event
                rows = db.execute(
                    f"SELECT c.model_raw, c.effort_raw, COUNT(*) FROM event e JOIN event_context "
                    f"c USING(event_uid) WHERE e.session_uid IN ({marks}) AND "
                    f"(c.model_raw IS NOT NULL OR c.effort_raw IS NOT NULL) GROUP BY 1, 2",
                    session_uids).fetchall()
            kinds = ",".join("?" * len(MOMENT_EVENT_KINDS))
            events = db.execute(
                f"SELECT session_uid, event_uid, seq, ts, kind FROM event WHERE session_uid IN "
                f"({marks}) AND kind IN ({kinds}) ORDER BY session_uid, seq LIMIT ?",
                [*session_uids, *MOMENT_EVENT_KINDS, MAX_KEY_MOMENTS]).fetchall()
    except Exception as error:  # noqa: BLE001 - detail must still render without these facts
        return {"status": "unavailable", "reason": type(error).__name__, "models": None,
                "efforts": None, "events": None}
    models, efforts = {}, {}
    for model, effort, n in rows:
        models[model or "unknown"] = models.get(model or "unknown", 0) + n
        efforts[effort or "unknown"] = efforts.get(effort or "unknown", 0) + n
    return {"status": "available", "models": models, "efforts": efforts,
            "events": [dict(zip(("session_uid", "event_uid", "seq", "ts", "kind"), r, strict=True))
                       for r in events]}


def key_moments(row: dict, events: list[dict] | None) -> list[dict]:
    """Tool failures, correction signals, user feedback and protocol interruptions, in order."""
    moments = {}

    def add(session_uid, event_uid, seq, ts, tag):
        if not event_uid:
            return
        item = moments.setdefault(event_uid, {"session_uid": session_uid, "event_uid": event_uid,
                                              "seq": seq, "ts": ts, "types": []})
        if tag not in item["types"]:
            item["types"].append(tag)

    for call in row.get("tool_sequence") or []:
        if call.get("status") == "failed":
            add(call.get("session_uid"), call.get("call_event_uid"), call.get("seq"),
                call.get("started_at"), "tool_failure")
    for signal in row.get("correction_signals") or []:
        add(row.get("session_uid"), signal.get("event_uid"), None, None, "correction")
    for item in row.get("subjective_outcome_candidates") or []:
        add(row.get("session_uid"), item.get("event_uid"), None, item.get("ts"), "user_feedback")
    for event in events or []:
        add(event["session_uid"], event["event_uid"], event["seq"], event["ts"], event["kind"])
    ordered = sorted(moments.values(), key=lambda m: (
        m["ts"] is None, m["ts"] or 0, m["session_uid"] or "", m["seq"] or 0, m["event_uid"]))
    return ordered[:MAX_KEY_MOMENTS]


def _session_detail(store, scope, params, memo):
    from ..analytics.service import response_section

    result = response_section(
        memo.sections(store, scope, ["sessions"], True, params.get("_rev")), "sessions")
    row = next((s for s in result.pop("sessions") if s["session_uid"] == params["session_id"]),
               None)
    if row is None:
        raise SectionNotFound("会话不在本次分析范围内")
    facts = _store_facts(store, row.get("included_session_uids") or [row["session_uid"]])
    row = {**row,
           "outcome": session_outcome(row),
           "models": {"status": facts["status"], "models": facts["models"],
                      "efforts": facts["efforts"], "reason": facts.get("reason"),
                      "basis": "event_context of model.usage events (any event as fallback)"},
           "key_moments": key_moments(row, facts["events"]),
           "signals": {"correction": row.get("correction_signals"),
                       "language": row.get("language_signals"),
                       "tool_failure_count": session_outcome(row)["tool_failure_count"],
                       "feedback": (row.get("subjective_outcomes") or {}).get("counts")}}
    return {**result, "session": row}


def _sample_files(store, scope, params, memo):
    """Full sample-boundary file list; section bodies only carry its count and digest."""
    from ..analytics.service import response_section

    data = memo.analysis(store, scope, False, params.get("_rev"))
    result = response_section(data, "overview")
    result.pop("overview")
    return {**result, "files": (data.get("sample_boundary") or {}).get("files") or []}


def _preferences(store, scope, params, memo):
    from ..analytics.preference import resolve_effective_preferences
    from ..analytics.service import response_section

    data = memo.sections(store, scope, ["tasks", "preferences"], False, params.get("_rev"))
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
# Full passes (``uiview_facts``, recommendations) read ``WITH_TEXT``: the cache also files
# their text-free sections under the ``with_text=False`` key, so one computation per scope
# serves every section.
WITH_TEXT = True
for _name, _cost, _text in (("overview", "light", False), ("tools", "light", False),
                            ("projects", "light", True), ("instruction", "light", False),
                            ("text", "heavy", True), ("tasks", "heavy", False)):
    register(Section(_name, _name, _cost, _section(_name, _text), _text))
register(Section("sessions", "sessions", "light", _sessions, True))
register(Section("session", "session", "heavy", _session_detail, True))
register(Section("preferences", "preferences", "light", _preferences, False))
register(Section("sample_files", "files", "light", _sample_files, False, prewarm=False))

def _compact_section(key: str) -> Compute:
    def compute(store, scope, params, memo):
        from ..analytics.products.payload import compact
        from ..analytics.service import response_section

        result = response_section(memo.analysis(store, scope, False, params.get("_rev")), key)
        result[key] = compact(result[key])
        return result

    return compute


def _summarised(body: dict, *nested: str) -> dict:
    """Swap ``sample_boundary.files`` for count + digest (the list is /v1/analytics/sample_files)."""
    from ..analytics.service import boundary_summary

    body = dict(body)
    if isinstance(body.get("sample_boundary"), dict):
        body["sample_boundary"] = boundary_summary(body["sample_boundary"])
    for key in nested:
        if isinstance(body.get(key), dict):
            body[key] = _summarised(body[key])
    return body


def _products(store, scope, params, memo):
    """Former synchronous gateway fallback; the gateway pages ``sessions`` of this body."""
    from ..analytics.products import analyze_product_store

    body = analyze_product_store(store, scope, bucket=params.get("bucket", "day"),
                                 with_text=bool(params.get("with_text")),
                                 compare_previous=bool(params.get("compare_previous")))
    return _summarised(body)


def _presentation(store, scope, params, memo):
    from ..analytics.presentation import bounded_presentation
    from ..analytics.presentation.metrics import window_scope

    selected = window_scope(scope, params.get("window"), now_ts=params.get("window_until"))
    target, family = params.get("target_agent", "generic"), params.get("family")
    if target == "generic" and not family:  # the analysis' own default set is the answer
        return _summarised(bounded_presentation(memo.analysis(store, selected, False,
                                                              params.get("_rev"))))
    from ..recommend.service import recommend

    result = dict(memo.without_recommendations(store, selected, params.get("_rev")))
    result["bottleneck_recommendations"] = recommend(result, context={"agent": target},
                                                     family=family)
    return _summarised(bounded_presentation(result))


def _default_recommendation_request(params: dict) -> bool:
    """Same inputs as the analysis' own ``recommend(full_without_recommendations)`` call."""
    from ..recommend.contracts import RecommendationContext

    return (params.get("kind") is None and params.get("family") is None
            and params.get("limit", 6) == 6
            and RecommendationContext.model_validate(params.get("context") or {})
            == RecommendationContext())


def _recommendations(store, scope, params, memo):
    from ..analytics.service import response_section
    from ..recommend.service import recommend

    if _default_recommendation_request(params):
        return response_section(memo.analysis(store, scope, False, params.get("_rev")),
                                "bottleneck_recommendations")
    result = dict(memo.without_recommendations(store, scope, params.get("_rev")))
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


def _scope_comparison(store, scope, params, memo):
    """``POST /v1/analytics/compare``: two full product analyses; ``scope`` is unused."""
    from ..analytics.inputs import Scope
    from ..analytics.products.service import compare_scopes

    return _summarised(compare_scopes(store, Scope(**params["first"]), Scope(**params["second"])),
                       "first", "second")


def _catalog_requests(store, scope, params, memo):
    """``/v1/catalog/match-analysis`` input: the gateway matches these against its catalog."""
    from orbit_catalog.analysis_adapter import requests_from_analysis

    from ..profiling.analysis import analyze

    data = analyze(store, params.get("project_id"), params.get("model"),
                   scene=params.get("scene"))
    return {"requests": [r.model_dump(mode="json")
                         for r in requests_from_analysis(data, limit=params.get("limit", 10))]}


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
register(Section("comparison", "comparison", "heavy", _scope_comparison, timeout_s=1800,
                 **_ON_DEMAND))
register(Section("catalog_requests", "requests", "heavy", _catalog_requests, **_ON_DEMAND))
register(Section("products", "products", "heavy", _products, timeout_s=1800, **_ON_DEMAND))
register(Section("presentation", "presentation", "heavy", _presentation, timeout_s=1800,
                 **_ON_DEMAND))
# Work graph / task trajectories (PR #58): worker-computed like the other analysis
# sections instead of the legacy create_app() inline fallthrough.
register(Section("work_graph", "work_graph", "heavy", _section("work_graph", False), False,
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
        from ..analytics.products.contracts import rule_versions
        from ..recommend.engine import ENGINE_VERSION
        from ..recommend.section import FACTS_VERSION
        from ..uiview.persona_signals import UNITS_VERSION

        payload = json.dumps([rule_versions(), FEATURE_VERSION, __version__, sorted(SECTIONS),
                              {"full_pass_with_text": WITH_TEXT, "recommend_facts": FACTS_VERSION,
                               "recommend_engine": ENGINE_VERSION,
                               "uiview_units": UNITS_VERSION}], sort_keys=True)
        _RULES = hashlib.sha256(payload.encode()).hexdigest()[:12]
    return _RULES


def estimate_events(store, scope) -> int | None:
    """Upper bound on the events a scope selects (sources, projects, roots, time window).

    Far cheaper than the analysis itself; the supervisor sizes the task's time budget from
    it. Without project/root filters it counts on the (kind, ts) index only (a time window
    on a real home: a join over every event took 12 s under load). ``None`` when the store
    cannot answer (legacy stores).
    """
    import json

    connect = getattr(store, "connect", None)
    if connect is None:
        return None
    narrow = scope.project_ids is not None or scope.root_session_uids is not None
    try:
        with connect() as db:
            if not narrow:
                if scope.from_ts is None and scope.until_ts is None:
                    return int(db.execute("SELECT count(*) FROM event").fetchone()[0])
                kinds = [row[0] for row in db.execute("SELECT DISTINCT kind FROM event")]
                where, args = ["kind IN (SELECT value FROM json_each(?))"], [json.dumps(kinds)]
                for clause, value in (("ts >= ?", scope.from_ts), ("ts < ?", scope.until_ts)):
                    if value is not None:
                        where.append(clause)
                        args.append(value)
                return int(db.execute("SELECT count(*) FROM event WHERE " + " AND ".join(where),
                                      args).fetchone()[0])
            where, args = [], []
            for column, values in (("s.source_id", scope.source_ids),
                                   ("s.project_id", scope.project_ids),
                                   ("s.root_uid", scope.root_session_uids)):
                if values is not None:
                    where.append(f"{column} IN ({','.join('?' * len(values))})" if values else "0")
                    args.extend(values)
            if scope.from_ts is not None:
                where.append("(e.ts IS NULL OR e.ts >= ?)")
                args.append(scope.from_ts)
            if scope.until_ts is not None:
                where.append("(e.ts IS NULL OR e.ts < ?)")
                args.append(scope.until_ts)
            sql = ("SELECT count(*) FROM event e JOIN session s ON s.session_uid = e.session_uid"
                   + (" WHERE " + " AND ".join(where) if where else ""))
            return int(db.execute(sql, args).fetchone()[0])
    except Exception:  # noqa: BLE001  sizing is advisory; the analysis reports real errors.
        return None


def compute_section(name: str, store, scope, params: dict, memo: ResultMemo) -> dict:
    section = SECTIONS.get(name)
    if section is None:
        raise SectionNotFound(f"Unknown section {name}")
    return section.compute(store, scope, params, memo)

from ..recommend import section as _recommend_section  # noqa: E402,F401  registers recommend_inputs
from ..uiview import section as _uiview_section  # noqa: E402,F401  registers uiview_facts
