"""Compose semantic families once, with explicit indexes for session summaries."""

from collections import defaultdict
from dataclasses import asdict, dataclass

from .context import AnalysisContext, Record
from .instruction import extract_instruction_constraints, summarize_control_patterns
from .preference import (
    PREFERENCE_EVIDENCE_VERSION,
    build_preference_evidence,
    extract_explicit_preferences,
    summarize_preference_evidence,
    summarize_preferences,
)
from .task import summarize_task_distribution


@dataclass(frozen=True)
class SemanticAnalysis:
    tasks: Record
    preferences: Record
    instruction_records: list[Record]
    instruction_groups: dict[str, list[Record]]
    instruction_summary: Record
    task_ids: dict[str, list[str]]
    preference_ids: dict[str, list[str]]
    preference_evidence_ids: dict[str, list[str]]


def analyze_semantics(context: AnalysisContext) -> SemanticAnalysis:
    """Extract task, preference and instruction evidence without mutating family returns."""
    events = context.events if context.bundle.events is not None else None
    task_result = context.work_index.task_result
    tasks = {key: value for key, value in task_result.items() if key != "task_by_event"}
    if events is None:
        tasks["records"] = None
    preferences = extract_explicit_preferences(
        events, context.sessions, task_result["task_by_event"]
    )
    tasks["summary"] = summarize_task_distribution(tasks["records"], asdict(context.scope))
    preferences["summary"] = summarize_preferences(preferences["records"], asdict(context.scope))
    task_ids, preference_ids, instruction_groups = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    for task in tasks["records"] or []:
        for sid in task["related_session_ids"]:
            task_ids[sid].append(task["task_id"])
    for preference in preferences["records"] or []:
        preference_ids[preference["preference_evidence"][0]["session_uid"]].append(
            preference["preference_id"]
        )
    records = extract_instruction_constraints(context.events, main_ids=context.main_ids)
    available_records = records if events is not None else None
    preferences["evidence_schema_version"] = PREFERENCE_EVIDENCE_VERSION
    preferences["evidence"] = build_preference_evidence(
        preferences, available_records, context.sessions, task_result["task_by_event"]
    )
    preferences["evidence_summary"] = summarize_preference_evidence(
        preferences["evidence"], available_records, context.sessions, task_result["task_by_event"]
    )
    preference_evidence_ids = defaultdict(list)
    for item in preferences["evidence"] or []:
        preference_evidence_ids[item["session_uid"]].append(item["evidence_id"])
    for record in records:
        instruction_groups[record["session_uid"]].append(record)
    summary = summarize_control_patterns(records, source_available=events is not None)
    return SemanticAnalysis(
        tasks,
        preferences,
        records,
        instruction_groups,
        summary,
        task_ids,
        preference_ids,
        preference_evidence_ids,
    )
