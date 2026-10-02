"""Assemble frontend sections from the eight already-selected feature families."""

from collections import Counter
from copy import deepcopy

from ...models import stable_id
from . import PRESENTATION_VERSION
from .diagnostics import build_diagnostics
from .metrics import activity_view, measure, ranked_counts, unavailable
from .profile import build_profile


def _tokens(usage):
    snapshots = usage.get("cumulative_snapshots") or []
    refs = ([{"session_uid": r["session_uid"], "event_uid": r["event_uid"]} for r in snapshots]
            if usage.get("total_basis") == "cumulative_snapshot" else usage.get("request_evidence", []))
    result = measure(usage.get("total_tokens"), "token", usage.get("total_basis"),
                     status=usage.get("status", "unavailable"),
                     unknown_n=usage.get("token_unknown_call_n"),
                     reason=None if usage.get("total_tokens") is not None else "incomplete_token_coverage",
                     evidence_refs=refs)
    result.update(known_subtotal=usage.get("known_call_tokens"),
                  buckets=usage.get("token_buckets"), semantics=usage.get("token_semantics"),
                  bucket_basis=usage.get("token_bucket_basis"),
                  cumulative_snapshots=snapshots, cumulative_note=usage.get("cumulative_note"))
    return result


def _scoped_task(task, ids, event_ids):
    """Project already-extracted evidence; a shared task cannot lend labels to another project."""
    result = {**task, "related_session_ids": sorted(ids & set(task["related_session_ids"])),
              "human_evidence_ids": [e for e in task["human_evidence_ids"] if e in event_ids],
              "task_boundaries": [b for b in task["task_boundaries"] if b["session_uid"] in ids],
              "session_relations": [r for r in task.get("session_relations", []) if r["session_uid"] in ids],
              "label_evidence": {}, "projection_basis": "selected_session_evidence_only"}
    for field in ("domain", "task_type"):
        evidence = {label: [ref for ref in refs if ref["session_uid"] in ids]
                    for label, refs in task.get("label_evidence", {}).get(field, {}).items()}
        result["label_evidence"][field] = {label: refs for label, refs in evidence.items() if refs}
        result[field] = sorted(result["label_evidence"][field]) or None
    history = [h for h in task.get("task_goal_history", [])
               if (h.get("evidence") or {}).get("session_uid") in ids]
    result["task_goal_history"] = history
    result["task_goal"] = history[-1]["goal"] if history else None
    result["task_title"] = result["task_goal"][:60] if result["task_goal"] else None
    result["expected_artifacts"] = [a for a in task.get("expected_artifacts") or []
                                    if a["evidence"]["session_uid"] in ids] or None
    result["observed_message_count"] = len(result["human_evidence_ids"])
    result["missing_reasons"] = [f for f in ("domain", "task_type") if result[f] is None]
    if result["task_goal"] is None:
        result["missing_reasons"].append("goal_not_observed_in_selected_sessions")
    return result


def _subview(analysis, rows, *, bottleneck, subjective):
    """Reuse existing scoped aggregates; never average session rates or token totals."""
    ids = {r["session_uid"] for r in rows}
    result = {"scope": analysis.get("scope", {}), "coverage": analysis.get("coverage", {}),
              "sessions": rows, "bottleneck_features": bottleneck,
              "overview": {"subjective_outcomes": subjective}}
    for name, predicate in (
        ("tasks", lambda r: bool(ids & set(r["related_session_ids"]))),
        ("instruction", lambda r: r["session_uid"] in ids),
        ("preferences", lambda r: any(e["session_uid"] in ids for e in r["preference_evidence"])),
    ):
        family = analysis.get(name, {})
        records = family.get("records")
        result[name] = {**family, "records": None if records is None else [r for r in records if predicate(r)]}
        if name == "preferences":
            for key in ("candidates", "task_instructions"):
                values = family.get(key)
                result[name][key] = None if values is None else [r for r in values if predicate(r)]
    event_ids = {r["event_uid"] for r in result["instruction"]["records"] or []}
    if result["tasks"]["records"] is not None:
        result["tasks"]["records"] = [_scoped_task(task, ids, event_ids)
                                      for task in result["tasks"]["records"]]
    return result


