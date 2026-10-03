"""Eight-family input use and per-resource decisions; no inferred utility claims."""

import json
from collections import Counter

FAMILY_NAMES = {
    "interaction": "Interaction",
    "respond": "Respond",
    "cost_time": "Cost / Time",
    "objective_outcome": "Outcome 客观",
    "subjective_outcome": "Outcome 主观",
    "task": "Task",
    "preference": "Preference",
    "instruction": "Instruction",
}
VERSION = "analysis-use-diagnostics-v1"


def measurement(value, unit, path, denominator=None):
    return {
        "value": value,
        "unit": unit,
        "path": path,
        "denominator": denominator,
        "status": "unknown" if value is None else "observed",
    }


def references(rows, field):
    refs = sorted({(r.get("session_uid"), r[field]) for r in rows or [] if r.get(field)}, key=str)
    return {
        "count": len(refs),
        "sample": [{"session_uid": sid, "id": uid} for sid, uid in refs[:20]],
        "sample_limit": 20,
        "meaning": "traceability sample, not an accuracy label",
    }


def block(
    family, input_metrics, analyzed_metrics, unknowns, evidence, *, quality="reported", note=""
):
    values = [m["value"] for m in analyzed_metrics.values()]
    state = (
        "unavailable" if not values or all(v is None for v in values) else "observations_available"
    )
    return {
        "name": FAMILY_NAMES[family],
        "status": state,
        "input": input_metrics,
        "analyzed": analyzed_metrics,
        "unknown_reasons": unknowns,
        "evidence": evidence,
        "quality": quality,
        "semantic_accuracy_verified": False if quality != "reported" else None,
        "interpretation": note,
    }


