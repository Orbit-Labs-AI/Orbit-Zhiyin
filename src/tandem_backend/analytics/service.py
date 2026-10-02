"""One feature engine for CLI, API, session rows and project aggregates."""

from collections import Counter, defaultdict
from dataclasses import asdict

from ..models import stable_id
from . import FEATURE_VERSION
from .bottleneck import analyze_bottleneck
from .common import human
from .dictionary import FEATURES
from .features import activity, session_features, tool_summary, usage, workflow
from .inputs import KINDS, Scope, legacy_bundle, metadata, select
from .instruction import (
    INSTRUCTION_VERSION,
    extract_instruction_constraints,
    summarize_control_patterns,
)
from .outcome_subjective import aggregate_subjective_outcomes
from .preference import extract_explicit_preferences, summarize_preferences
from .task import segment_tasks, summarize_task_distribution
from .task.representation import representation


def analyze_bundle(bundle, scope=None, with_text=True):
    scope = scope or Scope()
    sessions, events, calls, model_calls, diagnostics = select(bundle, scope)
    meta = metadata(bundle, scope, diagnostics)
    # Source coverage is retained separately from row counts in this selection.
    meta["source_coverage"] = meta["coverage"]
    meta["coverage"] = {k: dict(v) for k, v in bundle.coverage.items()}
    for name, items in (("sessions", sessions), ("events", events if bundle.events is not None else None),
                        ("tool_calls", calls), ("model_calls", model_calls)):
        meta["coverage"].setdefault(name, {"status": "unavailable"})["rows"] = len(items) if items is not None else None
    main_ids = {s["session_uid"] for s in sessions if s.get("kind") == "main"}
    semantic_events = events if bundle.events is not None else None
    tasks = segment_tasks(semantic_events, sessions)
    if semantic_events is None:
        tasks["records"] = None
    preferences = extract_explicit_preferences(semantic_events, sessions, tasks.pop("task_by_event"))
    tasks["summary"] = summarize_task_distribution(tasks["records"], asdict(scope))
    preferences["summary"] = summarize_preferences(preferences["records"], asdict(scope))
    task_ids, preference_ids = defaultdict(list), defaultdict(list)
    for task in tasks["records"] or []:
        for sid in task["related_session_ids"]:
            task_ids[sid].append(task["task_id"])
    for preference in preferences["records"] or []:
        sid = preference["preference_evidence"][0]["session_uid"]
        preference_ids[sid].append(preference["preference_id"])
    instruction_records = extract_instruction_constraints(events, main_ids=main_ids)
    instruction_groups = defaultdict(list)
    for record in instruction_records:
        instruction_groups[record["session_uid"]].append(record)
    instruction_available = bundle.events is not None
    instruction_summary = summarize_control_patterns(
        instruction_records, source_available=instruction_available)
    complete_models = bundle.coverage.get("model_calls", {}).get("status") == "available"
    groups, call_groups, children = defaultdict(list), defaultdict(list), defaultdict(set)
    for s in sessions:
        if s.get("kind") in ("subagent", "workflow_agent") and s.get("root_uid"):
            children[s["root_uid"]].add(s["session_uid"])
    for e in events:
        groups[e["session_uid"]].append(e)
    for c in calls or []:
        call_groups[c["session_uid"]].append(c)
    supported = set(KINDS.values()) if bundle.versions.get("storage") == "legacy-json-ledger" else None
    event_status = "unavailable" if bundle.events is None else bundle.coverage.get("events", {}).get("status", "partial")
    rows, entities = [], []
    for s in sessions:
        sid = s["session_uid"]
        if s.get("kind") in ("subagent", "workflow_agent"):
            continue
        included = {sid} | (children[sid] if scope.include_children else set())
        own = groups[sid]
        root_events = [e for member in sorted(included) for e in groups[member]]
        context_events = [e for e in diagnostics["context_events"] if e["session_uid"] in included]
        root_calls = None if calls is None else [c for member in sorted(included) for c in call_groups[member]]
        data = session_features(s, own, root_calls, main_ids, supported, event_status)
        data["workflow"] = workflow(root_events + context_events, root_calls, main_ids, supported)
        data["usage"] = usage(None if model_calls is None else [c for c in model_calls if c["session_uid"] in included],
                              root_events, [p for p in sessions if p["session_uid"] in included], scope, complete_models)
        data["tools"] = tool_summary(root_calls, bundle.coverage.get("tool_calls", {}).get("status", "partial"))
        if root_calls == [] and data["tools"]["status"] != "available":
            data["features"]["tool_call_count"] = None
        data["instruction"] = {
            "schema_version": INSTRUCTION_VERSION,
            "records": instruction_groups[sid] if instruction_available else None,
            "summary": summarize_control_patterns(
                instruction_groups[sid], source_available=instruction_available),
        }
        data["coverage"] = meta["coverage"]
        data["bottleneck_features"] = analyze_bottleneck(
            [p for p in sessions if p["session_uid"] in included], root_events if bundle.events is not None else None,
            root_calls, None if model_calls is None else [c for c in model_calls if c["session_uid"] in included],
            main_ids, scope, bundle.coverage, context_events, supported)
        row = {**s, **data, "included_session_uids": sorted(included), "cluster_id": None,
               "novelty": None, "embedding_x": None, "embedding_y": None,
               "task_ids": task_ids[sid] if semantic_events is not None else None,
               "preference_ids": preference_ids[sid] if semantic_events is not None else None}
        rows.append(row)
        prompts = [e for e in own if human(e, main_ids) and e.get("text")]
        if prompts:
            # Session text is available only after its last contributing prompt.
            # If any prompt is unclocked, temporal novelty is unavailable.
            ts = max(e["ts"] for e in prompts) if all(e.get("ts") is not None for e in prompts) else None
            entities.append({"entity_id": sid, "text": "\n".join(e["text"] for e in prompts), "ts": ts})
    text = representation(entities) if with_text else {"status": "excluded", "coordinates": None,
                                                       "reason": "调用方禁用文本表示"}
    projections = {p["entity_id"]: p for p in text.get("coordinates") or []}
    for row in rows:
        row.update({k: v for k, v in projections.get(row["session_uid"], {}).items() if k != "entity_id"})
    all_tools = tool_summary(calls, bundle.coverage.get("tool_calls", {}).get("status", "partial"))
    all_workflow = workflow(events + diagnostics["context_events"], calls, main_ids, supported)
    all_usage = usage(model_calls, events, sessions, scope, complete_models)
    unknown_origin = sum(r["unknown_counts"]["human_origin"] for r in rows)
    human_count = sum(human(e, main_ids) for e in events)
    correction = sum(r["features"]["correction_signal_count"] or 0 for r in rows)
    counts = {"sessions": len(sessions), "main_sessions": len(main_ids),
              "session_kind_unknown": sum(s.get("kind") == "unknown" for s in sessions),
              "human_messages": human_count if human_count or not unknown_origin else None,
              "human_origin_unknown": unknown_origin, "events": len(events),
              "turns": len({(e["session_uid"], e["turn_uid"]) for e in events if e.get("turn_uid")}) or None,
              "correction_signals": correction if human_count else None,
              "correction_signal_rate": correction / human_count if human_count else None}
    meta["coverage"]["human_origin"] = {**meta["coverage"].get("human_origin", {}),
        "status": "partial" if unknown_origin else "available", "rows": human_count, "unknown_rows": unknown_origin}
    meta["coverage"]["sample_exclusions"] = {"status": "excluded",
        "rows": sum(diagnostics["excluded_sessions"].values()), "reasons": diagnostics["excluded_sessions"]}
    languages = Counter()
    for r in rows:
        languages.update({v["language"]: v["count"] for v in r["language_signals"]})
    rhythm = activity(sessions, events, calls, model_calls, main_ids, scope)
    projects = []
    by_project = defaultdict(list)
    for r in rows:
        by_project[(r.get("project_id"), r.get("legacy_project_id"))].append(r)
    names = {(p.get("project_id"), p.get("legacy_project_id")): p.get("name") for p in bundle.projects or []}
    for (pid, legacy), rs in sorted(by_project.items(), key=lambda pair: str(pair[0])):
        ids = {sid for r in rs for sid in r["included_session_uids"]}
        pcs = None if calls is None else [c for c in calls if c["session_uid"] in ids]
        pe = [e for e in events if e["session_uid"] in ids]
        ph = sum(human(e, main_ids) for e in pe)
        pu = sum(r["unknown_counts"]["human_origin"] for r in rs)
        projects.append({"project_id": pid, "legacy_project_id": legacy, "name": names.get((pid, legacy)),
            "identity_quality": "canonical" if pid is not None else "legacy_path",
            "session_count": len(rs), "main_session_count": sum(r["kind"] == "main" for r in rs),
            "human_message_count": ph if ph or not pu else None,
            "effective_samples": {"human_messages": ph}, "unknown_counts": {"human_origin": pu},
            "turn_count": len({(e["session_uid"], e["turn_uid"]) for e in pe if e.get("turn_uid")}) or None,
            "correction_signal_count": sum(r["features"]["correction_signal_count"] or 0 for r in rs) if ph else None,
            "subjective_outcomes": aggregate_subjective_outcomes([r["subjective_outcomes"] for r in rs], event_status),
            "tools": tool_summary(pcs, all_tools["status"]),
            "usage": usage(None if model_calls is None else [c for c in model_calls if c["session_uid"] in ids],
                           pe, [s for s in sessions if s["session_uid"] in ids], scope, complete_models),
            "bottleneck_features": analyze_bottleneck(
                [s for s in sessions if s["session_uid"] in ids], pe if bundle.events is not None else None, pcs,
                None if model_calls is None else [c for c in model_calls if c["session_uid"] in ids],
                main_ids, scope, bundle.coverage,
                [e for e in diagnostics["context_events"] if e["session_uid"] in ids], supported),
            "instruction": summarize_control_patterns(
                [record for r in rs for record in instruction_groups[r["session_uid"]]],
                source_available=instruction_available),
            "cluster_distribution": dict(Counter(str(r["cluster_id"]) for r in rs if r["cluster_id"] is not None))})
    correction_terms = Counter(term for r in rows for signal in r["correction_signals"] for term in signal["terms"])
    text["correction_terms"] = dict(correction_terms)
    if bundle.events is None:
        meta["coverage"]["human_origin"] = {"status": "unavailable", "rows": None, "unknown_rows": None}
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
    return {**meta, "feature_schema_version": FEATURE_VERSION, "feature_dictionary": FEATURES,
            "analysis_digest": stable_id(bundle.versions.get("content_digest"), asdict(scope), FEATURE_VERSION, INSTRUCTION_VERSION),
            "effective_samples": {"main_sessions": len(main_ids), "human_messages": human_count,
                                  "tools": len(calls) if calls is not None else None, "text_sessions": len(entities)},
            "unknown_counts": {"human_origin": unknown_origin, "session_kind": counts["session_kind_unknown"],
                               "timestamp": diagnostics["time_unknown_events"], "model_calls": None if model_calls is None else 0},
            "overview": {"instruction": instruction_summary, "counts": counts, "usage": all_usage, "activity_rhythm": rhythm,
                         "subjective_outcomes": aggregate_subjective_outcomes([r["subjective_outcomes"] for r in rows], event_status),
                         "top_tools": (all_tools["by_tool"] or [])[:10] if all_tools["by_tool"] is not None else None,
                         "top_languages": [{"language": k, "count": n, "basis": "file_extension_in_human_text"}
                                           for k, n in languages.most_common()] if bundle.events is not None and (human_count or not unknown_origin) else None},
            "sessions": rows, "tools": {**all_tools, "transitions": all_workflow["transitions"]},
            "workflow": all_workflow, "projects": projects, "text": text,
            "bottleneck_features": analyze_bottleneck(sessions, events if bundle.events is not None else None,
                calls, model_calls, main_ids, scope, bundle.coverage, diagnostics["context_events"], supported),
            "tasks": tasks, "preferences": preferences,
            "instruction": {"schema_version": INSTRUCTION_VERSION,
                            "records": instruction_records if instruction_available else None,
                            "summary": instruction_summary},
            "limitations": ["日志跨度不是实际工作时长", "词面纠偏和结构约束只是代理信号",
                            "缺少事件不等于没有发生；未知保持 null", "聚类和坐标不带人格或任务成功含义"]}


def analyze_store(store, scope=None, with_text=True):
    return analyze_bundle(legacy_bundle(store), scope, with_text)


def response_section(result, key):
    shared = {k: result[k] for k in ("input_contract", "feature_schema_version", "scope", "coverage", "versions",
                                   "sample_boundary", "selection", "effective_samples", "unknown_counts", "analysis_digest",
                                   "feature_dictionary", "source_coverage")}
    return {**shared, key: result[key]}