def _session(row, analysis):
    features = row["features"]
    sub = _subview(analysis, [row], bottleneck=row["bottleneck_features"],
                   subjective=row["subjective_outcomes"])
    diagnostic = build_diagnostics(sub)
    event_status = analysis.get("coverage", {}).get("events", {}).get("status", "unavailable")
    return {
        "session_uid": row["session_uid"], "title": row.get("title"),
        "kind": row.get("kind"), "agent": row.get("agent"),
        "project_id": row.get("project_id"), "legacy_project_id": row.get("legacy_project_id"),
        "last_activity_ts": features.get("last_observed_ts"),
        "time_basis": "last selected observed event, unknown timestamps sort last",
        "task_ids": row.get("task_ids"),
        "turns": measure(features.get("turn_count"), "turn", "distinct session_uid/turn_uid",
                         status=event_status, unknown_n=row.get("unknown_counts", {}).get("turn_identity")),
        "messages": measure(features.get("user_message_count"), "human_message",
                            "confirmed human-origin messages", status=event_status,
                            unknown_n=row.get("unknown_counts", {}).get("human_origin")),
        "tool_calls": diagnostic["tools"]["call_count"],
        "correction_rate": diagnostic["correction_rate"],
        "tools": diagnostic["tools"], "outcomes": diagnostic["outcomes"],
        "tokens": _tokens(row["usage"]),
        "observed_session_span_ms": measure(features.get("observed_session_span_ms"), "ms",
                                             "last_event-first_event; not human work duration",
                                             status=event_status),
        "findings": diagnostic["findings"], "suggestions": diagnostic["recommendations"],
    }


def _timeline(tasks):
    if tasks is None:
        return None
    rows = []
    for task in tasks:
        for boundary in task["task_boundaries"]:
            start, end = boundary.get("start") or {}, boundary.get("end") or {}
            rows.append({"task_id": task["task_id"], "session_uid": boundary["session_uid"],
                         "title": task.get("task_title"), "goal": task.get("task_goal"),
                         "domain": task.get("domain"), "task_type": task.get("task_type"),
                         "expected_artifacts": task.get("expected_artifacts"),
                         "start_ts": start.get("ts"), "end_ts": end.get("ts"),
                         "start_seq": start.get("seq"), "end_seq": end.get("seq"),
                         "boundary_status": boundary.get("status"),
                         "end_reason": boundary.get("end_reason"),
                         "evidence_refs": [v for v in (start, end) if v]})
    return sorted(rows, key=lambda r: (r["start_ts"] is None, r["start_ts"] or 0,
                                       r["session_uid"], r["start_seq"] or 0, r["task_id"]))


def _project(project, analysis):
    rows = [r for r in analysis["sessions"]
            if (r.get("project_id"), r.get("legacy_project_id")) ==
               (project.get("project_id"), project.get("legacy_project_id"))]
    sub = _subview(analysis, rows, bottleneck=project["bottleneck_features"],
                   subjective=project["subjective_outcomes"])
    sub["scope"] = {**analysis["scope"],
                    "project_ids": [project["project_id"]] if project.get("project_id") is not None else None,
                    "legacy_project_ids": [project["legacy_project_id"]] if project.get("legacy_project_id") is not None else None}
    diagnostic = build_diagnostics(sub)
    agents = Counter(r["agent"] for r in rows if r.get("agent") and r.get("kind") == "main")
    unknown = sum(not r.get("agent") for r in rows if r.get("kind") == "main")
    return {
        "project_id": project.get("project_id"), "legacy_project_id": project.get("legacy_project_id"),
        "name": project.get("name"), "session_count": project["main_session_count"],
        "turn_count": project["turn_count"], "messages": project["human_message_count"],
        "tokens": _tokens(project["usage"]),
        "agent_composition": ranked_counts(dict(agents), basis="main_session", unknown_n=unknown),
        "profile": build_profile(sub), "diagnostics": diagnostic,
        "completion": unavailable("no_complete_project_task_inventory", "ratio"),
        "declared_acceptance_sets": diagnostic["outcomes"]["objective"].get("declared_task_results"),
        "execution_time": (unavailable("tool_source_excluded", "ms")
                           if diagnostic["tools"]["status"] == "excluded" else
                           project["bottleneck_features"]["cost_time"].get("durations")),
        "configuration_coverage": unavailable("no_versioned_configuration_inventory"),
        "meaning": "验收结果仅覆盖声明的验收集合；不能用其通过率或工具成功率替代项目完成度。",
    }


