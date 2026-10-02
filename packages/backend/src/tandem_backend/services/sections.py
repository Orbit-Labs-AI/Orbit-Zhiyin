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
