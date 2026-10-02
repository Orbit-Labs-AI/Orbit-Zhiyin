"""Deterministic display rules over selected, evidence-backed feature families.

Rates are pooled counts, never averages of session rates. Unknown values do not
become zero, and these diagnostic signals do not establish psychological traits,
root causes, financial savings, or project completion.
"""

import math
from collections import Counter, defaultdict

RULE_VERSION = "presentation-diagnostics-v1"
RECOMMENDATION_CATEGORIES = (
    "prompt", "skill", "hooks", "plugin_mcp", "subagent", "model", "workflow",
)
PRIORITY_SUPPORT_N = 5
MAX_TRANSITION_NODES = 20


def _refs(rows, identity):
    return [{"session_uid": r.get("session_uid"), identity: r[identity],
             **({"task_uid": r.get("task_uid"), "criteria_set_uid": r.get("criteria_set_uid")}
                if identity == "criterion_uid" else {})}
            for r in rows if r.get(identity) is not None]


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _rate(numerator, denominator, *, source, unknown_n, basis, refs=()):
    if source in ("unavailable", "excluded"):
        # Coverage is authoritative even if a caller retained stale aggregates.
        numerator, denominator, unknown_n, refs = None, None, None, ()
    valid = (_number(numerator) and _number(denominator)
             and denominator > 0 and numerator <= denominator)
    status = ("unavailable" if source in ("unavailable", "excluded") else
              "insufficient_data" if not valid else
              "partial" if source != "available" or unknown_n is None or unknown_n > 0 else
              "available")
    return {"value": numerator / denominator if valid else None, "unit": "ratio",
            "status": status, "numerator": numerator, "denominator": denominator,
            "known_n": denominator, "unknown_n": unknown_n,
            "reason": "source_unavailable" if status == "unavailable" else
                      "no_eligible_denominator" if not valid else None,
            "basis": basis, "evidence_refs": list(refs), "rule_version": RULE_VERSION}


def _corrections(interaction):
    rows = interaction.get("message_intents")
    source = interaction.get("status", "unavailable")
    known = [r for r in rows or [] if r.get("state") == "confirmed"]
    corrected = [r for r in known if "correction" in (r.get("intents") or [])]
    counts = interaction.get("unknown_counts") or {}
    external = [counts.get("human_origin", 0), counts.get("session_kind_messages", 0)]
    unknown = (len(rows) - len(known) + sum(external)
               if rows is not None and all(_number(n) for n in external) else None)
    numerator = len(corrected) if known or rows == [] and source == "available" and unknown == 0 else None
    return _rate(numerator, len(known) if rows is not None else None,
                 source=source, unknown_n=unknown,
                 basis="confirmed correction messages / reviewed human messages with determinable intents",
                 refs=_refs(known, "event_uid")), corrected


def _duration_summary(calls, duration_rows, source):
    lookup = {(r.get("session_uid"), r.get("call_uid")): r for r in duration_rows or []}
    reliable, estimated = [], []
    for call in calls:
        row = lookup.get((call.get("session_uid"), call.get("call_uid")), {})
        if row.get("quality") == "reliable" and _number(row.get("execution_duration_ms")):
            reliable.append(row)
        elif row.get("quality") == "estimated" and _number(row.get("estimated_log_gap_ms")):
            estimated.append(row)
    values = [r["execution_duration_ms"] for r in reliable]
    total = math.fsum(values) if values else None
    missing = len(calls) - len(reliable) - len(estimated)
    return {"value": total / len(values) if values else None, "unit": "ms",
            "status": "unavailable" if source in ("unavailable", "excluded") else
                      "insufficient_data" if not values else
                      "partial" if source != "available" or len(values) < len(calls) else "available",
            "numerator": total, "denominator": len(values), "known_n": len(values),
            "unknown_n": missing, "estimated_n": len(estimated),
            "estimated_log_gap_mean_ms": (math.fsum(r["estimated_log_gap_ms"] for r in estimated)
                                          / len(estimated) if estimated else None),
            "reason": None if values else "no_reliable_execution_duration",
            "basis": "arithmetic mean of native/reported execution durations; log-gap estimates excluded",
            "evidence_refs": _refs(reliable, "call_uid"), "rule_version": RULE_VERSION}


