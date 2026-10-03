"""Join explicit preferences and structured Instruction observations without parsing text.

Confidence encodes evidence precedence, not a calibrated probability. Historical
task support never changes explicit preference history or grants execution permission.
"""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Literal

from ...models import stable_id
from ..instruction.formats import FORMAT_NAMES

PREFERENCE_EVIDENCE_VERSION = "preference-evidence-v1"
SOURCE_CONFIDENCE = {"explicit_preference": 1.0, "task_instruction": 0.6, "semantic_task_instruction": 0.4}
INSTRUCTION_DIMENSIONS = {
    "requested_autonomy": ("autonomy", {"ask_first": "ask_first", "explicit": "autonomous"}),
    "execution_order": ("execution_style", {v: v for v in ("plan_first", "discuss_first", "execute_first")}),
    "verification_requirements": ("verification", {"requested": "requested"}),
    "format_requirements": ("format", {}),
}


@dataclass(frozen=True)
class PreferenceEvidence:
    evidence_id: str
    dimension: str
    value: str | None
    source_type: Literal["explicit_preference", "task_instruction", "semantic_task_instruction"]
    source_id: str
    session_uid: str
    task_id: str | None
    task_identity_quality: str
    project_id: str | None
    legacy_project_id: str | None
    cluster_id: str | int | None
    confidence: float
    observed_at: int | None
    evidence_event_uids: list[str]
    scope: dict
    statement: str | None
    seq: int
    status: str
    source_feature: str
    polarity: str = "prefer"
    operation: str = "assert"
    condition: str | None = None
    targets: list[str] | None = None
    missing_reasons: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    corroborates_evidence_id: str | None = None


def _context(row, sessions, task_by_event, cluster_by_session):
    session = sessions[row["session_uid"]]
    derived = (task_by_event or {}).get(row["event_uid"])
    task_id = derived or row.get("task_id")
    return {
        "session_uid": row["session_uid"], "task_id": task_id,
        "task_identity_quality": "task_family" if derived else "session_local" if task_id else "missing",
        "project_id": session.get("project_id"), "legacy_project_id": session.get("legacy_project_id"),
        "cluster_id": (cluster_by_session or {}).get(row["session_uid"]),
    }


def _uid(source_type, source_id, dimension, value):
    return stable_id(PREFERENCE_EVIDENCE_VERSION, source_type, source_id, dimension, value)


def instruction_to_preference_evidence(instructions, sessions, task_by_event=None,
                                       cluster_by_session=None):
    """Consume the four P0 fields; source text is copied for audit, never interpreted."""
    if instructions is None:
        return None
    session_map = {s["session_uid"]: s for s in sessions if s.get("kind") == "main"}
    result = {}
    for row in instructions:
        if row["session_uid"] not in session_map:
            continue
        context = _context(row, session_map, task_by_event, cluster_by_session)
        for constraint in row["constraints"]:
            feature = constraint["feature"]
            if feature not in INSTRUCTION_DIMENSIONS or constraint.get("source") not in ("confirmed_human_text", "semantic_model"):
                continue
            if (constraint["event_uid"], constraint["session_uid"]) != (row["event_uid"], row["session_uid"]):
                raise ValueError("Instruction constraint provenance does not match its observation")
            dimension, mapping = INSTRUCTION_DIMENSIONS[feature]
            if feature == "format_requirements":
                values = constraint.get("format_values")
                if values is not None and (not isinstance(values, list)
                        or any(not isinstance(v, str) or v not in FORMAT_NAMES for v in values)):
                    raise ValueError("Instruction format_values must contain normalized format names")
                values = sorted(set(values)) if values else [None]
            elif constraint["value"] in mapping:
                values = [mapping[constraint["value"]]]
            else:
                continue  # scoped autonomy is a task boundary, not an autonomy preference.
            pairs = [(dimension, value) for value in values]
            if feature == "format_requirements" and constraint.get("detail_value") in ("concise", "detailed"):
                pairs = [(d, v) for d, v in pairs if v is not None]
                pairs.append(("detail", constraint["detail_value"]))
            source_type = "semantic_task_instruction" if constraint.get("source") == "semantic_model" else "task_instruction"
            for dimension, value in pairs:
                reasons = []
                if context["task_id"] is None:
                    reasons.append("task_unknown")
                if "text_truncated" in row.get("unknown_reasons", []):
                    reasons.append("text_truncated")
                if constraint.get("condition"):
                    reasons.append("condition_not_evaluated")
                if value is None:
                    reasons.append("format_value_unavailable")
                if constraint.get("format_relation") == "alternative":
                    reasons.append("alternative_values_not_resolved")
                uid = _uid(source_type, constraint["constraint_uid"], dimension, value)
                result[uid] = asdict(PreferenceEvidence(
                    evidence_id=uid, dimension=dimension, value=value,
                    source_type=source_type, source_id=constraint["constraint_uid"],
                    **context, confidence=SOURCE_CONFIDENCE[source_type],
                    observed_at=row.get("ts"), evidence_event_uids=[row["event_uid"]],
                    scope={"kind": "task", "target_id": context["task_id"],
                           "identity_quality": context["task_identity_quality"]},
                    statement=constraint.get("text"), seq=row["seq"],
                    status="pending" if reasons else "observed", source_feature=feature,
                    condition=constraint.get("condition"), targets=constraint.get("targets"),
                    missing_reasons=reasons,
                ))
    return [result[key] for key in sorted(result)]