def family_diagnostics(analysis):
    features = analysis.get("bottleneck_features") or {}
    interaction, respond = features.get("interaction") or {}, features.get("respond") or {}
    cost, objective = features.get("cost_time") or {}, features.get("outcome") or {}
    subjective = (analysis.get("overview") or {}).get("subjective_outcomes") or {}
    tasks, preferences, instruction = (
        analysis.get(k) or {} for k in ("tasks", "preferences", "instruction")
    )
    messages, calls = interaction.get("message_intents"), respond.get("tool_sequence")
    usage, durations = cost.get("usage") or {}, cost.get("durations") or {}
    human_n = (interaction.get("effective_samples") or {}).get("human_messages")
    input_human = {
        "human_messages": measurement(
            human_n, "human_message", "interaction.effective_samples.human_messages"
        )
    }
    inferred = interaction.get("semantic_observations") or {}
    lexical_candidates = sum(r.get("state") == "candidate" for r in messages or [])
    result = {}
    result["interaction"] = block(
        "interaction",
        input_human,
        {
            "reviewed_intents": measurement(
                (interaction.get("effective_samples") or {}).get("intent_messages"),
                "human_message",
                "interaction.effective_samples.intent_messages",
            ),
            "inferred_intents": measurement(
                inferred.get("intent_messages", 0) if messages is not None else None,
                "human_message",
                "interaction.semantic_observations.intent_messages",
            ),
            "confirmed_corrections": measurement(
                interaction.get("confirmed_correction_count"),
                "human_message",
                "interaction.confirmed_correction_count",
            ),
            "inferred_corrections": measurement(
                inferred.get("correction_count", 0) if messages is not None else None,
                "human_message",
                "interaction.semantic_observations.correction_count",
            ),
            "lexical_candidates": measurement(
                lexical_candidates if messages is not None else None,
                "human_message",
                "interaction.message_intents.state",
            ),
        },
        {
            **(interaction.get("unknown_counts") or {}),
            "semantic_parser": "observations_supplied" if inferred else "not_supplied",
        },
        references(messages, "event_uid"),
        quality="mixed_observation_tiers",
        note="未知意图不代表没有要求或摩擦；模型观察与确认标注分开。",
    )
    if messages is not None and not (
        inferred.get("intent_messages")
        or (interaction.get("effective_samples") or {}).get("intent_messages")
    ):
        result["interaction"]["status"] = (
            "candidates_only"
            if lexical_candidates
            else "input_only"
            if human_n
            else "empty_available"
        )
    statuses = Counter(c.get("tool_result_status", "unknown") for c in calls or [])
    known = sum(statuses[k] for k in ("success", "failed")) if calls is not None else None
    result["respond"] = block(
        "respond",
        {
            "calls": measurement(
                len(calls) if calls is not None else None, "tool_call", "respond.tool_sequence"
            )
        },
        {
            "known_results": measurement(
                known, "tool_call", "respond.tool_sequence.tool_result_status"
            ),
            "failed_results": measurement(
                statuses["failed"] if calls is not None else None,
                "tool_call",
                "respond.tool_sequence.tool_result_status",
            ),
            "subagent_instances": measurement(
                respond.get("subagent_instance_count"),
                "subagent_instance",
                "respond.subagent_instance_count",
            ),
            "subagent_activities": measurement(
                respond.get("subagent_activity_event_count"),
                "activity_event",
                "respond.subagent_activity_event_count",
            ),
        },
        {
            "result_states": dict(statuses),
            "failure_reasons": respond.get("failure_reason_unknown_n"),
            "unresolved_child_events": len(respond.get("unresolved_subagent_events") or []),
        },
        references(calls, "call_uid"),
        note="调用、包装调用和业务步骤不是同一种单位；失败结果不等于已知根因。边复用率只描述流程形状。",
    )
    result["cost_time"] = block(
        "cost_time",
        {
            "request_rows": measurement(
                (usage.get("request_count") or 0) + (usage.get("invalid_request_rows") or 0)
                if usage.get("request_count") is not None
                else None,
                "model_request",
                "cost_time.usage",
            )
        },
        {
            "valid_requests": measurement(
                usage.get("request_count"), "model_request", "cost_time.usage.request_count"
            ),
            "total_tokens": measurement(
                usage.get("total_tokens"), "token", "cost_time.usage.total_tokens"
            ),
            "uncached_input": measurement(
                (usage.get("token_buckets") or {}).get("input_tokens"),
                "token",
                "cost_time.usage.token_buckets.input_tokens",
            ),
            "cached_input": measurement(
                (usage.get("token_buckets") or {}).get("cache_read_tokens"),
                "token",
                "cost_time.usage.token_buckets.cache_read_tokens",
            ),
            "cache_write": measurement(
                (usage.get("token_buckets") or {}).get("cache_write_tokens"),
                "token",
                "cost_time.usage.token_buckets.cache_write_tokens",
            ),
            "output_tokens": measurement(
                (usage.get("token_buckets") or {}).get("output_tokens"),
                "token",
                "cost_time.usage.token_buckets.output_tokens",
            ),
            "wall_elapsed": measurement(
                durations.get("wall_elapsed_sum_ms"),
                "ms",
                "cost_time.durations.wall_elapsed_sum_ms",
            ),
            "native_execution": measurement(
                durations.get("native_execution_sum_ms"),
                "ms",
                "cost_time.durations.native_execution_sum_ms",
            ),
            "cost_usd": measurement(usage.get("cost_usd"), "USD", "cost_time.usage.cost_usd"),
        },
        {
            "invalid_requests": usage.get("invalid_request_reasons"),
            "unpriced_requests": usage.get("cost_unknown_n"),
            "model_latency": usage.get("request_count", 0) - usage.get("latency_effective_n", 0)
            if usage.get("request_count") is not None
            else None,
            "approval_wait": "missing_reported_waits"
            if durations.get("approval_wait_sum_ms") is None
            else None,
        },
        references(usage.get("request_evidence"), "call_uid"),
        note="缓存与输出分桶保留原含义；墙钟、原生执行、等待和用户投入时间不得互换。未知价格不补成零。",
    )
    runs, candidates = objective.get("validation_runs"), objective.get("validation_candidates")
    result["objective_outcome"] = block(
        "objective_outcome",
        {
            "calls": measurement(
                len(calls) if calls is not None else None, "tool_call", "respond.tool_sequence"
            )
        },
        {
            "executed_checks": measurement(
                len(runs) if runs is not None else None,
                "validation_attempt",
                "outcome.validation_runs",
            ),
            "failed_checks": measurement(
                (objective.get("validation_result_counts") or {}).get("failed", 0)
                if runs is not None
                else None,
                "validation_attempt",
                "outcome.validation_result_counts.failed",
            ),
            "command_candidates": measurement(
                len(candidates) if candidates is not None else None,
                "validation_candidate",
                "outcome.validation_candidates",
            ),
            "resolved_criteria": measurement(
                objective.get("effective_n"), "acceptance_criterion", "outcome.effective_n"
            ),
            "task_success": measurement(
                objective.get("task_success"), "boolean", "outcome.task_success"
            ),
        },
        {
            "acceptance": objective.get("missing_reason"),
            "unclassified_calls": objective.get("unclassified_call_n"),
        },
        references(runs, "validation_uid"),
        note="识别到已执行检查与证明完整任务验收分别统计；命令提及和工具成功不等于任务成功。",
    )
    counts = subjective.get("counts") or {}
    feedback_nodes = [
        n for n in (analysis.get("work_graph") or {}).get("nodes", []) if n["kind"] == "Feedback"
    ]
    result["subjective_outcome"] = block(
        "subjective_outcome",
        input_human,
        {
            "deliveries": measurement(
                counts.get("observed_delivery_count"),
                "delivery_observation",
                "subjective_outcomes.counts.observed_delivery_count",
            ),
            "recognized_feedback": measurement(
                counts.get("recognized_feedback_count"),
                "feedback_message",
                "subjective_outcomes.counts.recognized_feedback_count",
            ),
            "linked_feedback": measurement(
                counts.get("linked_feedback_count"),
                "feedback_message",
                "subjective_outcomes.counts.linked_feedback_count",
            ),
            "confirmed_completion": measurement(
                counts.get("confirmed_completion_count"),
                "feedback_message",
                "subjective_outcomes.counts.confirmed_completion_count",
            ),
        },
        {
            **(subjective.get("unknown_reasons") or {}),
            "unclassified_messages": counts.get("unclassified_message_count"),
            "unresolved_feedback": counts.get("unresolved_feedback_count"),
        },
        references(feedback_nodes, "entity_uid"),
        quality="linked_or_inferred_feedback",
        note="助手 final 是交付观察；沉默不算接受，部分接受不算完整任务完成。",
    )
    task_rows, task_summary = tasks.get("records"), tasks.get("summary") or {}
    result["task"] = block(
        "task",
        input_human,
        {
            "task_records": measurement(
                len(task_rows) if task_rows is not None else None,
                "task_observation",
                "tasks.records",
            ),
            "domain_labeled": measurement(
                (task_summary.get("domain") or {}).get("effective_n"),
                "task_observation",
                "tasks.summary.domain.effective_n",
            ),
            "type_labeled": measurement(
                (task_summary.get("task_type") or {}).get("effective_n"),
                "task_observation",
                "tasks.summary.task_type.effective_n",
            ),
            "domain_distribution": measurement(
                task_summary.get("domain"), "task_label_counts", "tasks.summary.domain"
            ),
            "type_distribution": measurement(
                task_summary.get("task_type"), "task_label_counts", "tasks.summary.task_type"
            ),
        },
        {
            "domain": (task_summary.get("domain") or {}).get("unknown_n"),
            "identity_qualities": dict(
                Counter(t.get("task_identity_quality", "unknown") for t in task_rows or [])
            ),
        },
        references(task_rows, "task_id"),
        quality="candidate_labels",
        note="领域和类型是多标签观察；边界候选不提升为确认任务或职业画像。",
    )
    evidence = preferences.get("evidence")
    result["preference"] = block(
        "preference",
        {
            "instruction_messages": measurement(
                (instruction.get("summary") or {}).get("message_n"),
                "human_message",
                "instruction.summary.message_n",
            )
        },
        {
            "explicit_records": measurement(
                len(preferences["records"]) if preferences.get("records") is not None else None,
                "explicit_preference",
                "preferences.records",
            ),
            "evidence_records": measurement(
                len(evidence) if evidence is not None else None,
                "preference_evidence",
                "preferences.evidence",
            ),
            "evidence_by_source": measurement(
                dict(Counter(e["source_type"] for e in evidence or []))
                if evidence is not None
                else None,
                "source_counts",
                "preferences.evidence.source_type",
            ),
        },
        {
            "pending_evidence": sum(e["status"] == "pending" for e in evidence or [])
            if evidence is not None
            else None
        },
        references(evidence, "evidence_id"),
        quality="scoped_evidence",
        note="历史任务要求支持任务范围证据；没有显式 global 偏好不等于没有习惯。",
    )
    summary = instruction.get("summary") or {}
    instruction_rows = instruction.get("records")
    instruction_quality = summary.get("evidence_quality")
    if instruction_quality is None and instruction_rows is not None:
        instruction_quality = {
            "explicit_messages": sum(
                any(c.get("source") == "confirmed_human_text" for c in r.get("constraints", []))
                for r in instruction_rows
            ),
            "inferred_messages": sum(
                any(c.get("source") == "semantic_model" for c in r.get("constraints", []))
                for r in instruction_rows
            ),
            "calibrated_probability": None,
        }
    result["instruction"] = block(
        "instruction",
        {
            "human_messages": measurement(
                summary.get("message_n"), "human_message", "instruction.summary.message_n"
            )
        },
        {
            "observed_messages": measurement(
                summary.get("effective_n"), "human_message", "instruction.summary.effective_n"
            ),
            "features": measurement(
                summary.get("features"), "feature_counts", "instruction.summary.features"
            ),
            "evidence_quality": measurement(
                instruction_quality,
                "source_counts",
                "instruction.summary.evidence_quality",
            ),
        },
        {"unmatched_messages": summary.get("unknown_n"), "truncated": summary.get("truncated_n")},
        references(instruction.get("records"), "event_uid"),
        quality="explicit_and_inferred_controls",
        note="这里只描述要求观察；推断的权限或长期偏好不能成为有效执行配置。",
    )
    gates = {
        "interaction": interaction.get("status"),
        "respond": respond.get("status"),
        "objective_outcome": objective.get("status"),
        "subjective_outcome": subjective.get("status"),
        "task": "unavailable" if task_rows is None else None,
        "preference": "unavailable"
        if evidence is None and preferences.get("records") is None
        else None,
        "instruction": summary.get("status"),
    }
    for family, state in gates.items():
        if state in ("unavailable", "excluded"):
            result[family]["status"] = state
            for group in ("input", "analyzed"):
                for item in result[family][group].values():
                    item.update(value=None, status="unknown")
    if usage.get("status") in ("unavailable", "excluded"):
        for key in (
            "valid_requests",
            "total_tokens",
            "uncached_input",
            "cached_input",
            "cache_write",
            "output_tokens",
            "cost_usd",
        ):
            result["cost_time"]["analyzed"][key].update(value=None, status="unknown")
        result["cost_time"]["input"]["request_rows"].update(value=None, status="unknown")
    return result