def _tool_rates(calls, source, duration_rows):
    statuses = Counter(c.get("tool_result_status", "unknown") for c in calls)
    eligible = statuses["success"] + statuses["failed"]
    unknown = len(calls) - sum(statuses[s] for s in
                              ("success", "failed", "rejected", "interrupted", "running"))
    measured = bool(calls) or source == "available"
    refs = _refs([c for c in calls if c.get("tool_result_status") in ("success", "failed")], "call_uid")
    return {"call_count": len(calls) if measured else None,
            "known_success_count": statuses["success"] if measured else None,
            "known_failure_count": statuses["failed"] if measured else None,
            "eligible_status_count": eligible if measured else None,
            "unknown_status_count": unknown if measured else None,
            **{s + "_count": statuses[s] if measured else None
               for s in ("rejected", "interrupted", "running")},
            "success_rate": _rate(statuses["success"] if measured else None,
                                  eligible if measured else None, source=source,
                                  unknown_n=unknown if measured else None,
                                  basis="known successful calls / (known successful + known failed calls)", refs=refs),
            "error_rate": _rate(statuses["failed"] if measured else None,
                                eligible if measured else None, source=source,
                                unknown_n=unknown if measured else None,
                                basis="known failed calls / (known successful + known failed calls)", refs=refs),
            "average_execution_duration_ms": _duration_summary(calls, duration_rows, source)}


def _tool_key(call):
    return call.get("name_raw"), call.get("kind")


def _transitions(calls, source):
    """Adjacency in recorded invocation order, with no cross-session edges."""
    observed = calls is not None and (bool(calls) or source == "available")
    frequencies = Counter(_tool_key(c) for c in calls or [])
    nodes = sorted(frequencies, key=str)
    original_n = len(nodes)
    other = object()  # Cannot collide with a real tool name/kind tuple.
    other_members = []
    if original_n > MAX_TRANSITION_NODES:
        selected = sorted(nodes, key=lambda key: (-frequencies[key], str(key)))[:MAX_TRANSITION_NODES - 1]
        other_members = [key for key in nodes if key not in set(selected)]
        nodes = [*selected, other]
    indices = {key: i for i, key in enumerate(nodes)}
    other_index = indices.get(other)
    counts = [[0 for _ in nodes] for _ in nodes]
    sessions, refs = defaultdict(list), []
    excluded = 0
    for call in calls or []:
        sessions[call.get("session_uid")].append(call)
    for sid, group in sorted(sessions.items(), key=lambda p: str(p[0])):
        seqs = [c.get("seq") for c in group]
        # A missing/tied position makes adjacency ambiguous for this session.
        if sid is None or any(not isinstance(s, int) or isinstance(s, bool) for s in seqs) or len(set(seqs)) != len(seqs):
            excluded += len(group)
            continue
        ordered = sorted(group, key=lambda c: c["seq"])
        for previous, following in zip(ordered, ordered[1:], strict=False):
            a = indices.get(_tool_key(previous), other_index)
            b = indices.get(_tool_key(following), other_index)
            counts[a][b] += 1
            refs.append({"session_uid": sid, "from_call_uid": previous["call_uid"],
                         "to_call_uid": following["call_uid"]})
    totals = [sum(row) for row in counts]
    return {"status": "unavailable" if calls is None or source in ("unavailable", "excluded") else
                      "partial" if excluded or source != "available" else "available",
            "nodes": [{"name_raw": None, "kind": None, "group": "other", "label": "其他工具"}
                      if key is other else {"name_raw": key[0], "kind": key[1]} for key in nodes]
                     if calls is not None else None,
            "reduction": {"max_nodes": MAX_TRANSITION_NODES, "original_node_count": original_n,
                          "other_node_members": [{"name_raw": k[0], "kind": k[1]} for k in other_members],
                          "basis": "above 20 identities keep 19 most-used tools, aggregate remainder before normalization"},
            "counts": counts if observed else None,
            "probabilities": [[n / total if total else None for n in row]
                              for row, total in zip(counts, totals, strict=True)] if observed else None,
            "row_denominators": totals if observed else None,
            "transition_count": sum(totals) if observed else None,
            "excluded_order_call_count": excluded if observed else None,
            "basis": "P(next tool=j | current tool=i)=observed adjacent i-to-j calls / all outgoing calls from i",
            "limitations": ["Invocation order is not a dependency chain or causal relation.",
                            "Concurrent calls can be adjacent; sessions with ambiguous sequence positions are excluded.",
                            "No edges cross session boundaries; zero outgoing rows have null probabilities."],
            "evidence_refs": refs, "rule_version": RULE_VERSION}


def _failure_reasons(respond):
    failures = respond.get("failure_reasons")
    if not respond.get("tool_sequence") and respond.get("status") != "available":
        failures = None
    groups = defaultdict(list)
    for row in failures or []:
        if row.get("failure_reason") is not None:
            groups[row["failure_reason"]].append(row)
    return {"rows": [{"reason": key, "count": len(rows), "evidence_refs": _refs(rows, "call_uid")}
                     for key, rows in sorted(groups.items(), key=lambda p: (-len(p[1]), p[0]))]
                    if failures is not None else None,
            "unknown_reason_count": sum(r.get("failure_reason") is None for r in failures) if failures is not None else None,
            "total_failure_records": len(failures) if failures is not None else None,
            "basis": "explicit protocol reasons for failed, rejected, or interrupted calls; no inferred root causes"}


