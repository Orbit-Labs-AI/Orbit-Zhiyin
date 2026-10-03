"""Shared coverage explanations for analytics JSON, API, CLI and narrative reports."""

from orbit_data.coverage import COVERAGE_CONTRACT

LABELS = {
    "sessions": "会话", "projects": "项目", "turns": "轮次", "usage_snapshot": "累计用量快照",
    "source_scans": "来源扫描范围", "events": "事件证据", "tool_calls": "工具调用配对",
    "model_calls": "逐次模型用量", "inventory": "本机安装清单", "catalog": "资源目录",
    "native_event_payload": "原生扩展正文", "sample_exclusions": "额外样本筛选",
    "human_origin": "真人来源",
}
STATUS_LABELS = {"available": "输入可用，空集也是有效观测", "partial": "部分证据可用",
                 "unavailable": "输入尚不可用", "excluded": "按配置或范围省略"}
REASONS = {
    "truncated_text": "条事件文本曾被截断",
    "missing_timestamps": "条事件缺少时间戳",
    "inherited_parent_evidence_unavailable": "条继承记录缺少父证据",
    "unparsed_source_records": "条原始记录尚未解析",
    "unknown_event_types": "条事件类型尚未识别",
    "capture_errors_or_incomplete_frames": "条读取失败或不完整帧诊断",
    "source_unavailable_preserved_facts": "条来源不可用诊断（已保留此前事实）",
    "sampled_source_files": "个来源只扫描了样本",
    "source_scan_incomplete": "个来源扫描未完成",
    "source_scan_boundary_unknown": "个来源缺少扫描范围记录",
    "tool_results_without_calls": "条结果缺少对应调用",
    "tool_calls_without_results": "条调用缺少对应结果",
    "tool_results_outside_time_scope": "条结果位于所选时间范围之外",
    "ambiguous_tool_pairing": "条调用无法唯一配对",
    "cumulative_usage_only": "来源只提供累计快照，没有逐次请求用量",
    "mixed_model_usage_granularity": "部分来源仅提供累计快照，逐次请求覆盖不完整",
    "no_inventory_scan": "尚未显式扫描本机安装配置",
    "inventory_layout_incomplete": "类安装配置布局的扫描不完整",
    "catalog_not_connected": "当前分析未接入资源目录快照",
    "native_payload_on_demand": "分析按需读取原生扩展正文",
    "excluded_by_scope": "按调用方配置或筛选范围省略",
    "input_not_provided": "尚未提供这一类输入",
    "human_origin_unknown": "条消息的真人来源无法确认",
    "events_unavailable": "没有可用的事件输入",
}
# Why read_analysis leaves a session tree out of the analysis views (coverage.excluded_sessions
# reason codes, orbit_data.analysis_input._excluded_trees). Shown in 设置 › 数据源.
EXCLUDED_REASONS = {
    "excluded_kind_review": "代码审查会话（如 Codex review）",
    "excluded_kind_automation": "自动化 / 无交互运行（如 claude -p）",
    "excluded_kind_import": "导入的历史会话",
    "excluded_kind_auxiliary": "辅助会话（标题生成、压缩等）",
    "excluded_lineage_unresolved": "找不到父会话的子会话",
    "excluded_root_not_main": "所属会话树的根不是主会话",
}
REASONS.update({code: "个" + label for code, label in EXCLUDED_REASONS.items()})
LABELS["excluded_sessions"] = "未纳入分析的会话"


def excluded_reason_label(code: str) -> str:
    """Chinese label for an excluded_sessions reason code; unknown kinds keep their name."""
    if code in EXCLUDED_REASONS:
        return EXCLUDED_REASONS[code]
    if code.startswith("excluded_kind_"):
        return "其他类型会话（" + code.removeprefix("excluded_kind_") + "）"
    return code
