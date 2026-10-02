"""One selection and reusable indexes for a single analysis request."""

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from .bottleneck import analyze_bottleneck
from .inputs import KINDS, AnalysisInputBundle, Scope, select
from .respond.calls import normalize_tool_calls, pair_tool_calls, project_call_sequence

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
    _families: dict[tuple[str, ...], Record] = field(default_factory=dict, init=False)
    _call_pieces: dict[str, tuple] = field(default_factory=dict, init=False)
    _pieces_handed_out: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
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

    @cached_property
    def _context_positions(self) -> dict[str, list[tuple[int, Record]]]:
        groups: dict[str, list[tuple[int, Record]]] = defaultdict(list)
        for i, event in enumerate(self.diagnostics["context_events"]):
            groups[event["session_uid"]].append((i, event))
        return groups

    def tree_context_events(self, ids: set[str]) -> list[Record]:
        """Context events of ``ids`` in their global order, without scanning all of them."""
        if len(ids) == 1:
            return list(self.context_groups.get(next(iter(ids)), ()))
        pairs = [pair for sid in ids for pair in self._context_positions.get(sid, ())]
        pairs.sort(key=lambda pair: pair[0])
        return [event for _, event in pairs]

    @cached_property
    def _session_positions(self) -> dict[str, int] | None:
        """Selection positions, or None when uids repeat (callers then scan the list)."""
        positions = {s["session_uid"]: i for i, s in enumerate(self.sessions)}
        return positions if len(positions) == len(self.sessions) else None

    def tree_sessions(self, ids: set[str]) -> list[Record]:
        """Sessions of ``ids`` in selection order, without scanning the whole selection."""
        positions = self._session_positions
        if positions is None:
            return [s for s in self.sessions if s["session_uid"] in ids]
        return [self.sessions[i] for i in sorted(positions[sid] for sid in ids if sid in positions)]

    def seed_families(self, ids: set[str], value: Record) -> None:
        """Store families computed elsewhere (a worker) for exactly this scope."""
        self._families.setdefault(tuple(sorted(ids)), value)

    def _call_piece(self, sid: str) -> tuple:
        """Pairing, normalization and sequence projection of one session, computed once.

        All three are keyed by session and sorted session-first, so a scope's result is
        the concatenation of its sessions' pieces in sorted uid order. Session rows,
        project rows and the whole selection then share one computation per session.
        """
        piece = self._call_pieces.get(sid)
        if piece is None:
            events = self.event_groups.get(sid, [])
            context_events = self.context_groups.get(sid, [])
            execution = list(
                {(e["session_uid"], e["event_uid"]): e for e in [*events, *context_events]}.values()
            )
            paired = pair_tool_calls(execution)
            calls = None if self.calls is None else self.call_groups.get(sid, [])
            normalized = normalize_tool_calls(calls)
            base = normalized["calls"] if calls is not None else paired["calls"]
            projected = project_call_sequence(base, execution) if base else []
            piece = self._call_pieces[sid] = (paired, normalized, projected)
        return piece

    def _respond_inputs(self, key: tuple[str, ...]) -> tuple | None:
        """Assemble ``analyze_respond``'s pairing inputs for a scope from session pieces."""
        if self.bundle.events is None or self.event_status in ("excluded", "unavailable"):
            return None
        if self.bundle.coverage.get("tool_calls", {}).get("status", "partial") == "excluded":
            return None
        pieces = [self._call_piece(sid) for sid in key]
        any_paired = any(p[0]["calls"] for p in pieces)
        paired = {
            "calls": [c for p in pieces for c in p[0]["calls"]] if any_paired else [],
            "orphan_result_event_uids": [u for p in pieces for u in p[0]["orphan_result_event_uids"]],
            "duplicate_event_uids": [u for p in pieces for u in p[0]["duplicate_event_uids"]],
            "pairing_conflicts": copy.deepcopy([c for p in pieces for c in p[0]["pairing_conflicts"]]),
        }
        normalized = {
            "calls": None,  # only consumed through ``effective``
            "duplicate_call_rows": sum(p[1]["duplicate_call_rows"] for p in pieces),
            "call_conflicts": copy.deepcopy([c for p in pieces for c in p[1]["call_conflicts"]]),
        }
        effective = None
        if self.calls is not None or any_paired:
            if len(key) == 1 and key[0] not in self._pieces_handed_out:
                # The session's own scope takes the projected rows themselves; every other
                # scope gets one-level copies, exactly as project_call_sequence hands out.
                self._pieces_handed_out.add(key[0])
                return paired, normalized, list(pieces[0][2])
            effective = []
            for p in pieces:
                for original in p[2]:
                    call = dict(original)
                    for k, v in call.items():
                        if isinstance(v, (list, dict)):
                            call[k] = v.copy()
                    effective.append(call)
        return paired, normalized, effective

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
                respond_inputs=self._respond_inputs(key),
            )
        return self._families[key]
