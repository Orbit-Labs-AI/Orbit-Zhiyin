"""Adapt the main data reader's L2/L3 bundle without re-reading legacy history."""

import hashlib
import json

from .inputs import AnalysisInputBundle, Scope, coverage


def canonical_bundle(data):
    bundle = AnalysisInputBundle.from_dict(data)
    lookup = {event["event_uid"]: event for event in bundle.events or []}
    selection = data.get("statistical_members")
    if selection is not None:
        members = set(selection["event_uids"])
        if members - lookup.keys():
            raise ValueError("statistical_members 引用了不存在的事件")
        reader_scope = Scope(**data["scope"])
        if any(not reader_scope.contains(lookup[uid].get("ts")) for uid in members):
            raise ValueError("统计成员超出数据读取接口声明的时间范围")
        bundle.statistical_event_uids = members

    # Canonical model_call deliberately keeps call/delta evidence in its linked
    # usage event. Only that evidence can establish a reliable request boundary.
    if data.get("projection_run_id") is not None:
        bundle.events = None if bundle.events is None else [{**event, "kind": "turn.interrupted"}
                         if event["kind"] == "turn.end" and event.get("attrs", {}).get("status") == "interrupted"
                         else event for event in bundle.events or []]
        calls = []
        for call in bundle.model_calls or []:
            event = lookup.get(call.get("usage_event_uid"), {})
            attrs = event.get("attrs", {})
            request_key = attrs.get("request_key")
            reliable = (event.get("kind") == "model.usage"
                        and event.get("session_uid") == call.get("session_uid")
                        and attrs.get("usage_scope") == "call"
                        and attrs.get("measurement") == "delta"
                        and isinstance(request_key, list) and bool(request_key)
                        and bool(call.get("request_id"))
                        and call["request_id"] == attrs.get("request_id"))
            calls.append({**call, "usage_scope": attrs.get("usage_scope"),
                          "measurement": attrs.get("measurement"),
                          "boundary_reliable": reliable,
                          "boundary_evidence_event_uid": event.get("event_uid")})
        bundle.model_calls = calls if bundle.model_calls is not None else None
        bundle.versions = {**bundle.versions, "storage": "tandem-session-v1",
                           **{key: data.get(key) for key in (
                               "db_schema_version", "parser_version", "derivation_version",
                               "redaction_version", "projection_run_id")},
                           "content_digest": hashlib.sha256(json.dumps(
                               data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
        for name in ("sessions", "projects", "turns"):
            items = getattr(bundle, name, None)
            bundle.coverage[name] = coverage("available" if items is not None else "unavailable",
                                             len(items) if items is not None else None,
                                             "main read_analysis 已选择的规范实体；范围见 sample_boundary")
        bundle.coverage["lineage"] = coverage(
            "partial" if any(s.get("lineage_unresolved", True) for s in bundle.sessions) else "available",
            len(bundle.sessions), "main 规范会话的 parent/root/fork 字段；未解决关系保留未知")
        bundle.sample_boundary = {**bundle.sample_boundary, "reader_scope": data.get("scope"),
                                  "statistical_member_counts": {key: len(value) for key, value in (selection or {}).items()},
                                  "context_event_count": len(bundle.events or []) - len(selection["event_uids"])
                                  if selection is not None else None}
    return bundle


def input_scope(data, options):
    """Saved selections can be narrowed, never silently widened."""
    original = data.get("scope", {})
    values = {key: value for key, value in original.items() if key in Scope.__dataclass_fields__}
    values.update({key: value for key, value in options.items() if value is not None})
    scope = Scope(**values)
    for key, before, after in (("from_ts", original.get("from_ts"), scope.from_ts),
                               ("until_ts", original.get("until_ts"), scope.until_ts)):
        if before is not None and (after is None or (after < before if key == "from_ts" else after > before)):
            raise ValueError("已保存分析输入的时间范围只能缩小；扩大范围请重新调用 read_analysis")
    for key in ("project_ids", "model_ids", "effort_raw", "root_session_uids"):
        before, after = original.get(key), getattr(scope, key)
        if before is not None and (after is None or not set(after) <= set(before)):
            raise ValueError("已保存分析输入的筛选只能缩小；扩大范围请重新调用 read_analysis")
    if original.get("include_children") is False and scope.include_children:
        raise ValueError("已保存输入不含子代理；请重新调用 read_analysis")
    if not set(original.get("excluded_session_uids", ())) <= set(scope.excluded_session_uids):
        raise ValueError("已保存输入的排除名单不能移除；请重新调用 read_analysis")
    return scope


def read_canonical(home, scope):
    try:
        from tandem_data.analysis_input import AnalysisScope, read_analysis
        from tandem_data.store import readonly_connection
    except ImportError as exc:
        raise ValueError("请安装 packages/data 及其依赖，或用 --analysis-input 读取其导出的 JSON") from exc
    with readonly_connection(home / "tandem.db") as connection:
        count = connection.execute("SELECT COUNT(*) FROM v_analysis_event").fetchone()[0]
    if scope.scene is not None or scope.legacy_project_ids is not None:
        raise ValueError("规范数据读取不支持旧 scene/legacy_project_id 筛选")
    arguments = {key: getattr(scope, key) for key in AnalysisScope.__dataclass_fields__}
    return read_analysis(home, AnalysisScope(**arguments), max_events=count + 1)
