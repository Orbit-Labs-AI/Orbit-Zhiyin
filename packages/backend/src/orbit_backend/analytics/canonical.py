"""Adapt the main data reader's L2/L3 bundle without re-reading legacy history."""

from .inputs import AnalysisInputBundle, Scope


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
    # Canonical model_call deliberately keeps call/delta evidence in its linked
    # usage event. Only that evidence can establish a reliable request boundary.
    if data.get("projection_run_id") is not None:
        bundle.events = None if bundle.events is None else [{**event, "kind": "turn.interrupted"}
                         if event["kind"] == "turn.end" and event.get("attrs", {}).get("status") == "interrupted"
                         else event for event in bundle.events or []]
        calls = []
        for call in bundle.model_calls or []:
            if "request_identity_quality" in call or "boundary_quality" in call:
                calls.append(dict(call))
                continue  # Current L3 contract carries its own audited identity and boundary.
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
    for key in ("source_ids", "agent_ids", "project_ids", "model_ids", "effort_raw", "root_session_uids"):
        before, after = original.get(key), getattr(scope, key)
        if before is not None and (after is None or not set(after) <= set(before)):
            raise ValueError("已保存分析输入的筛选只能缩小；扩大范围请重新调用 read_analysis")
    if original.get("include_children") is False and scope.include_children:
        raise ValueError("已保存输入不含子代理；请重新调用 read_analysis")
    if not set(original.get("excluded_session_uids", ())) <= set(scope.excluded_session_uids):
        raise ValueError("已保存输入的排除名单不能移除；请重新调用 read_analysis")
    return scope

