"""AN-19 session outcome synthesizer: strongest observable layer wins, else ``unknown``.

Priority ``explicit_feedback > verification > facet > structural``. Agent claims,
written files, commits or wrapper success never establish ``completed``.
"""

from typing import Any

from ..outcome_subjective import analyze_subjective_outcomes
from .detectors import SessionView
from .dictionary import is_edit_call

Record = dict[str, Any]

FACETS = {"fully_achieved": "completed", "mostly_achieved": "completed",
          "partially_achieved": "partial"}


def _key(row: Record) -> tuple:
    return (row.get("seq") if row.get("seq") is not None else -1, row.get("call_uid") or "")


def verification_state(view: SessionView) -> Record:
    """Executed validation facts shared by AN-02 ``verify_*`` and the verification layer."""
    if view.calls is None or view.validation_runs is None:
        return {"available": False, "verify_ran": None, "verify_pass": None,
                "verify_candidate": None, "last_edit": None, "runs_after_edit": None}
    runs = sorted(view.validation_runs, key=_key)
    edits = [c for c in view.calls if is_edit_call(c)
             and c.get("tool_result_status") != "rejected" and c.get("seq") is not None]
    last = max(edits, key=lambda c: (c.get("started_at") or 0, _key(c))) if edits else None
    by_uid = {c["call_uid"]: c for c in view.calls}

    def after(run):
        if last is None:
            return True
        if run["session_uid"] == last["session_uid"]:
            return run.get("seq") is not None and run["seq"] > last["seq"]
        ts = (by_uid.get(run["call_uid"]) or {}).get("started_at")
        return ts is not None and last.get("started_at") is not None and ts > last["started_at"]

    final = runs[-1]["validation_result"] if runs else None
    return {"available": True, "verify_ran": bool(runs),
            "verify_pass": None if final in (None, "unknown") else final == "passed",
            "verify_candidate": len(view.validation_candidates or []),
            "last_edit": last, "runs_after_edit": [r for r in runs if after(r)]}


def _structural(view: SessionView, detected: dict, deliveries: list[Record]) -> Record | None:
    turns = sorted(view.turns or [], key=lambda t: (t["session_uid"] != view.session_uid, t.get("idx", 0)))
    own_turns = [t for t in turns if t["session_uid"] == view.session_uid]
    if own_turns and own_turns[-1].get("status") == "interrupted":
        return {"outcome": "abandoned", "basis": "structural",
                "evidence": [{"turn_uid": own_turns[-1]["turn_uid"], "reason": "last_turn_interrupted"}]}
    own = [e for e in view.events or [] if e["session_uid"] == view.session_uid]
    if own and own[-1]["kind"] == "turn.interrupted":
        return {"outcome": "abandoned", "basis": "structural",
                "evidence": [{"event_uid": own[-1]["event_uid"], "reason": "last_turn_interrupted"}]}
    friction = [o for kind in ("correction", "frustration") for s in detected.get(kind) or []
                for o in s["occurrences"] if o["session_uid"] == view.session_uid]
    humans = [e for e in own if e["kind"] == "message.user" and e["session_uid"] in view.main_ids
              and e.get("attrs", {}).get("origin") == "human"]
    if humans and friction:
        last_human = humans[-1]
        later = [d for d in deliveries if d["session_uid"] == view.session_uid and d["seq"] > last_human["seq"]]
        if any(o["event_uid"] == last_human["event_uid"] for o in friction) and not later:
            return {"outcome": "abandoned", "basis": "structural",
                    "evidence": [{"event_uid": last_human["event_uid"], "reason": "ended_on_correction"}]}
    return None


def synthesize_outcome(view: SessionView, detected: dict, facet: str | None = None) -> Record:
    """Return ``{outcome, basis, evidence}`` for one root session tree."""
    unknown = {"outcome": "unknown", "basis": "unknown", "evidence": []}
    if view.events is None:
        return {**unknown, "reason": "events_unavailable"}
    report = analyze_subjective_outcomes(view.events, view.main_ids)
    deliveries = sorted(report["deliveries"] or [], key=_key)
    feedback = sorted(report["feedback"] or [], key=_key)
    # 1. explicit feedback after the last delivery
    if deliveries:
        last = deliveries[-1]
        after = [f for f in feedback if f["session_uid"] == last["session_uid"] and f["seq"] > last["seq"]]
        if after:
            f = after[-1]
            ev = [{"event_uid": f["event_uid"], "delivery_event_uid": last["delivery_event_uid"]}]
            if f["user_acceptance"] != "mixed":
                if f["user_acceptance"] == "accepted" or f["user_confirmed_completion"] is True:
                    return {"outcome": "completed", "basis": "explicit_feedback", "evidence": ev}
                if (f["user_acceptance"] == "rejected" or f["rework_feedback"]
                        or f["user_confirmed_completion"] is False):
                    return {"outcome": "partial", "basis": "explicit_feedback", "evidence": ev}
    # 2. executed verification after the last edit
    state = verification_state(view)
    runs = state["runs_after_edit"] or []
    if runs:
        passed = [r for r in runs if r["validation_result"] == "passed"]
        corrections = [o for s in detected.get("correction") or [] for o in s["occurrences"]]
        if passed:
            p = passed[-1]
            later_fail = any(r["validation_result"] == "failed" and _key(r) > _key(p) for r in runs)
            later_fix = any(o["session_uid"] == p["session_uid"] and (o.get("seq") or -1) > (p.get("seq") or -1)
                            for o in corrections)
            if not later_fail and not later_fix:
                return {"outcome": "completed", "basis": "verify_pass",
                        "evidence": [{"call_uid": p["call_uid"], "validation_uid": p["validation_uid"]}]}
        if runs[-1]["validation_result"] == "failed":
            return {"outcome": "failed", "basis": "verify_fail",
                    "evidence": [{"call_uid": runs[-1]["call_uid"],
                                  "validation_uid": runs[-1]["validation_uid"]}]}
    # 3. AI facet (only through the mapping table)
    structural = _structural(view, detected, deliveries)
    if facet in FACETS:
        return {"outcome": FACETS[facet], "basis": "facet", "evidence": [{"facet": facet}]}
    if facet == "not_achieved":
        if deliveries:
            return {"outcome": "partial", "basis": "facet", "evidence": [{"facet": facet}]}
        if structural:
            return {**structural, "basis": "facet", "evidence": [{"facet": facet}, *structural["evidence"]]}
        return {**unknown, "evidence": [{"facet": facet}]}
    # 4. structural rules only supply abandoned
    return structural or unknown