def explicit_to_preference_evidence(preferences, sessions, task_by_event=None,
                                    cluster_by_session=None):
    """Keep scope, polarity, candidate status and history from the explicit path."""
    if preferences["records"] is None:
        return None
    session_map = {s["session_uid"]: s for s in sessions}
    result = {}
    for record in preferences["records"] + (preferences.get("candidates") or []):
        source = record["preference_evidence"][0]
        context = _context(source, session_map, task_by_event, cluster_by_session)
        scope = record["preference_scope"]
        if context["task_id"] is None and scope["kind"] == "task" and scope["target_id"]:
            context.update(task_id=scope["target_id"], task_identity_quality="task_family")
        dimension, value = record["preference_type"], record["value"]
        # The old act_directly category mixes autonomy and order; retain it as
        # collaboration instead of inventing which control dimension was intended.
        if (dimension, value) == ("collaboration", "plan_first"):
            dimension = "execution_style"
        uid = _uid("explicit_preference", record["preference_id"], dimension, value)
        result[uid] = asdict(PreferenceEvidence(
            evidence_id=uid, dimension=dimension, value=value,
            source_type="explicit_preference", source_id=record["preference_id"],
            **context, confidence=SOURCE_CONFIDENCE["explicit_preference"],
            observed_at=source.get("ts"),
            evidence_event_uids=sorted({e["event_uid"] for e in record["preference_evidence"]}),
            scope=scope, statement=record["preference_statement"],
            seq=source["seq"], status="observed" if record["status"] == "observed" else "pending",
            source_feature=record["preference_type"], polarity=record["polarity"],
            operation=record["operation"], missing_reasons=record["missing_reasons"],
            history=record["preference_history"],
        ))
    return [result[key] for key in sorted(result)]


def build_preference_evidence(preferences, instructions, sessions, task_by_event=None,
                              cluster_by_session=None):
    explicit = explicit_to_preference_evidence(preferences, sessions, task_by_event, cluster_by_session)
    historical = instruction_to_preference_evidence(instructions, sessions, task_by_event, cluster_by_session)
    if explicit is None and historical is None:
        return None
    direct = {}
    for item in explicit or []:
        if item["status"] == "observed" and item["operation"] != "revoke":
            for event in item["evidence_event_uids"]:
                direct[event, item["dimension"], item["value"], item["polarity"]] = item["evidence_id"]
    for item in historical or []:
        key = (item["evidence_event_uids"][0], item["dimension"], item["value"], item["polarity"])
        item["corroborates_evidence_id"] = direct.get(key)
    return sorted((explicit or []) + (historical or []), key=lambda e: e["evidence_id"])


