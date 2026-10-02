"""One feature engine for CLI, API, session rows and project aggregates."""

from collections import Counter, defaultdict
from dataclasses import asdict

from ..models import stable_id
from ..recommend.service import recommend as recommend_resources
from . import FEATURE_VERSION
from .common import human
from .context import AnalysisContext, Record
from .dictionary import FEATURES
from .features import activity, session_features, tool_summary, usage, workflow
from .inputs import AnalysisInputBundle, Scope, legacy_bundle, metadata
from .instruction import (
    INSTRUCTION_VERSION,
    summarize_control_patterns,
)
from .outcome_subjective import aggregate_subjective_outcomes
from .preference import PREFERENCE_EVIDENCE_VERSION, PREFERENCE_VERSION
from .semantic import analyze_semantics
from .task.representation import representation
from .task.taxonomy import TAXONOMY_VERSION


def _session_rows(
    context: AnalysisContext,
    meta: Record,
    instruction_groups: dict,
    task_ids: dict,
    preference_ids: dict,
    preference_evidence_ids: dict,
    with_text: bool,
) -> tuple[list[Record], Record, int]:
    """Assemble session details and optional text coordinates from one selection."""
    bundle, scope = context.bundle, context.scope
    sessions, events, calls, model_calls = (
        context.sessions,
        context.events,
        context.calls,
        context.model_calls,
    )
    main_ids, diagnostics = context.main_ids, context.diagnostics
    supported, event_status = context.supported_kinds, context.event_status
    complete_models = bundle.coverage.get("model_calls", {}).get("status") == "available"
    groups, call_groups, children = context.event_groups, context.call_groups, context.children
    instruction_available = bundle.events is not None
    semantic_events = events if instruction_available else None
    rows, entities = [], []
    for s in sessions:
        sid = s["session_uid"]
        if s.get("kind") in ("subagent", "workflow_agent"):
            continue
        included = {sid} | (children[sid] if scope.include_children else set())
        own = groups[sid]
        root_events = [e for member in sorted(included) for e in groups[member]]
        context_events = [e for e in diagnostics["context_events"] if e["session_uid"] in included]
        root_calls = (
            None
            if calls is None
            else [c for member in sorted(included) for c in call_groups[member]]
        )
        data = session_features(
            s, own, root_calls, main_ids, supported, event_status, scope.display_timezone, with_workflow=False
        )
        data["workflow"] = workflow(root_events + context_events, root_calls, main_ids, supported)
        data["usage"] = usage(
            None if model_calls is None else context.members(included, "models"),
            root_events,
            [p for p in sessions if p["session_uid"] in included],
            scope,
            complete_models,
        )
        data["tools"] = tool_summary(
            root_calls, bundle.coverage.get("tool_calls", {}).get("status", "partial")
        )
        if root_calls == [] and data["tools"]["status"] != "available":
            data["features"]["tool_call_count"] = None
        data["instruction"] = {
            "schema_version": INSTRUCTION_VERSION,
            "records": instruction_groups[sid] if instruction_available else None,
            "summary": summarize_control_patterns(
                instruction_groups[sid], source_available=instruction_available
            ),
        }
        data["coverage"] = meta["coverage"]
        data["bottleneck_features"] = context.families(included)
        row = {
            **s,
            **data,
            "included_session_uids": sorted(included),
            "cluster_id": None,
            "novelty": None,
            "embedding_x": None,
            "embedding_y": None,
            "task_ids": task_ids[sid] if semantic_events is not None else None,
            "preference_ids": preference_ids[sid] if semantic_events is not None else None,
            "preference_evidence_ids": preference_evidence_ids[sid]
            if semantic_events is not None
            else None,
        }
        rows.append(row)
        prompts = [e for e in own if human(e, main_ids) and e.get("text")]
        if prompts:
            # Session text is available only after its last contributing prompt.
            # If any prompt is unclocked, temporal novelty is unavailable.
            ts = (
                max(e["ts"] for e in prompts)
                if all(e.get("ts") is not None for e in prompts)
                else None
            )
            entities.append(
                {"entity_id": sid, "text": "\n".join(e["text"] for e in prompts), "ts": ts}
            )
    text = (
        representation(entities)
        if with_text
        else {"status": "excluded", "coordinates": None, "reason": "调用方禁用文本表示"}
    )
    projections = {p["entity_id"]: p for p in text.get("coordinates") or []}
    for row in rows:
        row.update(
            {k: v for k, v in projections.get(row["session_uid"], {}).items() if k != "entity_id"}
        )
    return rows, text, len(entities)


