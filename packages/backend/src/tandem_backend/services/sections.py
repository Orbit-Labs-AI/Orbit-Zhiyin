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

    result = response_section(memo.analysis(store, scope, True, params.get("_rev")), "sessions")
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

LIGHT = tuple(name for name, s in SECTIONS.items() if s.cost == "light" and name != "session")
HEAVY = tuple(name for name, s in SECTIONS.items() if s.cost == "heavy" and name != "session")

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