def _task_key(item):
    if not item.get("task_id"):
        return None
    # Only the Task family's canonical assignment establishes cross-session identity.
    return (None if item["task_identity_quality"] == "task_family" else item["session_uid"], item["task_id"])


def summarize_preference_evidence(evidence, instructions=None, sessions=(), task_by_event=None):
    """Task-deduplicated historical support, kept separate from explicit authority.

    Rates describe observed requests in the selected input, not preference strength.
    A task without a request is unknown, never a vote for the opposite value.
    """
    if evidence is None:
        return {"status": "unavailable", "evidence_count": None, "by_source_type": None,
                "observed_tasks": None, "dimensions": None}
    rows = list({e["evidence_id"]: e for e in evidence}.values())
    session_map = {s["session_uid"]: s for s in sessions if s.get("kind") == "main"}
    task_keys = set()
    for row in instructions or []:
        if row["session_uid"] in session_map and not set(row.get("unknown_reasons", [])) & {
                "text_truncated", "text_unavailable", "no_direct_text"}:
            key = _task_key(_context(row, session_map, task_by_event, None))
            if key is not None:
                task_keys.add(key)
    dimensions = []
    for dimension in sorted({e["dimension"] for e in rows}):
        own = [e for e in rows if e["dimension"] == dimension]
        historical = [e for e in own if e["source_type"] == "task_instruction"]
        groups = defaultdict(list)
        for item in historical:
            if item["status"] == "observed" and not item["corroborates_evidence_id"]:
                key = _task_key(item)
                if key is not None:
                    groups[key].append(item)
        supports, conflicts = defaultdict(list), []
        for key, items in sorted(groups.items(), key=lambda pair: str(pair[0])):
            values = {e["value"] for e in items}
            if (dimension == "autonomy" and len(values) > 1 or
                    dimension == "execution_style" and "execute_first" in values and len(values) > 1):
                conflicts.append({"task_id": key[1], "evidence_ids": sorted(e["evidence_id"] for e in items)})
                continue
            for value in sorted(values):
                supports[value].append(items)
        values = []
        for value, tasks in sorted(supports.items()):
            refs = [e for task in tasks for e in task if e["value"] == value]
            values.append({"value": value, "support_tasks": len(tasks),
                           "support_sessions": len({e["session_uid"] for e in refs}),
                           "evidence_ids": sorted({e["evidence_id"] for e in refs}),
                           "task_rate": len(tasks) / len(task_keys) if task_keys else None})
        inferred = [e for e in own if e["source_type"] == "semantic_task_instruction"]
        inferred_values = []
        for value in sorted({e["value"] for e in inferred if e["status"] == "observed" and e["value"] is not None}):
            refs = [e for e in inferred if e["status"] == "observed" and e["value"] == value]
            inferred_values.append({"value": value, "support_tasks": len({_task_key(e) for e in refs}),
                                    "evidence_ids": sorted(e["evidence_id"] for e in refs),
                                    "quality": "model_inferred", "calibrated_probability": None})
        dimensions.append({"dimension": dimension,
                           "explicit_evidence_ids": sorted(e["evidence_id"] for e in own
                                                           if e["source_type"] == "explicit_preference"),
                           "historical_values": values, "conflicting_tasks": conflicts,
                           "pending_evidence_ids": sorted(e["evidence_id"] for e in historical if e["status"] == "pending"),
                           **({"inferred_values": inferred_values,
                               "inferred_pending_evidence_ids": sorted(e["evidence_id"] for e in inferred if e["status"] == "pending")}
                              if inferred else {})})
    return {"status": "observed" if rows else "no_evidence", "evidence_count": len(rows),
            "by_source_type": dict(sorted(Counter(e["source_type"] for e in rows).items())),
            "observed_tasks": len(task_keys) if instructions is not None else None,
            "dimensions": dimensions,
            "confidence_semantics": "fixed evidence precedence, not calibrated correctness probability",
            "counting": "one task support per dimension/value; explicit evidence is a separate authority tier",
            "rate_semantics": "requested tasks / observed tasks; absent requests are unknown, not opposite preferences"}