def _outcomes(analysis, outcome):
    subjective = (analysis.get("overview") or {}).get("subjective_outcomes") or {}
    counts = subjective.get("counts") or {}
    feedback = [f for session in analysis.get("sessions") or []
                for f in (session.get("subjective_outcomes") or {}).get("feedback") or []]
    feedback = list({(f.get("session_uid"), f.get("event_uid")): f for f in feedback}.values())
    rework = [f for f in feedback if f.get("link_status") == "linked" and f.get("rework_feedback")]
    subjective_result = {
        "status": subjective.get("status", "unavailable"), "counts": subjective.get("counts"),
        "rework_feedback_rate": _rate(counts.get("rework_feedback_count"), counts.get("linked_feedback_count"),
                                      source=subjective.get("status", "unavailable"), unknown_n=subjective.get("unknown_n"),
                                      basis="linked rework feedback messages / all linked feedback messages; not satisfaction or task success",
                                      refs=_refs(rework, "event_uid")),
        "task_success": None,
        "meaning": "Explicit linked user feedback; silence is unknown, not acceptance.",
    }
    validations = outcome.get("validation_runs")
    eligible = [r for r in validations or [] if r.get("validation_result") in ("passed", "failed")]
    failed = [r for r in eligible if r["validation_result"] == "failed"]
    acceptance = outcome.get("acceptance_results")
    known_criteria = [r for r in acceptance or [] if r.get("acceptance_result") in ("passed", "failed")]
    passed_criteria = sum(r["acceptance_result"] == "passed" for r in known_criteria)
    source = outcome.get("status", "unavailable")
    measured_validations = validations is not None and (bool(validations) or source == "available")
    measured_criteria = acceptance is not None and (bool(acceptance) or source == "available")
    objective_result = {
        "status": source,
        "validation_failure_rate": _rate(len(failed) if measured_validations else None,
                                         len(eligible) if measured_validations else None, source=source,
                                         unknown_n=len(validations) - len(eligible) if measured_validations else None,
                                         basis="failed validation runs / known passed or failed validation runs",
                                         refs=_refs(eligible, "validation_uid")),
        "declared_criterion_pass_rate": _rate(passed_criteria if measured_criteria else None,
                                             len(known_criteria) if measured_criteria else None, source=source,
                                             unknown_n=len(acceptance) - len(known_criteria) if measured_criteria else None,
                                             basis="passed declared criteria / declared criteria with known passed or failed results; not project completion",
                                             refs=_refs(known_criteria, "criterion_uid")),
        "declared_task_results": outcome.get("task_results"),
        "project_completion": None,
        "meaning": "Executed checks and explicitly declared acceptance sets; distinct from user acceptance.",
    }
    return {"subjective": subjective_result, "objective": objective_result}, failed, rework


def _finding(rule_id, title, metric, refs, category, action):
    if (not refs or not metric.get("numerator") or metric.get("value") is None
            or metric.get("status") == "unavailable"):
        return None
    known, unknown = metric["denominator"], metric.get("unknown_n")
    # Sorting heuristic only. Five samples is a versioned support convention,
    # not a significance threshold, population estimate, or predicted benefit.
    coverage = known / (known + unknown) if unknown is not None else None
    priority = (100 * metric["value"] * min(known / PRIORITY_SUPPORT_N, 1) * coverage
                if coverage is not None else None)
    return {"rule_id": rule_id, "rule_version": RULE_VERSION, "title": title,
            "interpretation": "Observed diagnostic signal requiring review; not proof of an abnormal bottleneck.",
            "priority_score": round(priority, 4) if priority is not None else None,
            "priority_components": {"observed_rate": metric["value"],
                                    "sample_support": min(known / PRIORITY_SUPPORT_N, 1),
                                    "known_coverage": coverage},
            "metric": metric, "evidence_refs": refs,
            "recommendation": {"category": category, "action": action}}


