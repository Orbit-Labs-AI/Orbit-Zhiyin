"""Evidence-backed labels, intervention links and interaction summaries."""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict

from ..common import annotation_visible, human, ratio, task_uid
from ..semantic_cascade import observation_for
from .rules import EXECUTION_KINDS, FRICTIONS, INTENTS, correction_terms


def classify_message_intents(events, main_ids, until_ts=None):
    """Consume bounded inferred observations and compatible reviewed evaluation labels.

    The optional attrs.interaction annotation is an upstream labeling contract,
    not a semantic classifier hidden inside the non-semantic feature family.
    """
    lookup = {(e["session_uid"], e["event_uid"]): e for e in events}
    rows = []
    for e in sorted(lookup.values(), key=lambda e: (e["session_uid"], e["seq"], e["event_uid"])):
        if not human(e, main_ids):
            continue
        a = e.get("attrs", {}).get("interaction") or {}
        labels = a.get("intents")
        labels_valid = (isinstance(labels, list) and bool(labels)
                        and all(isinstance(v, str) and v in INTENTS for v in labels))
        reviewed = (a.get("state") == "confirmed" and bool(a.get("source"))
                    and annotation_visible(a, until_ts) and labels_valid)
        target = lookup.get((e["session_uid"], a.get("target_event_uid")))
        target_valid = bool(target and target["seq"] < e["seq"] and task_uid(e)
                            and task_uid(target) == task_uid(e))
        # A confirmed correction must identify what was corrected in this task.
        if reviewed and "correction" in labels and not target_valid:
            reviewed = False
        terms = correction_terms(e.get("text") or "")
        friction = a.get("friction_types")
        friction_valid = (reviewed and target_valid and isinstance(friction, list)
                          and all(isinstance(v, str) and v in FRICTIONS for v in friction))
        requirements = a.get("requirements")
        requirement_valid = (reviewed and bool(task_uid(e)) and isinstance(requirements, list)
                             and all(isinstance(v, dict) and v.get("object_uid")
                                     and v.get("requirement_uid") for v in requirements))
        semantic = observation_for(e, lookup, until_ts)
        inferred = bool(not reviewed and semantic and semantic["intents"])
        if inferred:
            target = lookup.get((e["session_uid"], semantic["target_event_uid"]))
            target_valid = bool(target and target["seq"] < e["seq"] and task_uid(e)
                                and task_uid(target) == task_uid(e))
        rows.append({"event_uid": e["event_uid"], "session_uid": e["session_uid"],
                     "turn_uid": e.get("turn_uid"), "task_uid": task_uid(e), "seq": e["seq"],
                     "intents": sorted(set(labels)) if reviewed else sorted(set(semantic["intents"])) if inferred else None,
                     "state": "confirmed" if reviewed else "inferred" if inferred else "candidate" if terms else "unknown",
                     "candidate_intents": ["correction"] if terms else [], "candidate_terms": terms,
                     "friction_types": sorted(set(friction)) if friction_valid else
                     semantic["friction_types"] if inferred and target_valid else None,
                     "requirements": requirements if requirement_valid else None,
                     "target_event_uid": target["event_uid"] if target_valid else None,
                     "evidence_event_uids": [e["event_uid"]] + ([target["event_uid"]] if target_valid else []),
                     "source": a.get("source") if reviewed else "semantic_model" if inferred else "lexical_proxy" if terms else None,
                     "available_at": a.get("available_at") if reviewed else semantic["available_at"] if inferred else e.get("ts"),
                     "missing_reason": "inferred_correction_target_unresolved" if inferred and "correction" in semantic["intents"] and not target_valid
                     else None if reviewed or inferred else "missing_or_invalid_visible_annotation",
                     **({"confidence": {"tier": "inferred", "calibrated_probability": None},
                         "intent_quote": semantic["intent_quote"], "model": semantic["model"]} if inferred else {})})
    return rows


