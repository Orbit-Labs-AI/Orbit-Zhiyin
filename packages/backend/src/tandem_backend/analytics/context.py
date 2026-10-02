"""One selection and reusable indexes for a single analysis request."""

from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from .bottleneck import analyze_bottleneck
from .inputs import KINDS, AnalysisInputBundle, Scope, select
from .work_graph import WorkIndex, build_work_index

Record = dict[str, Any]


def group_sessions(records: list[Record] | None) -> dict[str, list[Record]]:
    """Index records without changing their content or native order."""
    groups: dict[str, list[Record]] = defaultdict(list)
    for record in records or []:
        groups[record["session_uid"]].append(record)
    return groups


@dataclass
class AnalysisContext:
    """Own request-local intermediate results; never cache across data snapshots."""

    bundle: AnalysisInputBundle
    scope: Scope
    sessions: list[Record]
    events: list[Record]
    calls: list[Record] | None
    model_calls: list[Record] | None
    diagnostics: Record
    event_groups: dict[str, list[Record]] = field(init=False)
    call_groups: dict[str, list[Record]] = field(init=False)
    model_groups: dict[str, list[Record]] = field(init=False)
    context_groups: dict[str, list[Record]] = field(init=False)
    session_map: dict[str, Record] = field(init=False)
    children: dict[str, set[str]] = field(init=False)
    work_index: WorkIndex = field(init=False)
    _families: dict[tuple[str, ...], Record] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.work_index = build_work_index(
            self.events if self.bundle.events is not None else None,
            self.sessions, self.calls, self.model_calls,
        )
        self.events, self.calls, self.model_calls = (
            self.work_index.events, self.work_index.calls, self.work_index.model_calls,
        )
        self.event_groups = group_sessions(self.events)
        self.call_groups = group_sessions(self.calls)
        self.model_groups = group_sessions(self.model_calls)
        self.context_groups = group_sessions(self.diagnostics["context_events"])
        self.session_map = {s["session_uid"]: s for s in self.sessions}
        self.children = defaultdict(set)
        for session in self.sessions:
            if session.get("kind") in ("subagent", "workflow_agent") and session.get("root_uid"):
                self.children[session["root_uid"]].add(session["session_uid"])

    @classmethod
    def select(cls, bundle: AnalysisInputBundle, scope: Scope) -> "AnalysisContext":
        """Select statistical members once; keep linked context separately."""
        return cls(bundle, scope, *select(bundle, scope))

    @cached_property
    def main_ids(self) -> frozenset[str]:
        """Main-session ids, computed once; per-event membership checks stay O(1)."""
        return frozenset(s["session_uid"] for s in self.sessions if s.get("kind") == "main")

    @property
    def event_status(self) -> str:
        return (
            "unavailable"
            if self.bundle.events is None
            else self.bundle.coverage.get("events", {}).get("status", "partial")
        )

    @property
    def supported_kinds(self) -> set[str] | None:
        return (
            set(KINDS.values())
            if self.bundle.versions.get("storage") == "legacy-json-ledger"
            else None
        )

    def members(self, ids: set[str], kind: str) -> list[Record] | None:
        """Return indexed records for a scope, preserving unavailable datasets."""
        source = {
            "events": self.bundle.events,
            "calls": self.calls,
            "models": self.model_calls,
            "context": [],
        }[kind]
        if source is None:
            return None
        groups = {
            "events": self.event_groups,
            "calls": self.call_groups,
            "models": self.model_groups,
            "context": self.context_groups,
        }[kind]
        return [row for sid in sorted(ids) for row in groups.get(sid, [])]

    def families(self, ids: set[str]) -> Record:
        """Reuse identical scopes; never average ratios or merge interval totals."""
        key = tuple(sorted(ids))
        if key not in self._families:
            self._families[key] = analyze_bottleneck(
                [self.session_map[sid] for sid in key],
                self.members(ids, "events"),
                self.members(ids, "calls"),
                self.members(ids, "models"),
                self.main_ids,
                self.scope,
                self.bundle.coverage,
                self.members(ids, "context"),
                self.supported_kinds,
            )
        return self._families[key]