def build_diagnostics(analysis: dict) -> dict:
    """Map analyze_bundle or its same-scope session/project subview to the UI."""
    families = analysis.get("bottleneck_features") or {}
    interaction, respond = families.get("interaction") or {}, families.get("respond") or {}
    outcome = families.get("outcome") or {}
    # A user exclusion overrides an older feature engine's L2 reconstruction.
    # Keep this boundary even when newer engines already enforce it upstream.
    excluded_tools = (families.get("source_coverage") or {}).get("tool_calls", {}).get("status") == "excluded"
    if excluded_tools:
        respond = {"status": "excluded", "tool_sequence": None}
        outcome = {"status": "excluded"}
    correction, corrected = _corrections(interaction)
    calls, source = respond.get("tool_sequence"), respond.get("status", "unavailable")
    durations = (families.get("cost_time") or {}).get("durations") or {}
    duration_rows = durations.get("execution_durations")
    subagent_relations = respond.get("subagent_relations")
    subagent_ids = {r["child_session_uid"] for r in subagent_relations or [] if r.get("child_session_uid")}
    retry_links = respond.get("retry_links")
    retry_measured = (retry_links is not None and calls is not None
                      and source not in ("unavailable", "excluded") and (bool(calls) or source == "available"))
    groups = defaultdict(list)
    for call in calls or []:
        groups[_tool_key(call)].append(call)
    tools = {"status": source, **_tool_rates(calls or [], source, duration_rows),
             "by_tool": [{"name_raw": key[0], "kind": key[1], **_tool_rates(rows, source, duration_rows)}
                         for key, rows in sorted(groups.items(), key=lambda p: (-len(p[1]), str(p[0])))]
                        if calls is not None else None,
             "transition_matrix": _transitions(calls, source),
             "failure_reasons": _failure_reasons(respond),
             "subagent_count": (len(subagent_ids) if subagent_ids or
                                subagent_relations == [] and respond.get("event_coverage") == "available" else None),
             "subagent_count_basis": "distinct children with explicit parent/spawn evidence; not installed configuration count",
             "subagent_relations": subagent_relations,
             "unresolved_subagent_events": respond.get("unresolved_subagent_events"),
             "retry_links": retry_links,
             "confirmed_retry_count": sum(r.get("state") == "confirmed" for r in retry_links) if retry_measured else None,
             "candidate_retry_count": sum(r.get("state") == "candidate" for r in retry_links) if retry_measured else None}
    outcomes, validation_failures, rework = _outcomes(analysis, outcome)
    failed_calls = [c for c in calls or [] if c.get("tool_result_status") == "failed"]
    findings = [
        _finding("confirmed_correction", "已确认的协作纠偏", correction, _refs(corrected, "event_uid"),
                 "prompt", "回看纠偏所指向的请求，在后续提示中明确相关约束与验收条件。"),
        _finding("tool_failure", "已记录的工具执行失败", tools["error_rate"], _refs(failed_calls, "call_uid"),
                 "workflow", "检查失败调用的协议原因和参数，复现后再调整调用步骤。"),
        _finding("validation_failure", "已执行检查出现失败", outcomes["objective"]["validation_failure_rate"],
                 _refs(validation_failures, "validation_uid"), "hooks" if len(validation_failures) >= 2 else "workflow",
                 "先复现失败检查；重复出现时考虑将同类检查配置到提交前或交付前执行。"),
        _finding("linked_rework", "交付后收到返工反馈", outcomes["subjective"]["rework_feedback_rate"],
                 _refs(rework, "event_uid"), "workflow", "回看反馈对应的交付版本，先确认验收条件，再缩小下一次交付批次。"),
    ]
    findings = sorted((f for f in findings if f is not None),
                      key=lambda f: (-(f["priority_score"] or 0), f["rule_id"]))
    recommendations = [{"recommendation_id": f["rule_id"], "rule_id": f["rule_id"],
                        "rule_version": RULE_VERSION, **f["recommendation"],
                        "priority_score": f["priority_score"], "evidence_refs": f["evidence_refs"],
                        "expected_effect": None, "installable": False,
                        "agent_customization": "Requires an explicit agent capability/configuration manifest."}
                       for f in findings]
    semantic = interaction.get("semantic_observations")
    return {"rule_version": RULE_VERSION, "correction_rate": correction, "tools": tools,
            "friction_types": interaction.get("friction_types"),
            "repeated_requirement_count": interaction.get("repeated_requirement_count"),
            "outcomes": outcomes, "findings": findings, "recommendations": recommendations,
            "recommendation_categories": list(RECOMMENDATION_CATEGORIES),
            "priority_rule": {"formula": "100 * observed_rate * min(known_n / 5, 1) * known_n / (known_n + unknown_n)",
                              "support_reference_n": PRIORITY_SUPPORT_N,
                              "meaning": "Review ordering heuristic, not measured severity, causation, savings or statistical significance."},
            **({"semantic_observations": {"interaction": semantic,
                                          "meaning": "Model inferred evidence; excluded from confirmed rates and measured utility."}} if semantic else {}),
            "limitations": ["All metrics describe the already selected observed subset.",
                            "Unreviewed correction candidates do not enter the confirmed correction rate.",
                            "Rejected, interrupted and running calls are excluded from the success/error denominator.",
                            "Missing configurations alone do not create findings or installation recommendations."]}
