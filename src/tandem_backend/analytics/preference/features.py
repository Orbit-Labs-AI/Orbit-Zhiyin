"""Explicit observations, scope-aware history and conservative as-of resolution."""

import re
from collections import Counter, defaultdict
from heapq import heappop, heappush

from ...models import stable_id
from ..common import clauses, evidence, semantic_coverage, semantic_messages
from .rules import CHANGE, EXPLICIT, GLOBAL, PROJECT, REPORTED, REVOKE, TASK, preference_values


def _scope(statement, session, task_id):
    if TASK.search(statement):
        return {"kind": "task", "target_id": task_id, "identity_quality": "derived_task" if task_id else "missing"}
    if PROJECT.search(statement):
        canonical = session.get("project_id")
        return {"kind": "project", "target_id": canonical or session.get("legacy_project_id"),
                "identity_quality": "canonical" if canonical else "legacy_path" if session.get("legacy_project_id") else "missing"}
    if GLOBAL.search(statement):
        return {"kind": "global", "target_id": None, "identity_quality": "explicit"}
    return {"kind": "unknown", "target_id": None, "identity_quality": "unspecified"}


def _key(record):
    scope = record["preference_scope"]
    return (record["preference_type"], scope["kind"], scope["target_id"], scope["identity_quality"])


def _earlier(left, right):
    a, b = left["preference_evidence"][0], right["preference_evidence"][0]
    if a["session_uid"] == b["session_uid"]:
        return a["seq"] < b["seq"]
    return a["ts"] is not None and b["ts"] is not None and a["ts"] < b["ts"]


def _ordered(records):
    """Merge session sequences; wall clocks never reorder a session's native seq."""
    groups = defaultdict(list)
    for record in records:
        groups[record["effective_position"]["session_uid"]].append(record)
    heap = []
    for sid, rows in groups.items():
        rows.sort(key=lambda r: (r["effective_position"]["seq"], r["preference_id"]))
        ts = rows[0]["effective_at"]
        heappush(heap, (ts if ts is not None else float("inf"), sid, 0))
    while heap:
        _, sid, i = heappop(heap)
        yield groups[sid][i]
        if i + 1 < len(groups[sid]):
            ts = groups[sid][i + 1]["effective_at"]
            heappush(heap, (ts if ts is not None else float("inf"), sid, i + 1))


def extract_explicit_preferences(events, sessions, task_by_event=None):
    messages = semantic_messages(events, sessions)
    session_map = {s["session_uid"]: s for s in sessions}
    records, candidates, instructions = [], [], []
    for event in messages:
        for index, statement in enumerate(clauses(event["semantic_text"])):
            if REPORTED.search(statement) or event["semantic_text"].rstrip().endswith(("?", "？")):
                continue
            values = preference_values(statement)
            explicit = bool(EXPLICIT.search(statement) or (PROJECT.search(statement) or GLOBAL.search(statement)) and CHANGE.search(statement) or REVOKE.search(statement))
            if not values or not explicit and not TASK.search(statement):
                continue
            scope = _scope(statement, session_map[event["session_uid"]], (task_by_event or {}).get(event["event_uid"]))
            for kind, value, polarity in values:
                record = {"preference_id": stable_id("preference", event["session_uid"], event["event_uid"], index, kind, value),
                    "preference_statement": statement, "preference_type": kind, "value": value, "polarity": polarity,
                    "preference_scope": scope, "preference_evidence": [evidence(event, statement)],
                    "confirmation": "explicit_human_statement", "confirmed_by": event.get("attrs", {}).get("author_id"),
                    "effective_at": event.get("ts"), "effective_position": {"session_uid": event["session_uid"], "seq": event["seq"]},
                    "time_basis": "observed_message_time" if event.get("ts") is not None else "sequence_only",
                    "operation": "revoke" if REVOKE.search(statement) else "revise" if CHANGE.search(statement) else "assert",
                    "preference_history": [], "status": "observed", "missing_reasons": []}
                if scope["kind"] == "unknown" or scope["kind"] in ("task", "project") and scope["target_id"] is None:
                    record["missing_reasons"].append("scope_not_resolved")
                if event.get("ts") is None:
                    record["missing_reasons"].append("timestamp_missing")
                if event.get("text_truncated"):
                    record.update(status="candidate", confirmation="truncated_statement")
                    record["missing_reasons"].append("text_truncated")
                    candidates.append(record)
                elif re.search(r"或者|或|\bor\b", statement, re.I) and sum(v[0] == kind for v in values) > 1:
                    record.update(status="candidate", confirmation="alternative_values")
                    record["missing_reasons"].append("alternative_values_not_resolved")
                    candidates.append(record)
                elif re.search(r"明天|下周|下个月|从\s*\d{4}[-年/]|\b(?:tomorrow|next week|starting on)\b", statement, re.I):
                    record.update(status="candidate", effective_at=None, time_basis="future_schedule_unresolved")
                    record["missing_reasons"].append("scheduled_effective_time_not_parsed")
                    candidates.append(record)
                elif TASK.search(statement) and not EXPLICIT.search(statement):
                    record.update(status="instruction", confirmation="task_instruction")
                    instructions.append(record)
                else:
                    records.append(record)
    # No total order is invented across sessions with missing/equal timestamps.
    # Clocked records are processed in time order; within a session seq remains authoritative.
    records = list(_ordered(records))
    heads = defaultdict(dict)
    for record in records:
        group = heads[_key(record)]
        eligible = [p for p in group.values() if _earlier(p, record)]
        if record["operation"] in ("revise", "revoke") and record["preference_scope"]["kind"] != "unknown":
            for previous in eligible:
                if (record["operation"] == "revoke" or record["polarity"] == "avoid") and previous["value"] != record["value"]:
                    continue
                record["preference_history"].append({"relation": "revokes" if record["operation"] == "revoke" else "supersedes",
                    "preference_id": previous["preference_id"], "visible_at": record["effective_at"],
                    "evidence_id": record["preference_evidence"][0]["event_uid"]})
                group.pop(previous["preference_id"], None)
        if record["operation"] != "revoke":
            for previous in list(group.values()):
                if (previous["value"], previous["polarity"]) == (record["value"], record["polarity"]) and _earlier(previous, record):
                    record["preference_history"].append({"relation": "reaffirms", "preference_id": previous["preference_id"],
                        "visible_at": record["effective_at"], "evidence_id": record["preference_evidence"][0]["event_uid"]})
                    group.pop(previous["preference_id"])
            group[record["preference_id"]] = record
    return {"records": records if events is not None else None,
            "candidates": candidates if events is not None else None,
            "task_instructions": instructions if events is not None else None,
            "coverage": semantic_coverage(events, messages), "family_version": "preference-v1"}


