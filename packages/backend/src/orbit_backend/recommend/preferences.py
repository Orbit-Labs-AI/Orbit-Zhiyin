"""Resolve explicit preferences using analytics history and scoped request input."""

from collections import defaultdict

from ..analytics.preference import resolve_effective_preferences
from .recall._common import ranked

_SCOPE_RANK = {"global": 0, "project": 1, "task": 2}
_ORIGIN_RANK = {"analytics": 0, "request": 1}


def _priority(pref):
    return _SCOPE_RANK[pref["scope"]], _ORIGIN_RANK[pref["origin"]]


def _applies(scope, target, task, project):
    return scope == "global" or scope == "project" and target == project or scope == "task" and target == task


def resolve_preferences(analysis, row, tasks, context):
    """An ambiguous multi-task root cannot borrow one task's preferences.

    History retains the existing revoke/time/conflict semantics. At a given
    scope current request input wins over explicit preference history.
    Historical Instruction observations never become effective preferences.
    Unresolved higher-scope conflicts never fall back to lower-scope values.
    """
    task = tasks[0] if len(tasks) == 1 else {"project_id": row.get("project_id"),
                                          "legacy_project_id": row.get("legacy_project_id")}
    task_id, project = task.get("task_id"), row.get("project_id")
    until = (analysis.get("scope") or {}).get("until_ts")
    at = until - 1 if until is not None else None
    candidates, unresolved = [], []
    preferences = analysis.get("preferences") or {}
    for section, origin in (("records", "analytics"),):
        # These are structured extraction records, never raw/persona text.
        records = [r for r in preferences.get(section) or []
                   if r.get("status") == "observed" and r.get("preference_evidence")
                   and r.get("confirmation") == "explicit_human_statement"]
        resolved = resolve_effective_preferences(records, task, at=at)
        unresolved.extend(resolved["unresolved"] or [])
        for record in resolved["applicable"] or []:
            scope = record["preference_scope"]
            candidates.append({"dimension": record["preference_type"], "value": record["value"],
                               "polarity": record["polarity"], "scope": scope["kind"],
                               "target_id": scope["target_id"], "origin": origin,
                               "evidence": record["preference_evidence"], "conflict": False})
        for conflict in resolved["conflicts"] or []:
            candidates.append({"dimension": conflict["preference_type"], "scope": conflict["scope"]["kind"],
                               "origin": origin, "conflict": True, "details": conflict})
    for pref in context.preferences:
        if _applies(pref.scope, pref.target_id, task_id, project):
            candidates.append({**pref.model_dump(), "origin": "request", "evidence": [], "conflict": False})
        else:
            unresolved.append({**pref.model_dump(), "reason": "outside_scope_or_ambiguous_task"})
    groups = defaultdict(list)
    for candidate in candidates:
        groups[candidate["dimension"]].append(candidate)
    effective, conflicts = [], []
    for dimension, values in sorted(groups.items()):
        highest = max(map(_priority, values))
        chosen = [p for p in values if _priority(p) == highest]
        positive = {p["value"].strip().casefold() for p in chosen if not p["conflict"] and p["polarity"] == "prefer"}
        negative = {p["value"].strip().casefold() for p in chosen if not p["conflict"] and p["polarity"] == "avoid"}
        if any(p["conflict"] for p in chosen) or len(positive) > 1 or positive & negative:
            conflicts.append({"dimension": dimension, "scope": chosen[0]["scope"],
                              "reason": "unresolved_values", "candidates": chosen})
            continue
        # Repetition is evidence, not additional preference weight.
        unique = {}
        for pref in chosen:
            pref = {k: v for k, v in pref.items() if k != "conflict"}
            pref["value"] = pref["value"].strip().casefold()
            unique.setdefault((pref["value"], pref["polarity"]), pref)
        effective.extend(unique.values())
    return {"preference_ids": row.get("preference_ids"), "used_for_ranking": bool(effective),
            "effective": effective, "conflicts": conflicts, "unresolved": unresolved,
            "task_id": task_id, "project_id": project,
            "precedence": "task > project > global; same scope: request > explicit history"}


def match_preferences(state, item):
    support = {key: {v.strip().casefold() for v in values if v.strip()}
               for key, values in item.preference_support.items()}
    for key, values in (("tool", item.requirements.tools), ("capability", item.capability.tags),
                        ("task_type", item.target_task.tags)):
        support.setdefault(key, set()).update(v.strip().casefold() for v in values)
    matches = []
    for pref in state.preference_state.get("effective", []):
        known = support.get(pref["dimension"], set())
        contains = pref["value"] in known
        outcome = ("unknown" if not known else "matched" if contains == (pref["polarity"] == "prefer")
                   else "mismatch")
        matches.append({**pref, "outcome": outcome, "supported_values": sorted(known)})
    # Equal dimension weights: a long list of avoid values cannot dominate.
    dimensions = defaultdict(list)
    for match in matches:
        dimensions[match["dimension"]].append({"matched": 1., "unknown": .5, "mismatch": 0.}[match["outcome"]])
    scores = [sum(values) / len(values) for values in dimensions.values()]
    return {"score": sum(scores) / len(scores) if scores else 0., "active": bool(matches), "matches": matches}


def recall(state, items, limit=50):
    scores = {}
    for item in items:
        match = match_preferences(state, item)
        if any(p["outcome"] == "matched" for p in match["matches"]):
            scores[item.identity.id] = match["score"]
    return ranked(scores, limit)
