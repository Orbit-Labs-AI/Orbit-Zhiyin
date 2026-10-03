"""Translate observed bottlenecks into opportunities with attributable evidence.

Rules operate on one selected root-session tree at a time. They never consume
raw prompts, old lexical proxies, popularity, or estimated work duration.
"""

import json
from collections import defaultdict

from ...models import stable_id
from ..respond import result_status

RULE_IDS = ("correction_density", "repeated_requirements", "identical_retries", "tool_failures",
            "validation_failures", "acceptance_evidence_gap", "context_pressure")
PREFLIGHT_REASONS = {"command_not_found", "missing_dependency", "invalid_arguments", "permission_denied",
                     "timeout", "rate_limit"}


def clamp(value):
    return min(1., max(0., value))


def evidence(kind, sid, uid, task=None):
    return {"kind": kind, "session_uid": sid, "id": uid, "task_uid": task}


def metric(path, value, denominator=None, unit="count"):
    return {"path": path, "value": value, "denominator": denominator, "unit": unit}


def _status(call):
    return call.get("tool_result_status") or result_status(call)


def evaluate_features(features, policy, context):
    signals, assessments = [], []
    interaction = features.get("interaction") or {}
    respond = features.get("respond") or {}
    outcome = features.get("outcome") or {}
    calls = respond.get("tool_sequence")
    call_index = {(c["session_uid"], c["call_uid"]): c for c in calls or []}

    def assessment(rule, status, reason):
        assessments.append({"rule_id": rule, "status": status, "reason": reason, "scope": context})

    def emit(rule, capabilities, reason, metrics, refs, count, minimum, n, target_n, coverage, severity,
             hypothesis, evaluation_metrics, group=None):
        refs = list({(r["kind"], r["session_uid"], r["id"]): r for r in refs if r["id"] and r["session_uid"]}.values())
        if not refs:
            return
        signal = {"signal_id": stable_id(rule, context, group), "rule_id": rule,
                        "capabilities": capabilities, "reason": reason, "metrics": metrics,
                        "evidence": sorted(refs, key=lambda r: (r["session_uid"], r["kind"], r["id"])),
                        "scope": {**context, "group": group}, "effective_n": n, "coverage": round(clamp(coverage), 4),
                        "confidence": round(clamp(coverage) * min(1., n / target_n), 4),
                        "severity": round(clamp(severity), 4), "recurrence": round(min(1., count / (minimum * 3)), 4),
                        "hypothesis": hypothesis, "evaluation_metrics": evaluation_metrics}
        signals.append(signal)
        return signal

    rows = interaction.get("message_intents")
    reviewed = [r for r in rows or [] if r.get("state") == "confirmed" and r.get("source")
                and r.get("event_uid") and r.get("session_uid") and r.get("intents")]
    unknown = interaction.get("unknown_counts") or {}
    denominator = max(len(rows or []), (interaction.get("effective_samples") or {}).get("human_messages") or 0)
    denominator += (unknown.get("human_origin") or 0) + (unknown.get("session_kind_messages") or 0)
    coverage = len(reviewed) / denominator if denominator else 0
    corrections = [r for r in reviewed if "correction" in r["intents"] and r.get("task_uid")
                   and r.get("target_event_uid") in r.get("evidence_event_uids", [])]
    rate = len(corrections) / len(reviewed) if reviewed else None
    rule = "correction_density"
    if rows is None or len(reviewed) < policy.intent_min_samples or coverage < policy.annotation_min_coverage:
        assessment(rule, "insufficient_evidence", "意图有效样本或标注覆盖不足；词面候选不能代替确认纠偏。")
    elif len(corrections) < policy.correction_min_count or rate < policy.correction_min_rate:
        assessment(rule, "below_threshold", "本范围内确认纠偏未达到触发门槛。")
    else:
        friction = {t for r in corrections for t in r.get("friction_types") or []}
        capabilities = sorted(({"scope_alignment"} if friction & {"understanding", "scope"} or not friction else set())
                              | ({"debugging"} if "execution" in friction else set())
                              | ({"verification"} if "verification" in friction else set()))
        emit(rule, capabilities, f"{len(reviewed)} 条已确认意图消息中有 {len(corrections)} 条纠偏，按已标注的摩擦类型选择试验；未标类型时先试行目标确认。",
             [metric("interaction.confirmed_correction_count", len(corrections)),
              metric("interaction.confirmed_correction_rate", rate, len(reviewed), "ratio")],
             [evidence("event", r["session_uid"], uid, r.get("task_uid")) for r in corrections for uid in r["evidence_event_uids"]],
             len(corrections), policy.correction_min_count, len(reviewed), policy.intent_min_samples * 2, coverage,
             rate / (policy.correction_min_rate * 2), "检验针对已知摩擦类型的干预是否减少确认纠偏，同时保留原任务验收要求。",
             ["interaction.confirmed_correction_rate", "outcome.acceptance_results"])
        assessment(rule, "triggered", "确认纠偏达到样本、覆盖与比例门槛。")

    inferred = [r for r in rows or [] if r.get("state") == "inferred" and r.get("source") == "semantic_model"
                and r.get("event_uid") and r.get("session_uid") and r.get("intents")
                and r.get("missing_reason") is None]
    inferred_corrections = [r for r in inferred if "correction" in r["intents"] and r.get("task_uid")
                            and r.get("target_event_uid") in r.get("evidence_event_uids", [])]
    inferred_coverage = len(inferred) / denominator if denominator else 0
    inferred_rate = len(inferred_corrections) / len(inferred) if inferred else None
    if (len(inferred) >= policy.intent_min_samples and inferred_coverage >= policy.annotation_min_coverage
            and len(inferred_corrections) >= policy.correction_min_count and inferred_rate >= policy.correction_min_rate):
        friction = {t for r in inferred_corrections for t in r.get("friction_types") or []}
        capabilities = sorted(({"scope_alignment"} if friction & {"understanding", "scope"} or not friction else set())
                              | ({"debugging"} if "execution" in friction else set())
                              | ({"verification"} if "verification" in friction else set()))
        inferred_signal = emit("correction_density", capabilities,
             f"模型推断的 {len(inferred)} 条意图中有 {len(inferred_corrections)} 条关联纠偏；可复核原句并试验相应干预，尚无独立精度校准。",
             [metric("interaction.semantic_observations.correction_count", len(inferred_corrections)),
              metric("interaction.semantic_observations.correction_rate", inferred_rate, len(inferred), "ratio")],
             [evidence("event", r["session_uid"], uid, r.get("task_uid")) for r in inferred_corrections for uid in r["evidence_event_uids"]],
             len(inferred_corrections), policy.correction_min_count, len(inferred), policy.intent_min_samples * 2,
             inferred_coverage, inferred_rate / (policy.correction_min_rate * 2),
             "先核对推断纠偏与目标；再检验干预是否有益，不把模型标签当用户确认或已测收益。",
             ["interaction.semantic_observations", "outcome.acceptance_results"], group={"evidence_tier": "model_inferred"})
        if inferred_signal is not None:
            inferred_signal.update(evidence_tier="model_inferred", calibrated_probability=None,
                                   confidence_semantics="coverage/sample support heuristic, not semantic correctness probability")
            assessments.append({"rule_id": "correction_density", "status": "candidate_triggered",
                            "source_tier": "model_inferred", "scope": context,
                            "reason": "有边界的推断观察达到候选试验门槛；人工标注不作为有输出的前提。"})

    rule = "repeated_requirements"
    requirements = [r for r in reviewed if r.get("task_uid") and isinstance(r.get("requirements"), list)]
    seen, repeats = set(), []
    for r in sorted(requirements, key=lambda r: (r["session_uid"], r.get("seq", 0), r["event_uid"])):
        keys = {(r["session_uid"], r["task_uid"], q["object_uid"], q["requirement_uid"])
                for q in r["requirements"] if q.get("object_uid") and q.get("requirement_uid")}
        if keys & seen:
            repeats.append(r)
        seen.update(keys)
    requirement_coverage = len(requirements) / denominator if denominator else 0
    if rows is None or len(requirements) < policy.requirement_min_samples or requirement_coverage < policy.annotation_min_coverage:
        assessment(rule, "insufficient_evidence", "同对象要求的标注或覆盖不足，不能从相似文本猜测重复要求。")
    elif len(repeats) < policy.repeated_min_count:
        assessment(rule, "below_threshold", "同任务同对象的重复强调未达到门槛。")
    else:
        emit(rule, ["requirements_memory"], f"观察到 {len(repeats)} 条对同任务、同对象要求的再次强调，可试用要求记录与阶段核对。",
             [metric("interaction.repeated_requirement_count", len(repeats), len(requirements))],
             [evidence("event", r["session_uid"], r["event_uid"], r["task_uid"]) for r in requirements],
             len(repeats), policy.repeated_min_count, len(requirements), policy.requirement_min_samples * 2,
             requirement_coverage, len(repeats) / (policy.repeated_min_count * 2),
             "检验持久记录要求是否减少重复强调，而不增加无关的计划步骤。",
             ["interaction.repeated_requirement_count", "outcome.acceptance_results"])
        assessment(rule, "triggered", "存在可追溯的同对象重复强调。")

    rule = "identical_retries"
    links = respond.get("retry_links")
    unique_links = {(r.get("session_uid"), r.get("from_call_uid"), r.get("to_call_uid")): r for r in links or []}
    retries = []
    for (sid, previous, current), link in unique_links.items():
        a, b = call_index.get((sid, previous)), call_index.get((sid, current))
        if (link.get("state") == "confirmed" and link.get("same_arguments") is True and link.get("task_uid")
                and link.get("status_scope") not in (None, "unknown") and a and b and _status(a) == "failed"):
            retries.append(link)
    if calls is None or links is None:
        assessment(rule, "insufficient_evidence", "没有可验证的调用与重试关系。")
    elif len(retries) < policy.retry_min_count:
        assessment(rule, "below_threshold" if not links or retries else "insufficient_evidence", "确认的同参数重试不足；候选关系不计入。")
    else:
        refs = [evidence("call", r["session_uid"], uid, r["task_uid"]) for r in retries for uid in (r["from_call_uid"], r["to_call_uid"])]
        emit(rule, ["debugging", "retry_control"], f"存在 {len(retries)} 对确认的失败后同参数重试，可试行先诊断再重试。",
             [metric("respond.retry_links.confirmed_same_arguments", len(retries), len(unique_links))], refs,
             len(retries), policy.retry_min_count, len(retries), policy.retry_min_count * 2,
             len(retries) / len(unique_links), len(retries) / (policy.retry_min_count * 2),
             "检验根因定位和重试检查点是否减少重复失败；不得通过跳过失败检查来降低计数。",
             ["respond.retry_links", "outcome.acceptance_results"])
        assessment(rule, "triggered", "使用确认关系，不使用兼容层的弱重试计数。")

    rule = "tool_failures"
    groups = defaultdict(list)
    for c in calls or []:
        groups[(c.get("name_raw"), c.get("kind"))].append(c)
    reasons = {(r["session_uid"], r["call_uid"]): r for r in respond.get("failure_reasons") or []}
    qualified, emitted = 0, 0
    for (name, kind), group in sorted(groups.items(), key=lambda item: str(item[0])):
        known = [c for c in group if _status(c) in ("success", "failed")]
        failed = [c for c in known if _status(c) == "failed" and c.get("result_event_uid")]
        coverage = len(known) / len(group)
        if len(known) < policy.tool_min_samples or coverage < policy.tool_min_coverage:
            continue
        qualified += 1
        rate = len(failed) / len(known)
        if len(failed) < policy.tool_failure_min_count or rate < policy.tool_failure_min_rate:
            continue
        preflight = [c for c in failed if reasons.get((c["session_uid"], c["call_uid"]), {}).get("failure_reason") in PREFLIGHT_REASONS]
        capabilities = ["tool_preflight"] if len(preflight) >= policy.tool_failure_min_count else ["debugging"]
        emit(rule, capabilities, f"工具 {name} 的 {len(known)} 次明确结果中有 {len(failed)} 次失败；" +
             ("已有结构化原因，可试行调用前检查。" if "tool_preflight" in capabilities else "先诊断失败原因，再选择修复方式。"),
             [metric("respond.tools.by_tool.known_failure_count", len(failed)),
              metric("respond.tools.by_tool.failure_rate", rate, len(known), "ratio")],
             [evidence("call", c["session_uid"], c["call_uid"], c.get("task_uid")) for c in failed],
             len(failed), policy.tool_failure_min_count, len(known), policy.tool_min_samples * 2, coverage,
             rate / (policy.tool_failure_min_rate * 2), "检验诊断或调用前检查能否减少同类故障；预期的负例测试单独记录。",
             ["respond.tools.by_tool.failure_rate", "outcome.acceptance_results"], group={"tool": name, "kind": kind})
        emitted += 1
    assessment(rule, "triggered" if emitted else "below_threshold" if qualified else "insufficient_evidence",
               "按同一工具计算已知结果与覆盖，拒绝和未知不算失败。")

    rule = "validation_failures"
    validation_groups = defaultdict(list)
    for v in outcome.get("validation_runs") or []:
        scope = v.get("validation_scope") or {}
        refs = v.get("validation_evidence") or {}
        if (v.get("task_uid") and all(scope.get(k) for k in ("project_id", "artifact_uid", "artifact_revision", "coverage"))
                and (refs.get("result_event_uid") or refs.get("report_uid"))):
            normalized = {k: sorted(value) if isinstance(value, list) else value for k, value in scope.items()}
            key = (v.get("root_session_uid") or v["session_uid"], v["task_uid"], v["kind"], json.dumps(normalized, sort_keys=True))
            validation_groups[key].append(v)
    emitted = 0
    for key, group in sorted(validation_groups.items()):
        failed = [v for v in group if v["validation_result"] == "failed"]
        known = [v for v in group if v["validation_result"] in ("failed", "passed")]
        if len(failed) < policy.validation_failure_min_count:
            continue
        emit(rule, ["debugging", "verification"], f"同一任务、产物版本和验证范围出现 {len(failed)} 次 {key[2]} 失败，可试用专门的诊断与验证流程。",
             [metric("outcome.validation_runs.failed_same_scope", len(failed), len(known))],
             [evidence("validation", v["session_uid"], v["validation_uid"], v["task_uid"]) for v in failed],
             len(failed), policy.validation_failure_min_count, len(known), policy.validation_failure_min_count * 2,
             len(known) / len(group), len(failed) / len(known),
             "检验固定失败用例与独立核验是否减少同一验证的反复失败；保持原覆盖范围。",
             ["outcome.validation_runs", "outcome.acceptance_results"], group={"task_uid": key[1], "kind": key[2], "validation_scope": json.loads(key[3])})
        emitted += 1
    assessment(rule, "triggered" if emitted else "below_threshold" if validation_groups else "insufficient_evidence",
               "只比较同任务、同产物版本与范围的实际验证；命令候选不参与。")

    rule = "acceptance_evidence_gap"
    criteria_groups = defaultdict(list)
    for r in outcome.get("acceptance_results") or []:
        if all(r.get(k) for k in ("session_uid", "task_uid", "criteria_set_uid", "criterion_uid", "source", "evidence_event_uid")):
            criteria_groups[(r["session_uid"], r["task_uid"], r["criteria_set_uid"])].append(r)
    complete_tools = (features.get("source_coverage", {}).get("tool_calls") or {}).get("status") == "available"
    emitted = 0
    if complete_tools:
        for key, group in sorted(criteria_groups.items()):
            gaps = [r for r in group if r["acceptance_result"] == "unknown" and r.get("missing_reason") in (
                "no_matching_validation", "scope_or_artifact_revision_mismatch")]
            if len(gaps) < policy.acceptance_gap_min_count:
                continue
            emit(rule, ["verification", "validation_visibility"], f"明确的验收集合有 {len(gaps)} 项缺少匹配的验证证据；这不等于断言没有执行测试。",
                 [metric("outcome.acceptance_results.evidence_gap", len(gaps), len(group))],
                 [evidence("criterion", r["session_uid"], r["criterion_uid"], r["task_uid"]) for r in gaps] +
                 [evidence("event", r["session_uid"], r["evidence_event_uid"], r["task_uid"]) for r in gaps],
                 len(gaps), policy.acceptance_gap_min_count, len(group), policy.acceptance_gap_min_count * 2, 1,
                 len(gaps) / len(group), "检验验收清单和结果记录能否提高相同产物版本的证据覆盖。",
                 ["outcome.acceptance_results", "outcome.validation_runs"], group={"task_uid": key[1], "criteria_set_uid": key[2]})
            emitted += 1
    assessment(rule, "triggered" if emitted else "below_threshold" if criteria_groups and complete_tools else "insufficient_evidence",
               "需要明确验收项及完整工具数据；缺采集不能解释为缺验证。")

    rule = "context_pressure"
    usage = (features.get("cost_time") or {}).get("usage") or {}
    buckets = usage.get("token_buckets") or {}
    n = usage.get("request_count") or 0
    total, tokens = usage.get("total_tokens"), buckets.get("input_tokens")
    request_refs = usage.get("request_evidence") or []
    compactions = [evidence("event", sid, uid) for sid, sequence in ((respond.get("workflow") or {}).get("sequences") or {}).items()
                   for state, uid in sequence if state == "COMPACTION"]
    corroboration = compactions + [evidence("call", r["session_uid"], r["to_call_uid"], r["task_uid"]) for r in retries]
    valid_usage = (usage.get("status") == "available" and usage.get("total_basis") == "call_delta"
                   and n >= policy.token_min_requests and len(request_refs) == n
                   and isinstance(total, int) and not isinstance(total, bool) and total > 0
                   and isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0)
    if not valid_usage:
        assessment(rule, "insufficient_evidence", "需要完整逐请求 Token、足够请求与请求证据；累计快照不能代替。")
    elif tokens < policy.uncached_input_min_tokens or tokens / total < policy.input_min_share or not corroboration:
        assessment(rule, "below_threshold", "高 Token 用量本身不构成浪费，需同时满足输入占比及重试／压缩证据。")
    else:
        emit(rule, ["context_budget"], f"本会话树的 {n} 次完整请求中未缓存输入占 {tokens / total:.0%}，同时有重试或上下文压缩记录，可试验阶段摘要。",
             [metric("cost_time.usage.token_buckets.input_tokens", tokens, total, "token"),
              metric("cost_time.usage.request_count", n)],
             [evidence("model_call", c["session_uid"], c["call_uid"]) for c in request_refs] + corroboration,
             len(corroboration), 1, n, policy.token_min_requests * 2, 1, tokens / total,
             "检验阶段摘要能否降低同类任务的未缓存输入，同时保持验收结果；共现不代表已证明因果。",
             ["cost_time.usage.token_buckets.input_tokens", "outcome.acceptance_results"])
        assessment(rule, "triggered", "完整逐请求输入与可追溯的过程信号共同触发。")
    return signals, assessments