def _project_rows(
    context: AnalysisContext, rows: list[Record], instruction_groups: dict, tool_status: str
) -> list[Record]:
    """Recompute project denominators instead of averaging session rates."""
    bundle, scope = context.bundle, context.scope
    sessions, events, calls, model_calls = (
        context.sessions,
        context.events,
        context.calls,
        context.model_calls,
    )
    main_ids = context.main_ids
    event_status = context.event_status
    complete_models = bundle.coverage.get("model_calls", {}).get("status") == "available"
    instruction_available = bundle.events is not None
    projects = []
    by_project = defaultdict(list)
    for r in rows:
        by_project[(r.get("project_id"), r.get("legacy_project_id"))].append(r)
    names = {
        (p.get("project_id"), p.get("legacy_project_id")): p.get("name")
        for p in bundle.projects or []
    }
    for (pid, legacy), rs in sorted(by_project.items(), key=lambda pair: str(pair[0])):
        ids = {sid for r in rs for sid in r["included_session_uids"]}
        pcs = None if calls is None else [c for c in calls if c["session_uid"] in ids]
        pe = [e for e in events if e["session_uid"] in ids]
        ph = sum(human(e, main_ids) for e in pe)
        pu = sum(r["unknown_counts"]["human_origin"] for r in rs)
        projects.append(
            {
                "project_id": pid,
                "legacy_project_id": legacy,
                "name": names.get((pid, legacy)),
                "identity_quality": "canonical" if pid is not None else "legacy_path",
                "session_count": len(rs),
                "main_session_count": sum(r["kind"] == "main" for r in rs),
                "human_message_count": ph if ph or not pu else None,
                "effective_samples": {"human_messages": ph},
                "unknown_counts": {"human_origin": pu},
                "turn_count": len(
                    {(e["session_uid"], e["turn_uid"]) for e in pe if e.get("turn_uid")}
                )
                or None,
                "correction_signal_count": sum(
                    r["features"]["correction_signal_count"] or 0 for r in rs
                )
                if ph
                else None,
                "subjective_outcomes": aggregate_subjective_outcomes(
                    [r["subjective_outcomes"] for r in rs], event_status
                ),
                "activity_rhythm": activity([s for s in sessions if s["session_uid"] in ids], pe,
                    pcs, None if model_calls is None else context.members(ids, "models"),
                    main_ids & ids, scope) if bundle.events is not None else None,
                "tools": tool_summary(pcs, tool_status),
                "usage": usage(
                    None
                    if model_calls is None
                    else [c for c in model_calls if c["session_uid"] in ids],
                    pe,
                    [s for s in sessions if s["session_uid"] in ids],
                    scope,
                    complete_models,
                ),
                "bottleneck_features": context.families(ids),
                "instruction": summarize_control_patterns(
                    [record for r in rs for record in instruction_groups[r["session_uid"]]],
                    source_available=instruction_available,
                ),
                "cluster_distribution": dict(
                    Counter(str(r["cluster_id"]) for r in rs if r["cluster_id"] is not None)
                ),
            }
        )
    return projects


def analyze_bundle(
    bundle: AnalysisInputBundle,
    scope: Scope | None = None,
    with_text: bool = True,
    *,
    with_recommendations: bool = True,
) -> Record:
    """Compute all eight families; optional recommendation work stays at the boundary."""
    scope = scope or Scope()
    context = AnalysisContext.select(bundle, scope)
    return analyze_context(context, with_text, with_recommendations=with_recommendations)


