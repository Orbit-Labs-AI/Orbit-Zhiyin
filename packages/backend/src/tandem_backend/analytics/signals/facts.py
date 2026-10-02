"""AN-02 session fact extensions: outcome, ``verify_*``, ``autonomy_steps``, ``signals_summary``.

These are additive fields for a session row; the existing ``_session_rows`` output is
not modified here — callers merge by ``session_uid``.
"""

from collections import defaultdict
from typing import Any

from ..common import human
from .detectors import SessionView, opportunities
from .dictionary import RULES_VERSION
from .outcome import verification_state

Record = dict[str, Any]


def autonomy_steps(view: SessionView) -> float | None:
    """Median observed steps (tool calls + final deliveries) in human-containing turns."""
    if view.events is None:
        return None
    turns = defaultdict(list)
    for e in view.events:
        if e.get("turn_uid") and e["session_uid"] in view.main_ids:
            turns[(e["session_uid"], e["turn_uid"])].append(e)
    steps = []
    for events in turns.values():
        if not any(human(e, view.main_ids) for e in events):
            continue
        calls = {e.get("call_id") or e["event_uid"] for e in events if e["kind"] == "tool.call"}
        finals = [e for e in events if e["kind"] == "message.assistant"
                  and e.get("attrs", {}).get("phase") in ("final", "final_answer")]
        steps.append(len(calls) + len(finals))
    if not steps:
        return None
    steps.sort()
    mid = len(steps) // 2
    return steps[mid] if len(steps) % 2 else (steps[mid - 1] + steps[mid]) / 2


def verify_requested(view: SessionView) -> bool | None:
    if view.instruction_records is None:
        return None
    return any((r.get("features") or {}).get("verification_requirements")
               for r in view.instruction_records)


def signals_summary(detected: dict) -> dict[str, int | None]:
    """Occurrences per kind; ``None`` = evidence unavailable, never a zero."""
    return {kind: None if rows is None else sum(s["value"] for s in rows)
            for kind, rows in detected.items()}


def session_facts(view: SessionView, detected: dict, outcome: Record) -> Record:
    s = view.session
    state = verification_state(view)
    return {"session_uid": view.session_uid, "kind": s.get("kind"),
            "project_id": s.get("project_id") or s.get("legacy_project_id"),
            "source_id": s.get("source_id"), "agent": s.get("agent") or s.get("source_agent"),
            "started_at": s.get("started_at"), "included_session_uids": view.member_ids,
            "outcome": outcome["outcome"], "outcome_basis": outcome["basis"],
            "outcome_evidence": outcome["evidence"],
            "verify_requested": verify_requested(view), "verify_ran": state["verify_ran"],
            "verify_pass": state["verify_pass"], "verify_candidate": state["verify_candidate"],
            "autonomy_steps": autonomy_steps(view),
            "signals_summary": signals_summary(detected),
            "opportunities": opportunities(view), "rules_version": RULES_VERSION}