def skill_diagnostics(recommendations, catalog=()):
    if recommendations is None:
        return {"status": "unavailable", "items": None, "reason": "recommendation_pipeline_not_run"}
    items = {i.identity.id: i for i in catalog if i.family == "skills"}
    audits = {
        a["resource_id"]: a
        for a in recommendations.get("resource_assessments", [])
        if a["family"] == "skills"
    }
    cards, exclusions = {}, {}
    signals = {s["signal_id"]: s for s in recommendations.get("signals", [])}
    for card in recommendations.get("recommendations", []):
        if card["family"] == "skills":
            cards.setdefault(card["resource_id"], []).append(card)
    for row in recommendations.get("excluded_resources", []):
        exclusions.setdefault(row["resource_id"], []).append(row)
    result = []
    for uid in sorted(set(items) | set(audits) | set(cards)):
        own = cards.get(uid, [])
        item = items.get(uid)
        audit = audits.get(uid) or {}
        signal_ids = sorted(
            set(audit.get("matched_signal_ids", []))
            | {sid for c in own for sid in c["candidate_features"]["grounded_signal_ids"]}
        )
        used = [signals[sid] for sid in signal_ids if sid in signals]
        result.append(
            {
                "resource_id": uid,
                "name": item.identity.name if item else audits.get(uid, {}).get("name", uid),
                "decision": audits.get(uid),
                "excluded": exclusions.get(uid, []),
                "selected_cards": len(own),
                "input_use": {
                    "signal_ids": signal_ids,
                    "evidence": references(
                        [r for s in used for r in s["evidence"]]
                        + [r for c in own for r in c["evidence"]],
                        "id",
                    ),
                    "observations": [
                        {
                            "rule_id": s["rule_id"],
                            "reason": s["reason"],
                            "metrics": s["metrics"],
                            "evidence_tier": s.get("evidence_tier", "reported"),
                        }
                        for s in used
                    ],
                },
                "pending_requirements": sorted(
                    set(audit.get("pending_requirements", []))
                    | {p for c in own for p in c["pending_requirements"]}
                ),
                "utility": {
                    "status": "unproven",
                    "observed_uplift": None,
                    "saved_tokens": None,
                    "saved_minutes": None,
                    "scenario_estimates": [c.get("benefit_estimate") for c in own],
                    "reason": "same-checkpoint intervention/control evidence is not supplied",
                    "priority_meaning": "trial ordering, not expected causal gain",
                },
            }
        )
    return {
        "status": recommendations.get("status"),
        "items": result,
        "assessment_counts": dict(
            Counter(a["status"] for a in recommendations.get("assessments", []))
        ),
    }


