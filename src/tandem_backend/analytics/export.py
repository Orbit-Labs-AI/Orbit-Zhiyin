"""Local personal-test exports of existing feature values and their JSON paths."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .dictionary import FEATURES

BASE_FAMILIES = {
    "session": "user_message_count assistant_message_count turn_count total_event_count first_observed_ts last_observed_ts observed_session_span_ms avg_user_message_chars median_user_message_chars avg_assistant_message_chars median_assistant_message_chars language_signals",
    "tools": "call_count paired_result_count known_success_count known_failure_count rejected_count interrupted_count running_count unknown_status_count unpaired_count tool_call_count success_rate failure_rate median_duration_ms p25_duration_ms p75_duration_ms p90_duration_ms duration_sum_ms reliable_interval_union_ms",
    "workflow": "error_count branch_count rollback_rewind_count compaction_count permission_request_count subagent_spawn_count interruption_count repeated_transition_count repeated_transition_rate max_repeated_transition_run consecutive_failed_calls confirmed_same_argument_failed_retries correction_signal_count correction_signal_rate",
    "usage": "request_count total_tokens cost_usd median_latency_ms median_ttft_ms",
    "activity": "sessions_by_day sessions_by_hour human_messages_by_day human_messages_by_hour tool_calls_by_day model_usage_by_day active_days weekday_distribution hour_distribution",
    "text": "cluster_id embedding_x embedding_y top_terms distance_to_cluster_centroid novelty",
    "outcome_subjective": "user_acceptance user_confirmed_completion rework_feedback feedback_target feedback_evidence accepted_feedback_count rejected_feedback_count confirmed_completion_count confirmed_incompletion_count rework_feedback_count",
}
BASE_OWNER = {name: family for family, names in BASE_FAMILIES.items() for name in names.split()}
ACTIVITY_PATHS = {
    "sessions_by_day": "sessions.by_day", "sessions_by_hour": "sessions.by_hour",
    "human_messages_by_day": "human_messages.by_day", "human_messages_by_hour": "human_messages.by_hour",
    "tool_calls_by_day": "tool_calls.by_day", "model_usage_by_day": "model_requests.by_day",
}
PAYLOAD_PATHS = {
    "session": ["overview.counts", "overview.top_languages", "sessions.*.features", "sessions.*.text_measurements", "sessions.*.language_signals"],
    "tools": ["tools", "sessions.*.tools", "projects.*.tools"],
    "workflow": ["workflow", "sessions.*.workflow", "sessions.*.correction_signals"],
    "usage": ["overview.usage", "sessions.*.usage", "projects.*.usage"],
    "activity": ["overview.activity_rhythm"],
    "text": ["text"],
    "outcome_subjective": ["overview.subjective_outcomes", "sessions.*.subjective_outcomes", "projects.*.subjective_outcomes"],
    "instruction": ["instruction", "sessions.*.prompt_structure"],
    "preference": ["preferences"], "task": ["tasks"],
    **{family: [f"bottleneck_features.{family}", f"sessions.*.bottleneck_features.{family}",
                f"projects.*.bottleneck_features.{family}"]
       for family in ("interaction", "respond", "cost_time", "outcome")},
}


def family_of(name, definition):
    return definition.get("family") or (name.split(".")[0] if "." in name else BASE_OWNER[name])


def feature_paths(name, family, definition):
    if definition.get("path_prefix"):
        return [f"bottleneck_features.{name}", f"sessions.*.bottleneck_features.{name}",
                f"projects.*.bottleneck_features.{name}"]
    if family == "session":
        return ["sessions.*.language_signals"] if name == "language_signals" else [f"sessions.*.features.{name}"]
    if family == "tools":
        return ["sessions.*.features.tool_call_count"] if name == "tool_call_count" else [
            f"tools.totals.{name}", f"tools.by_tool.*.{name}", f"sessions.*.tools.totals.{name}",
            f"projects.*.tools.totals.{name}"]
    if family == "workflow":
        if name.startswith("correction_signal"):
            return [f"sessions.*.features.{name}"]
        return [f"workflow.{name}", f"sessions.*.workflow.{name}"]
    if family == "usage":
        return [f"overview.usage.{name}", f"sessions.*.usage.{name}", f"projects.*.usage.{name}"]
    if family == "activity":
        return ["overview.activity_rhythm." + ACTIVITY_PATHS.get(name, name)]
    if family == "text":
        return ["text.top_terms", "text.clusters.*.top_terms"] if name == "top_terms" else [f"sessions.*.{name}"]
    if family == "instruction":
        return [f"instruction.records.*.features.{name}", f"sessions.*.prompt_structure.*.{name}"]
    if family in ("preference", "task"):
        root = "preferences" if family == "preference" else "tasks"
        return [f"{root}.records.*.{name}"]
    if family == "outcome_subjective":
        return [f"overview.subjective_outcomes.counts.{name}",
                f"sessions.*.subjective_outcomes.counts.{name}",
                f"projects.*.subjective_outcomes.counts.{name}"] if name.endswith("_count") else [
                    f"sessions.*.subjective_outcomes.feedback.*.{name}"]
    raise ValueError(f"未配置特征导出路径：{name}")


def observations(root, pattern):
    """Keep exact values, including zero/false/null; provenance is an RFC6901 path."""
    def walk(node, parts, pointer, identity):
        if not parts:
            return [{"source_path": pointer, "entity": identity, "value": node}]
        head, *tail = parts
        if head == "*" and isinstance(node, list):
            rows = []
            for index, item in enumerate(node):
                entity = {**identity, **{key: item[key] for key in (
                    "session_uid", "project_id", "event_uid", "task_id", "preference_id", "name_raw", "cluster_id")
                    if isinstance(item, dict) and key in item}}
                rows.extend(walk(item, tail, pointer + f"/{index}", entity))
            return rows
        if isinstance(node, dict) and head in node:
            escaped = head.replace("~", "~0").replace("/", "~1")
            return walk(node[head], tail, pointer + "/" + escaped, identity)
        return []
    return walk(root, pattern.split("."), "", {})


def family_values(result):
    families = {name: {"features": {}, "payload": []} for name in PAYLOAD_PATHS}
    dictionary = result.get("feature_dictionary", FEATURES)
    for name, definition in dictionary.items():
        family = family_of(name, definition)
        paths = feature_paths(name, family, definition)
        values = [row for path in paths for row in observations(result, path)]
        families[family]["features"][name] = {
            "definition": definition, "paths": paths, "observations": values,
            "emitted_n": len(values), "non_null_n": sum(v["value"] is not None for v in values),
            "missing_reason": None if values else "没有对应记录或此输入未输出字段；不补成 0",
        }
    for family, document in families.items():
        document["payload"] = [row for path in PAYLOAD_PATHS[family] for row in observations(result, path)]
    return families


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _write(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def export_families(result, destination):
    """Export all declared fields, plus family outputs not yet in the dictionary."""
    families = family_values(result)
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    metadata = {key: result[key] for key in (
        "scope", "coverage", "source_coverage", "versions", "effective_samples", "unknown_counts",
        "feature_schema_version", "analysis_digest", "sample_boundary", "selection", "limitations") if key in result}
    manifest = {**metadata, "feature_count": sum(len(doc["features"]) for doc in families.values()),
                "family_count": len(families), "families": {}}
    lines = ["# 个人 feature 测试结果", "", "所有已有字段按族输出；未输出、null、空列表和数值 0 分别保留。",
             "特征 JSON 包含完整值、对应 analytics.json 的路径和定义；族 payload 保留未登记的额外测量、证据和覆盖说明。",
             "同一字段可有总体、会话、项目、记录多个粒度；本导出不另外求平均或相加。", ""]
    zone = ZoneInfo(result["scope"]["display_timezone"])
    for key in ("from_ts", "until_ts"):
        value = result["scope"].get(key)
        if value is not None:
            lines.append(f"{key}: {datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(zone).isoformat()}")
    lines.extend(["", f"{manifest['feature_count']} 项字段，{len(families)} 个族。", "",
                  "| 族 | 字段数 | 完整值 |", "| --- | ---: | --- |"])
    for family, document in families.items():
        fields = document["features"]
        manifest["families"][family] = {"feature_count": len(fields), "features": list(fields),
                                         "json": family + ".json", "markdown": family + ".md"}
        _write(destination / (family + ".json"), _json({"family": family, **metadata, **document}) + "\n")
        page = [f"# {family}：完整 feature 值", "", "source_path 指向同次计算的 analytics.json。null 保持未知；无记录不补数值。", ""]
        for name, field in fields.items():
            page.extend([f"## {name}", "", f"单位：{field['definition'].get('unit')}；规则：{field['definition'].get('rule')}", "",
                         "```json", _json({key: field[key] for key in (
                             "observations", "emitted_n", "non_null_n", "missing_reason")}), "```", ""])
        _write(destination / (family + ".md"), "\n".join(page))
        lines.append(f"| {family} | {len(fields)} | [Markdown]({family}.md) · [JSON]({family}.json) |")
    lines.extend(["", "## 字段速查", "", "下表只预览总体值；记录、会话和项目的全部值在上方对应族文件。", "",
                  "| 族 | 字段 | 总体预览 / 输出记录 | 非 null / 全部值 |", "| --- | --- | --- | ---: |"])
    for family, document in families.items():
        for name, field in document["features"].items():
            aggregate = next((row for row in field["observations"] if not row["entity"]), None)
            preview = json.dumps(aggregate["value"], ensure_ascii=False) if aggregate else field["missing_reason"] or "逐记录值"
            if len(preview) > 120:
                preview = preview[:117] + "…"
            preview = preview.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {family} | {name} | {preview} | {field['non_null_n']} / {field['emitted_n']} |")
    _write(destination / "index.json", _json(manifest) + "\n")
    _write(destination / "README.md", "\n".join(lines) + "\n")
    return {"feature_count": manifest["feature_count"], "family_count": len(families),
            "report": str((destination / "README.md").resolve())}