def locate_interventions(events, main_ids):
    """Link human messages to recorded execution steps, within explicit tasks.

    Steps are indexed per (session, task) and located by bisection: a per-message scan
    over every step is quadratic and dominated analysis time on long real sessions.
    """
    groups = defaultdict(list)
    for e in events:
        groups[e["session_uid"]].append(e)
    points = []
    for es in groups.values():
        es.sort(key=lambda e: (e["seq"], e["event_uid"]))
        steps = [e for e in es if e["kind"] in EXECUTION_KINDS]
        by_task = defaultdict(list)
        for s in steps:
            by_task[task_uid(s)].append(s)
        seqs = {key: [s["seq"] for s in rows] for key, rows in by_task.items()}
        all_seqs = [s["seq"] for s in steps]
        for e in es:
            if not human(e, main_ids):
                continue
            task = task_uid(e)
            eligible, positions = (steps, all_seqs) if task is None else (
                by_task.get(task, []), seqs.get(task, []))
            low, high = bisect_left(positions, e["seq"]), bisect_right(positions, e["seq"])
            previous = eligible[low - 1] if low else None
            following = eligible[high] if high < len(eligible) else None
            points.append({"event_uid": e["event_uid"], "session_uid": e["session_uid"],
                           "task_uid": task, "turn_uid": e.get("turn_uid"), "seq": e["seq"],
                           "previous_step_uid": previous["event_uid"] if previous else None,
                           "next_step_uid": following["event_uid"] if following else None,
                           "next_step_available_at": following.get("ts") if following else None,
                           "relation_scope": "task" if task else "session_only"})
    return points


def summarize_interactions(labeled_messages):
    rows = list({(r["session_uid"], r["event_uid"]): r for r in labeled_messages}.values())
    known = [r for r in rows if r["state"] == "confirmed"]
    corrections = [r for r in known if "correction" in r["intents"]]
    requirement_rows = [r for r in known if r["requirements"] is not None]
    seen, repeated = set(), []
    for r in sorted(requirement_rows, key=lambda r: (r["session_uid"], r["seq"], r["event_uid"])):
        keys = {(r["session_uid"], r["task_uid"], v["object_uid"], v["requirement_uid"])
                for v in r["requirements"]}
        if keys & seen:
            repeated.append(r["event_uid"])
        seen.update(keys)
    friction_rows = [r for r in known if r["friction_types"] is not None]
    result = {"confirmed_correction_count": len(corrections) if known or not rows else None,
            "confirmed_correction_rate": ratio(len(corrections), len(known)),
            "correction_denominator": "confirmed human messages with determinable reviewed intents",
            "repeated_requirement_count": len(repeated) if requirement_rows or not rows else None,
            "repeated_requirement_evidence": repeated,
            "friction_types": dict(Counter(v for r in friction_rows for v in r["friction_types"])) if friction_rows else None,
            "effective_samples": {"human_messages": len(rows), "intent_messages": len(known),
                                  "requirement_messages": len(requirement_rows), "friction_messages": len(friction_rows)},
            "unknown_counts": {"intent_messages": len(rows) - len(known),
                               "requirement_messages": len(rows) - len(requirement_rows),
                               "friction_messages": len(rows) - len(friction_rows)},
            "correction_evidence": [r["event_uid"] for r in corrections]}
    inferred = [r for r in rows if r["state"] == "inferred"]
    if inferred:
        measured = [r for r in inferred if r["missing_reason"] is None]
        corrected = [r for r in measured if "correction" in r["intents"]]
        result["semantic_observations"] = {
            "intent_messages": len(inferred), "correction_count": len(corrected),
            "correction_rate": ratio(len(corrected), len(measured)),
            "correction_denominator": "model inferred intents with resolved correction targets",
            "unresolved_corrections": len(inferred) - len(measured),
            "friction_types": dict(Counter(v for r in measured for v in r["friction_types"] or [])),
            "evidence_event_uids": [r["event_uid"] for r in inferred],
            "quality": "model_inferred", "calibrated_probability": None,
        }
    return result