def fact_profile(analysis):
    """An observable projection, never psychological traits or productivity grades."""
    features = analysis.get("bottleneck_features") or {}
    respond = features.get("respond") or {}
    graph = analysis.get("work_graph") or {}
    tasks = analysis.get("tasks") or {}
    nodes = {n["node_uid"]: n for n in graph.get("nodes", [])}
    review = []
    for task in graph.get("task_trajectories", []):
        counts = task["counts"]
        if not any(
            counts.get(k)
            for k in ("tool_failed", "validation_failed", "rework_feedback", "semantic_corrections")
        ):
            continue
        node = nodes.get(task["task_node_uid"], {})
        review.append(
            {
                "task_uid": task["task_uid"],
                "observed_counts": counts,
                "task_identity_quality": (node.get("attributes") or {}).get(
                    "task_identity_quality", "unknown"
                ),
                "task_success": task.get("task_success"),
                "evidence_node_uids": task["members"],
                "friction": "review_negative_results",
                "severity": None,
                "extra_cost": None,
                "causal_root_cause": None,
                "quality": "review_candidate",
            }
        )
    review.sort(
        key=lambda r: (
            -r["observed_counts"].get("validation_failed", 0),
            -r["observed_counts"].get("tool_failed", 0),
            r["task_uid"],
        )
    )
    return {
        "work_mix": {
            "domain": (tasks.get("summary") or {}).get("domain"),
            "task_type": (tasks.get("summary") or {}).get("task_type"),
            "quality": "candidate_labels",
        },
        "collaboration": {
            k: respond.get(k)
            for k in (
                "subagent_instance_count",
                "subagent_activity_event_count",
                "subagent_parent_unknown_n",
            )
        },
        "iteration": {
            "validation_results": (features.get("outcome") or {}).get("validation_result_counts"),
            "task_trajectories": len(graph.get("task_trajectories", []))
            if graph.get("status") not in (None, "unavailable", "excluded")
            else None,
            "review_candidates": review,
        },
        "limitations": [
            "领域不是职业身份，工具活动不是用户工时。",
            "负面执行记录需要复核，不能自动当成根因或无效劳动。",
            "任务成功、瓶颈严重度、额外成本和推荐收益只在相应证据齐备时确认。",
        ],
    }