ACTIONS = {
    "source_scans": "需要完整历史时，在来源目录之外的数据目录重新执行 ingest，记录扫描范围。",
    "events": "可继续分析已有证据；旧版截断可重算恢复，原始历史已丢失的部分仍保留缺口。",
    "tool_calls": "缺少另一端时保留未知；不要把未配对调用当成成功。",
    "model_calls": "累计快照不能替代逐次请求；缺少的精确用量保持未知。",
    "inventory": "需要安装情况时，显式运行 orbit-data scan-inventory 后重新分析。",
    "catalog": "会话数据库不提供资源目录快照；推荐使用的独立目录不等同于该输入。",
    "native_event_payload": "这是按需读取优化，完整已存证据仍可通过事件或原始记录 ID 回看。",
    "sample_exclusions": "这是额外的分析筛选；需要这些会话时调整筛选参数。",
}

ACTIONS["excluded_sessions"] = "这些会话不计入统计；它们的花费单独列出，不会算进总花费。"


def _describe(coverage):
    details = {}
    for name, entry in coverage.items():
        canonical = {"tool_call": "tool_calls", "model_call": "model_calls"}.get(name, name)
        if name != canonical and canonical in coverage:
            continue
        status = entry.get("status", "unavailable")
        codes = entry.get("reasons") or []
        if isinstance(codes, dict):
            codes = [key for key, value in codes.items() if value]
        counts = dict(entry.get("reason_counts") or {})
        for code, field in (("truncated_text", "truncated_rows"), ("missing_timestamps", "time_unknown_rows"),
                            ("unknown_event_types", "unknown_rows")):
            if code in codes and code not in counts and entry.get(field) is not None:
                counts[code] = entry[field]
        explanations = []
        for code in codes:
            if code in REASONS:
                count = counts.get(code)
                explanations.append(f"{count} {REASONS[code]}" if count is not None else REASONS[code].removeprefix("条").removeprefix("个"))
            else:
                explanations.append(f"{code}（{counts[code]}）" if code in counts else str(code))
        if not codes and canonical == "inventory" and entry.get("reason") == "no_inventory_scan":
            explanations.append("尚未显式扫描本机安装配置")
        elif not codes and canonical == "catalog":
            explanations.append("当前分析未接入资源目录快照")
        elif not codes and canonical == "native_event_payload":
            explanations.append("分析未批量载入 event.ext 原生副本")
        elif canonical == "sample_exclusions":
            explanations.append(f"本次筛选额外排除 {entry.get('rows', 0)} 个会话")
        elif not codes and entry.get("reason"):
            explanations.append(entry["reason"])
        if not explanations and status != "available":
            explanations.append("输入未提供具体原因；此状态不代表命令执行失败")
        details[canonical] = {"status": status, "label": LABELS.get(canonical, canonical),
                              "reasons": list(dict.fromkeys(explanations)), "reason_codes": codes,
                              "counts": counts, "rows": entry.get("rows"),
                              "action": ACTIONS.get(canonical) if status != "available" else None}
    return details



def build_coverage_report(coverage):
    return {"contract": COVERAGE_CONTRACT, "metadata_available": bool(coverage),
            "meaning": "输入完整性，不是任务执行状态；可用不保证每个字段都已知，也不表示工具成功",
            "status_meanings": dict(STATUS_LABELS),
            "datasets": _describe(coverage or {})}


def coverage_details(coverage):
    return {key: value for key, value in build_coverage_report(coverage)["datasets"].items()
            if value["status"] != "available"}


def coverage_lines(report):
    if not report["metadata_available"]:
        return ["输入未声明覆盖元数据，不能推断为完整。"]
    lines = []
    for item in report["datasets"].values():
        if item["status"] == "available":
            continue
        lines.append(f"{item['label']} [{item['status']} / {STATUS_LABELS.get(item['status'], item['status'])}]："
                     + "；".join(dict.fromkeys(item["reasons"])))
        if item["action"]:
            lines.append("  " + item["action"])
    return lines or ["当前范围的输入均可用；具体字段的未知值仍保留。"]