def analyze_context(
    context: AnalysisContext, with_text: bool = True, *, with_recommendations: bool = True
) -> Record:
    """Compose family results from an already selected, indexed request."""
    bundle, scope = context.bundle, context.scope
    sessions, events, calls, model_calls = (
        context.sessions,
        context.events,
        context.calls,
        context.model_calls,
    )
    diagnostics = context.diagnostics
    meta = metadata(bundle, scope, diagnostics)
    # Source coverage is retained separately from row counts in this selection.
    meta["source_coverage"] = meta["coverage"]
    meta["coverage"] = {k: dict(v) for k, v in bundle.coverage.items()}
    for name, items in (
        ("sessions", sessions),
        ("events", events if bundle.events is not None else None),
        ("tool_calls", calls),
        ("model_calls", model_calls),
    ):
        meta["coverage"].setdefault(name, {"status": "unavailable"})["rows"] = (
            len(items) if items is not None else None
        )
    main_ids = {s["session_uid"] for s in sessions if s.get("kind") == "main"}
    semantic = analyze_semantics(context)
    tasks, preferences = semantic.tasks, semantic.preferences
    instruction_records, instruction_groups = (
        semantic.instruction_records,
        semantic.instruction_groups,
    )
    instruction_summary = semantic.instruction_summary
    instruction_available = bundle.events is not None
    complete_models = bundle.coverage.get("model_calls", {}).get("status") == "available"
    supported, event_status = context.supported_kinds, context.event_status
    rows, text, text_count = _session_rows(
        context,
        meta,
        instruction_groups,
        semantic.task_ids,
        semantic.preference_ids,
        semantic.preference_evidence_ids,
        with_text,
    )
    projections = {p["entity_id"]: p for p in text.get("coordinates") or []}
    for item in preferences["evidence"] or []:
        item["cluster_id"] = projections.get(item["session_uid"], {}).get("cluster_id")
    all_tools = tool_summary(calls, bundle.coverage.get("tool_calls", {}).get("status", "partial"))
    all_workflow = workflow(events + diagnostics["context_events"], calls, main_ids, supported)
    all_usage = usage(model_calls, events, sessions, scope, complete_models)
    unknown_origin = sum(r["unknown_counts"]["human_origin"] for r in rows)
    human_count = sum(human(e, main_ids) for e in events)
    correction = sum(r["features"]["correction_signal_count"] or 0 for r in rows)
    counts = {
        "sessions": len(sessions),
        "main_sessions": len(main_ids),
        "session_kind_unknown": sum(s.get("kind") == "unknown" for s in sessions),
        "human_messages": human_count if human_count or not unknown_origin else None,
        "human_origin_unknown": unknown_origin,
        "events": len(events),
        "turns": len({(e["session_uid"], e["turn_uid"]) for e in events if e.get("turn_uid")})
        or None,
        "correction_signals": correction if human_count else None,
        "correction_signal_rate": correction / human_count if human_count else None,
    }
    meta["coverage"]["human_origin"] = {
        **meta["coverage"].get("human_origin", {}),
        "status": "partial" if unknown_origin else "available",
        "rows": human_count,
        "unknown_rows": unknown_origin,
    }
    meta["coverage"]["sample_exclusions"] = {
        "status": "excluded",
        "rows": sum(diagnostics["excluded_sessions"].values()),
        "reasons": diagnostics["excluded_sessions"],
    }
    languages = Counter()
    for r in rows:
        languages.update({v["language"]: v["count"] for v in r["language_signals"]})
    rhythm = activity(sessions, events, calls, model_calls, main_ids, scope)
    projects = _project_rows(context, rows, instruction_groups, all_tools["status"])
    correction_terms = Counter(
        term for r in rows for signal in r["correction_signals"] for term in signal["terms"]
    )
    text["correction_terms"] = dict(correction_terms)
    if bundle.events is None:
        meta["coverage"]["human_origin"] = {
            "status": "unavailable",
            "rows": None,
            "unknown_rows": None,
        }
        counts.update(events=None, human_messages=None, turns=None, correction_signals=None)
        for row in rows:
            for key in row["features"]:
                if key != "tool_call_count":
                    row["features"][key] = None
            row["prompt_structure"] = None
            row["subjective_outcome_candidates"] = None
            row["workflow"] = None
        all_workflow = {"status": "unavailable", "transitions": None, "sequences": None}
        rhythm = None
    result = {
        **meta,
        "feature_schema_version": FEATURE_VERSION,
        "feature_dictionary": FEATURES,
        "analysis_digest": stable_id(
            bundle.versions.get("content_digest"),
            asdict(scope),
            FEATURE_VERSION,
            INSTRUCTION_VERSION,
            TAXONOMY_VERSION,
            PREFERENCE_VERSION,
            PREFERENCE_EVIDENCE_VERSION,
        ),
        "effective_samples": {
            "main_sessions": len(main_ids),
            "human_messages": human_count,
            "tools": len(calls) if calls is not None else None,
            "text_sessions": text_count,
        },
        "unknown_counts": {
            "human_origin": unknown_origin,
            "session_kind": counts["session_kind_unknown"],
            "timestamp": diagnostics["time_unknown_events"],
            "model_calls": None if model_calls is None else 0,
        },
        "overview": {
            "instruction": instruction_summary,
            "counts": counts,
            "usage": all_usage,
            "activity_rhythm": rhythm,
            "subjective_outcomes": aggregate_subjective_outcomes(
                [r["subjective_outcomes"] for r in rows], event_status
            ),
            "top_tools": (all_tools["by_tool"] or [])[:10]
            if all_tools["by_tool"] is not None
            else None,
            "top_languages": [
                {"language": k, "count": n, "basis": "file_extension_in_human_text"}
                for k, n in languages.most_common()
            ]
            if bundle.events is not None and (human_count or not unknown_origin)
            else None,
        },
        "sessions": rows,
        "tools": {**all_tools, "transitions": all_workflow["transitions"]},
        "workflow": all_workflow,
        "projects": projects,
        "text": text,
        "bottleneck_features": context.families(set(context.session_map)),
        "tasks": tasks,
        "preferences": preferences,
        "instruction": {
            "schema_version": INSTRUCTION_VERSION,
            "records": instruction_records if instruction_available else None,
            "summary": instruction_summary,
        },
        "limitations": [
            "日志跨度不是实际工作时长",
            "词面纠偏和结构约束只是代理信号",
            "缺少事件不等于没有发生；未知保持 null",
            "聚类和坐标不带人格或任务成功含义",
        ],
    }
    from .products.contracts import RULE_VERSIONS
    from .products.lexical import lexical_analysis
    from .products.statistics import statistical_analysis

    result["inventory"] = bundle.inventory
    result["inventory_scans"] = bundle.inventory_scans
    result["lexical"] = lexical_analysis(context)
    result["statistics"] = statistical_analysis(context, result)
    result["analysis_methods"] = dict(RULE_VERSIONS)
    result["analysis_digest"] = stable_id(result["analysis_digest"], RULE_VERSIONS, with_text)
    if with_recommendations:
        result["bottleneck_recommendations"] = recommend_resources(result)
    return result


def analyze_store(store, scope: Scope | None = None, with_text: bool = True) -> Record:
    """Adapt canonical or legacy storage before entering the pure analysis engine."""
    from .history import recorded

    scope = scope or Scope()
    def compute():
        bundle = store.analysis_bundle(scope) if hasattr(store, "analysis_bundle") else legacy_bundle(store)
        return analyze_bundle(bundle, scope, with_text)
    return recorded(store, "features", {"scope": asdict(scope), "with_text": with_text}, compute)


def response_section(result: Record, key: str) -> Record:
    """Attach shared scope and coverage metadata to an API section."""
    shared = {
        k: result[k]
        for k in (
            "input_contract",
            "feature_schema_version",
            "scope",
            "coverage",
            "versions",
            "sample_boundary",
            "selection",
            "effective_samples",
            "unknown_counts",
            "analysis_digest",
            "feature_dictionary",
            "source_coverage",
        )
    }
    return {**shared, key: result[key]}