def diagnostics(analysis, recommendations=None, catalog=()):
    return {
        "schema_version": VERSION,
        "analysis_digest": analysis.get("analysis_digest"),
        "scope": analysis.get("scope"),
        "families": family_diagnostics(analysis),
        "skills": skill_diagnostics(recommendations, catalog),
        "profile": fact_profile(analysis),
        "counting": "each metric declares its unit; different family grains must not be ordered as one funnel",
    }


def terminal_text(report):
    def render(value):
        return "unknown" if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)

    lines = ["八个特征族：输入使用、观察覆盖与未知原因"]
    for family in report["families"].values():
        lines.append(f"\n{family['name']} | {family['status']} | {family['quality']}")
        for label, metrics in (("输入", family["input"]), ("分析", family["analyzed"])):
            values = "; ".join(
                f"{k}={render(m['value'])} [{m['unit']}]" for k, m in metrics.items()
            )
            lines.append(f"  {label}：{values}")
        lines.append(f"  未知：{family['unknown_reasons']}")
        lines.append(f"  可回查证据：{family['evidence']['count']} 项（JSON 中最多列出 20 项）")
        lines.append(f"  解释：{family['interpretation']}")
    lines.append("\nSkill：选择过程与效用依据")
    for item in report["skills"].get("items") or []:
        decision = item.get("decision") or {}
        lines.append(
            f"  {item['name']}：{decision.get('status', 'not_audited')}；入选 {item['selected_cards']} 张；"
            f"待确认 {item['pending_requirements']}；效用未证实"
        )
        lines.append(
            f"    决策依据：{decision.get('reasons', [])}；"
            f"已评估 {decision.get('evaluated_candidates', 'unknown')} 个根会话候选；"
            f"匹配 {len(item['input_use']['signal_ids'])} 个信号"
        )
        for observation in item["input_use"]["observations"]:
            lines.append(
                f"    {observation['rule_id']} [{observation['evidence_tier']}]：{observation['reason']}"
            )
        lines.append(
            "    实测收益 / 节省 Token / 节省分钟：unknown；需要同一任务起点的干预与对照试验。"
        )
    work_mix = report["profile"]["work_mix"]
    lines.append(
        f"\n画像观察：领域={render(work_mix['domain'])}；任务类型={render(work_mix['task_type'])}"
    )
    iteration = report["profile"]["iteration"]
    lines.append(
        f"验证结果={render(iteration['validation_results'])}；"
        f"需复核的任务轨迹={len(iteration['review_candidates'])}"
    )
    lines.append(
        "\n画像与复核：领域/任务类型是候选标签；负面结果可沿任务轨迹回查，严重度与因果收益保持未知。"
    )
    return "\n".join(lines)