def build_presentation(analysis):
    """One immutable display snapshot. Input is analyze_bundle/analyze_store's result."""
    diagnostic = build_diagnostics(analysis)
    profile = build_profile(analysis)
    overview = analysis["overview"]
    counts = overview["counts"]
    scope = analysis["scope"]
    coverage = analysis["coverage"]
    events = coverage.get("events", {}).get("status", "unavailable")
    session_status = coverage.get("sessions", {}).get("status", "unavailable")
    language_counts = None if overview["top_languages"] is None else {
        r["language"]: r["count"] for r in overview["top_languages"]}
    correction_terms = analysis.get("text", {}).get("correction_terms") if events != "unavailable" else None
    sessions = [_session(row, analysis) for row in analysis["sessions"]]
    sessions.sort(key=lambda r: (r["last_activity_ts"] is None,
                                 -(r["last_activity_ts"] or 0), r["session_uid"]))
    work_duration = unavailable("human_work_duration_is_not_observed", "ms")
    result = {
        "schema_version": PRESENTATION_VERSION,
        "source_feature_version": analysis.get("feature_schema_version"),
        "source_analysis_digest": analysis.get("analysis_digest"),
        "presentation_digest": stable_id(analysis.get("analysis_digest"), PRESENTATION_VERSION),
        "scope": scope, "coverage": coverage, "selection": analysis.get("selection"),
        "family_versions": {
            "task": analysis["tasks"].get("family_version"),
            "instruction": analysis["instruction"].get("schema_version"),
            "preference": analysis["preferences"].get("family_version"),
            "bottleneck": analysis["bottleneck_features"].get("schema_version"),
        },
        "overview": {
            "sessions": measure(counts["main_sessions"], "main_session", "distinct confirmed main_session_uid",
                                status=session_status, unknown_n=counts.get("session_kind_unknown")),
            "messages": measure(counts["human_messages"], "human_message", "confirmed human-origin messages",
                                status=events, unknown_n=counts.get("human_origin_unknown")),
            "collaboration_duration": work_duration,
            "correction_rate": diagnostic["correction_rate"],
            "tokens": _tokens(overview["usage"]),
            "profile_summary": profile.get("headline"),
            "bottleneck_summary": diagnostic["findings"][:1],
            "summary_method": "deterministic evidence templates; no generated or psychological claims",
            "suggestions": diagnostic["recommendations"][:3],
            "suggestion_scope": "当前选择范围；本周建议需选择对应时间边界",
            "activity": activity_view(overview["activity_rhythm"], scope, events,
                source_statuses={"human_messages": events,
                                 "tool_calls": coverage.get("tool_calls", {}).get("status", "unavailable"),
                                 "model_requests": coverage.get("model_calls", {}).get("status", "unavailable")},
                human_origin_unknown_n=counts.get("human_origin_unknown", 0)),
            "tool_ranking": diagnostic["tools"]["by_tool"],
            "language_ranking": ranked_counts(language_counts, basis="file_extension_mentions_in_human_text",
                                               status=events, unknown_n=counts.get("human_origin_unknown")),
        },
        "profile": profile, "diagnostics": diagnostic, "tools": diagnostic["tools"],
        "sessions": sessions, "timeline": _timeline(analysis["tasks"]["records"]),
        "projects": [_project(project, analysis) for project in analysis["projects"]],
        "semantics": {
            "interest_domains": analysis["tasks"]["summary"].get("domain"),
            "explicit_preferences": profile.get("preferences"),
            "feedback_terms": ranked_counts(correction_terms, basis="lexical_feedback_signal_occurrences",
                                            status=events, unknown_n=counts.get("human_origin_unknown")),
            "semantic_terms": unavailable("existing_text_endpoint_returns_ngram_weights_not_semantic_word_counts"),
            "friction": analysis["bottleneck_features"]["interaction"].get("friction_types"),
            "meaning": "兴趣标签、反馈词面线索与已确认摩擦分别显示；词频不证明情绪或纠偏。",
        },
        "recommendations": diagnostic["recommendations"],
        "resources": {
            "matching_signals": {"task_distribution": analysis["tasks"]["summary"],
                                 "explicit_preferences": profile.get("preferences"),
                                 "findings": diagnostic["findings"]},
            "for_you": unavailable("catalog_capability_and_agent_compatibility_mapping_required"),
            "same_persona": unavailable("no_consented_cohort_usage_dataset"),
            "popular": unavailable("no_resource_usage_dataset"),
            "catalog_endpoint": "/v1/catalog",
        },
        "capabilities": {
            "profile_code": "partial_feature_support",
            "configuration_inventory": "unavailable", "resource_popularity": "unavailable",
            "project_completion": "unavailable", "human_work_duration": "unavailable",
            "estimated_improvement": "unmeasured", "studio": "deferred",
            "sync_export_share_install": "application_actions_not_statistical_metrics",
        },
        "limitations": ["规则阈值用于可解释展示，未经独立人群校准。",
                        "比例在各自已知分母上计算；未知不补零，也不平均会话比例。",
                        "画像、瓶颈和资源匹配使用不同证据；不合成单一人格/效率总分。"],
    }
    # The caller may annotate the display result without changing feature-layer evidence.
    return deepcopy(result)