def resolve_effective_preferences(history, task=None, at=None):
    """`at` is an inclusive UTC-ms instant; missing clocks cannot establish past applicability."""
    task = task or {}
    if history is None:
        return {"applicable": None, "conflicts": None, "unresolved": None, "at": at}
    visible, unresolved = [], []
    for record in history:
        ts = record["effective_at"]
        if at is not None and ts is None:
            unresolved.append({"preference_id": record["preference_id"], "reason": "timestamp_missing"})
            continue
        if at is not None and ts > at:
            continue
        scope = record["preference_scope"]
        if scope["kind"] == "unknown" or scope["kind"] in ("task", "project") and scope["target_id"] is None:
            unresolved.append({"preference_id": record["preference_id"], "reason": "scope_not_resolved"})
            continue
        if scope["kind"] == "task" and scope["target_id"] != task.get("task_id"):
            continue
        if scope["kind"] == "project":
            field = "project_id" if scope["identity_quality"] == "canonical" else "legacy_project_id"
            if scope["target_id"] != task.get(field):
                continue
        visible.append(record)
    retired = {link["preference_id"] for record in visible for link in record["preference_history"]}
    groups = defaultdict(list)
    for record in visible:
        if record["preference_id"] not in retired and record["operation"] != "revoke":
            groups[_key(record)].append(record)
    conflicts, applicable = [], []
    rank = {"global": 0, "project": 1, "task": 2}
    best = {}
    for key in groups:
        best[key[0]] = max(best.get(key[0], -1), rank[key[1]])
    for key, records in groups.items():
        if rank[key[1]] < best[key[0]]:
            continue
        positive = {r["value"] for r in records if r["polarity"] == "prefer"}
        negative = {r["value"] for r in records if r["polarity"] == "avoid"}
        if len(positive) > 1 or positive & negative:
            conflicts.append({"preference_type": key[0], "scope": records[0]["preference_scope"],
                              "preference_ids": [r["preference_id"] for r in records], "reason": "unresolved_values"})
        else:
            applicable.extend(records)
    return {"applicable": applicable, "conflicts": conflicts, "unresolved": unresolved, "at": at,
            "precedence": "explicit task > project > global; current instructions remain separate"}


def summarize_preferences(preferences, scope=None):
    if preferences is None:
        return {"record_count": None, "by_type": None, "by_scope": None, "scope": scope}
    unique = list({r["preference_id"]: r for r in preferences}.values())
    return {"record_count": len(unique), "by_type": dict(sorted(Counter(r["preference_type"] for r in unique).items())),
            "by_scope": dict(sorted(Counter(r["preference_scope"]["kind"] for r in unique).items())),
            "missing_time_count": sum(r["effective_at"] is None for r in unique), "scope": scope,
            "counting": "distinct explicit observation IDs; repetition is not preference strength"}
