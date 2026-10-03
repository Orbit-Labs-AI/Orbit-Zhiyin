"""Lossless decision audit for the bounded recommendation pool.

Candidate metadata is stored once; ordered stage decisions reference its rec_key.
This is observational: recording must never change eligibility, scores or quotas.
Ingestion counts are explicitly analysis-input summaries, not proof of raw capture.
Injection/activation/usage belong to the client and are unknown here, never zero.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy

SOURCE = "recommendation_funnel"
VERSION = "recommendation-funnel-v1"
COMPATIBILITY_CHECKS = {"agent_supported", "language_ok", "requirements_ok"}


class Funnel:
    def __init__(self, inputs: dict, problems: list[dict], recall: dict):
        self.candidates: dict[str, dict] = {}
        self.stages: list[dict] = []
        self.upstream = {
            "history_ingestion": {
                "status": "analysis_input_summary",
                "sessions": deepcopy(inputs.get("sessions") or {}),
                "data_rev": inputs.get("data_rev"),
                "scope_hash": inputs.get("scope_hash"),
                "raw_capture_verified": None,
            },
            "analytics_evidence": {
                "signals": len(inputs.get("signals") or []),
                "tasks": len(inputs.get("tasks") or []),
                "problem_statuses": dict(Counter(p.get("status", "unknown") for p in problems)),
                "problems": [{k: deepcopy(p.get(k)) for k in (
                    "problem_id", "type", "key", "status", "sessions", "denominator",
                    "wilson_lo", "weekly_count", "evidence")} for p in problems],
            },
            "recall": deepcopy(recall.get("audit") or {"routes": recall.get("routes") or {}}),
        }

    def record(self, stage: str, decisions) -> None:
        rows, kinds, retained = [], Counter(), Counter()
        for cand, keep, reasons in decisions:
            key, kind = cand["rec_key"], cand.get("kind", "unknown")
            entry = self.candidates.setdefault(key, {"rec_key": key})
            # Keep evidence from the raw candidate even if later UI serialization compacts it.
            for field in ("kind", "title", "evidence", "source", "routes", "problem", "agents", "target"):
                if field in cand and cand[field] is not None:
                    entry[field] = deepcopy(cand[field])
            row = {"rec_key": key, "kept": bool(keep), "reasons": list(reasons),
                   "score": deepcopy(cand.get("score"))}
            if cand.get("gates") is not None:
                row["checks"] = deepcopy(cand["gates"].get("checks") or {})
            rows.append(row)
            kinds[kind] += 1
            if keep:
                retained[kind] += 1
        self.stages.append({"stage": stage, "input_count": len(rows),
                            "kept_count": sum(retained.values()),
                            "rejected_count": len(rows) - sum(retained.values()),
                            "input_types": dict(sorted(kinds.items())),
                            "kept_types": dict(sorted(retained.items())), "decisions": rows})

    def export(self) -> dict:
        return {"version": VERSION, "upstream": self.upstream,
                "stages": self.stages, "candidates": self.candidates,
                "runtime": {stage: {"status": "not_observed", "count": None}
                            for stage in ("pi_injection", "runtime_activation", "actual_usage")}}


def from_diagnostics(diagnostics: list[dict]) -> dict | None:
    return next((d.get("data") for d in reversed(diagnostics) if d.get("source") == SOURCE), None)


def append_stage(data: dict, stage: str, decisions) -> None:
    audit = Funnel({}, [], {})
    audit.candidates, audit.stages = data["candidates"], data["stages"]
    audit.record(stage, decisions)
