"""Thin boundary: legacy SQLite is not the target L2/L3 schema."""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..feedback import SCENE_LABELS, task_contexts
from ..models import Event, stable_id
from ..store import Store, _decode_sample_policy


def millis(value):
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return round(dt.timestamp() * 1000) if dt.tzinfo else None
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def coverage(status, rows=None, reason=None, **extra):
    return {"status": status, "rows": rows, "reason": reason, **extra}


@dataclass
class Scope:
    display_timezone: str = "UTC"
    project_ids: list[str] | None = None
    model_ids: list[str] | None = None
    effort_raw: list[str] | None = None
    from_ts: int | None = None
    until_ts: int | None = None
    root_session_uids: list[str] | None = None
    excluded_session_uids: list[str] = field(default_factory=list)
    include_children: bool = True
    scene: str | None = None
    legacy_project_ids: list[str] | None = None

    def __post_init__(self):
        try:
            ZoneInfo(self.display_timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("display_timezone 必须是 IANA 时区名") from exc
        for value in (self.from_ts, self.until_ts):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError("from_ts/until_ts 必须是 UTC 毫秒整数")
        if self.from_ts is not None and self.until_ts is not None and self.from_ts >= self.until_ts:
            raise ValueError("时间范围必须满足 from_ts < until_ts")
        if self.scene and self.scene not in SCENE_LABELS:
            raise ValueError("未知的分析场景")

    def contains(self, ts):
        if ts is None:
            return self.from_ts is None and self.until_ts is None
        return ((self.from_ts is None or ts >= self.from_ts)
                and (self.until_ts is None or ts < self.until_ts))


@dataclass
class AnalysisInputBundle:
    sessions: list[dict]
    events: list[dict] | None
    tool_calls: list[dict] | None
    model_calls: list[dict] | None
    coverage: dict
    projects: list[dict] | None = None
    turns: list[dict] | None = None
    versions: dict = field(default_factory=dict)
    sample_boundary: dict = field(default_factory=dict)
    input_contract: str = "analysis-input-v1"
    statistical_members: dict | None = None

    @classmethod
    def from_dict(cls, data):
        if data.get("input_contract") != "analysis-input-v1":
            raise ValueError("不支持的分析输入契约")
        cov = dict(data.get("coverage", {}))
        # The contract fixture uses singular entity names in coverage.
        for one, many in (("tool_call", "tool_calls"), ("model_call", "model_calls")):
            if one in cov and many not in cov:
                cov[many] = cov[one]
        fields = {}
        for name in ("events", "tool_calls", "model_calls", "projects", "turns"):
            state = cov.get(name, {}).get("status")
            fields[name] = None if state in ("unavailable", "excluded") else data.get(name)
            if name not in cov:
                cov[name] = coverage("partial" if fields[name] is not None else "unavailable",
                                     len(fields[name]) if fields[name] is not None else None,
                                     "调用方未声明完整覆盖")
        versions = data.get("versions", {})
        if "projection_run_id" in data:
            versions = {k: data.get(k) for k in ("db_schema_version", "parser_version",
                        "derivation_version", "redaction_version", "projection_run_id")}
            versions.update(storage="tandem-session-v1", content_digest=stable_id(
                versions, data.get("sample_boundary"), data.get("statistical_members")))
        return cls(sessions=data.get("sessions", []), coverage=cov, **fields,
                   versions=versions, sample_boundary=data.get("sample_boundary", {}),
                   statistical_members=data.get("statistical_members"))


KINDS = {"user_message": "message.user", "assistant_message": "message.assistant",
         "tool_call": "tool.call", "tool_result": "tool.result", "usage": "model.usage",
         "turn_started": "turn.started", "turn_completed": "turn.completed",
         "turn_interrupted": "turn.interrupted"}


def tool_identity(name):
    name = name or "unknown"
    short = name.rsplit(".", 1)[-1]
    result = {"name_raw": name, "kind": "other", "mcp_server": None, "mcp_tool": None,
              "skill": None, "command_head": None, "is_wrapper": short in ("exec", "wait")}
    if short.startswith("mcp__"):
        pieces = short.split("__", 2)
        if len(pieces) == 3:
            result.update(kind="mcp", mcp_server=pieces[1], mcp_tool=pieces[2])
    elif short in ("exec_command", "write_stdin", "shell", "shell_command"):
        result["kind"] = "shell"
    elif short in ("apply_patch", "edit_file", "write_file"):
        result["kind"] = "file.edit"
    elif short in ("read_file", "view_image"):
        result["kind"] = "file.read"
    elif short in ("spawn_agent", "send_message", "wait_agent", "followup_task"):
        result["kind"] = "subagent"
    elif short.startswith("request_user_input"):
        result["kind"] = "ask_user"
    elif "web" in name and short == "run":
        result["kind"] = "web.search"
    return result


def legacy_bundle(store: Store) -> AnalysisInputBundle:
    """One SQLite read transaction; no source rescans, writes, or field guessing."""
    with store.connect() as conn:
        conn.execute("BEGIN")
        sessions_raw = [json.loads(r[0]) for r in conn.execute("SELECT data FROM sessions ORDER BY id")]
        events_raw = [Event(**json.loads(r[0])) for r in conn.execute(
            "SELECT data FROM events ORDER BY session_id,ordinal")]
        imports = [dict(r) for r in conn.execute("SELECT signature,policy,warnings FROM imports")]
        policies = [dict(r) for r in conn.execute("SELECT source_root,data FROM sample_policies ORDER BY source_root")]
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    sessions, projects = [], {}
    for s in sessions_raw:
        md = s.get("analytics_metadata", {})
        sessions.append({"session_uid": s["id"], "native_id": s["id"], "source_id": None,
                         "kind": md.get("kind", "unknown"), "root_uid": md.get("root_uid"),
                         "parent_uid": md.get("parent_uid"), "forked_from": s.get("parent_id"),
                         "replay_boundary_unknown": bool(s.get("parent_id")),
                         "project_id": None, "legacy_project_id": s["project_id"],
                         "title": s["title"], "started_at": millis(s.get("started_at")),
                         "timezone": None, "timezone_source": "unknown"})
        projects[s["project_id"]] = {"project_id": None, "legacy_project_id": s["project_id"],
                                     "name": s["project"], "identity_quality": "legacy_path"}
    # Reuse established task/scene derivation only on confirmed human observations.
    mains = {s["session_uid"] for s in sessions if s["kind"] == "main"}
    humans = [e for e in events_raw if e.kind == "user_message"
              and e.details.get("origin") == "human" and e.session_id in mains]
    contexts = task_contexts(humans)
    active, events, calls, pending, turns = {}, [], [], {}, {}
    for e in events_raw:
        attrs = dict(e.details)
        if e.id in contexts:
            active[e.session_id] = contexts[e.id]
        ctx = active.get(e.session_id, {})
        attrs.update(scene=ctx.get("scene"), task_id=ctx.get("task_id"), task_id_source="legacy_inferred")
        attrs["time"] = {"source_field": "timestamp", "semantics": "written",
                         "quality": "reported" if e.timestamp else "missing"}
        if e.kind == "usage":
            attrs.update(usage_scope="unknown", measurement="cumulative", coverage="unknown",
                         snapshot_key=None, reported=e.details.get("cumulative_tokens"))
        uid = stable_id(e.session_id, e.turn_id) if e.turn_id else None
        event = {"event_uid": e.id, "session_uid": e.session_id, "seq": e.ordinal,
                 "kind": KINDS.get(e.kind, e.kind), "ts": millis(e.timestamp), "turn_uid": uid,
                 "actor": "human" if attrs.get("origin") == "human" else "unknown",
                 "text": e.text if e.kind.endswith("message") else None,
                 "text_truncated": e.details.get("original_chars", len(e.text)) > len(e.text),
                 "attrs": attrs, "record_uid": None, "legacy_source_line": e.ordinal}
        events.append(event)
        if uid:
            if uid not in turns:
                turns[uid] = {"turn_uid": uid, "session_uid": e.session_id,
                              "idx": len(turns), "first_event_uid": e.id, "status": "unknown"}
            turns[uid]["last_event_uid"] = e.id
        if e.kind == "tool_call":
            call = {"call_uid": e.id, "session_uid": e.session_id, "turn_uid": uid,
                    "call_event_uid": e.id, "result_event_uid": None, "seq": e.ordinal,
                    **tool_identity(e.tool), "status": None, "status_scope": None,
                    "argument_digest": e.details.get("argument_digest"),
                    "argument_digest_kind": "literal", "started_at": millis(e.timestamp),
                    "ended_at": None, "duration_ms": None, "duration_source": None,
                    "duration_quality": "missing", "interval_reliable": False}
            calls.append(call)
            if e.call_id:
                pending[(e.session_id, e.call_id)] = call
        elif e.kind == "tool_result":
            call = pending.pop((e.session_id, e.call_id), None)
            if call is not None:
                call.update(result_event_uid=e.id, status=e.status, status_scope=attrs.get("status_scope"),
                            ended_at=millis(e.timestamp), duration_ms=e.duration_ms,
                            duration_source="event_difference" if e.duration_ms is not None else None,
                            duration_quality="estimated" if e.duration_ms is not None else "missing")
                for key in ("known_command_results", "failed_command_results", "unknown_return_values"):
                    call[key] = attrs.get(key)
    unknown_origins = sum(e["kind"] == "message.user" and e["attrs"].get("origin", "unknown") == "unknown" for e in events)
    warnings = sum(len(json.loads(i["warnings"])) for i in imports)
    cov = {
        "sessions": coverage("partial", len(sessions), "只读入旧导入器允许的会话；子代理已在上游跳过",
                             unknown_rows=sum(s["kind"] == "unknown" for s in sessions)),
        "human_origin": coverage("partial" if unknown_origins else "available", len(humans),
                                 "只接受原生 user_message 回执/问答答案或显式 origin=human", unknown_rows=unknown_origins),
        "events": coverage("partial", len(events), "旧解析器只保存部分事件种类；不代表完整 L2",
                           time_unknown_rows=sum(e["ts"] is None for e in events), parser_warning_count=warnings),
        "tool_calls": coverage("partial" if warnings else "available", len(calls),
                               "所选已导入文件中的显式调用；exec 包装内工具不展开"),
        "turns": coverage("partial", len(turns), "保留原生 turn_id；缺失轮次不按用户消息补造"),
        "projects": coverage("unavailable", None, "只有 legacy cwd 分组，无规范 project_id"),
        "model_calls": coverage("unavailable", None, "无逐次请求边界；event.model 不是请求模型"),
        "usage": coverage("partial", sum(e["kind"] == "model.usage" for e in events),
                          "旧累计值无 snapshot_key/计数周期/覆盖，仅保留末次原生报告"),
        "lineage": coverage("partial", None, "forked_from 不是 parent_uid；没有子会话树或复制段边界"),
        "inventory": coverage("unavailable", None, "未接入 inventory_item"),
        "workflow_kinds": coverage("partial", None, "只支持保留的消息、工具与 turn.interrupted"),
        "prompt_structure": coverage("partial", None, "规范正文已剔除引用/围栏，原始代码块统计不可恢复"),
    }
    boundary = []
    for p in policies:
        policy = _decode_sample_policy(p["data"])
        cutoff = millis(policy["before"])
        boundary.append({"source_id": stable_id(p["source_root"]), "legacy_before_inclusive": cutoff,
                         "equivalent_until_ts": cutoff + 1 if cutoff is not None else None,
                         "excluded_sessions": len(policy["exclude"])})
    digest = stable_id(json.dumps([sessions_raw, [e.to_dict() for e in events_raw], imports, boundary],
                                  sort_keys=True, ensure_ascii=False))
    return AnalysisInputBundle(sessions, events, calls, None, cov, list(projects.values()), list(turns.values()),
        {"db_schema_version": schema or None, "storage": "legacy-json-ledger",
         "parser_version": sorted({json.loads(i["policy"]).get("parser", 0) for i in imports}),
         "derivation_version": "legacy-adapter-v1", "redaction_version": None, "content_digest": digest},
        {"ledger_policies": boundary})


def select(bundle: AnalysisInputBundle, scope: Scope):
    """Select members, then keep bounded linked context without counting it."""
    if bundle.statistical_members is not None:
        return select_canonical(bundle, scope)
    if scope.project_ids and bundle.coverage.get("projects", {}).get("status") == "unavailable":
        raise ValueError("规范 project_id 不可用；路径分组请使用 legacy_project_ids")
    if (scope.model_ids or scope.effort_raw) and bundle.model_calls is None:
        raise ValueError("model_ids/effort_raw 需要逐次 model_call；旧 session.model 不可替代")
    excluded, sessions = defaultdict(int), []
    for s in bundle.sessions:
        sid, root = s["session_uid"], s.get("root_uid")
        reason = None
        if sid in scope.excluded_session_uids or root in scope.excluded_session_uids:
            reason = "explicit"
        elif s.get("replay_boundary_unknown"):
            reason = "fork_replay_boundary_unknown"
        elif s.get("kind") in ("review", "automation", "import", "auxiliary"):
            reason = "non_collaboration_session"
        elif not scope.include_children and s.get("kind") in ("subagent", "workflow_agent"):
            reason = "children_disabled"
        elif scope.root_session_uids is not None and root not in scope.root_session_uids:
            reason = "root_filter"
        elif scope.project_ids is not None and s.get("project_id") not in scope.project_ids:
            reason = "project_filter"
        elif scope.legacy_project_ids is not None and s.get("legacy_project_id") not in scope.legacy_project_ids:
            reason = "legacy_project_filter"
        if reason:
            excluded[reason] += 1
        else:
            sessions.append(s)
    ids = {s["session_uid"] for s in sessions}
    all_events = sorted((e for e in (bundle.events or []) if e["session_uid"] in ids),
                        key=lambda e: (e["session_uid"], e["seq"], e["event_uid"]))
    replayed = {e["event_uid"] for e in all_events if e.get("attrs", {}).get("replayed_from")
                or e.get("attrs", {}).get("duplicate_of")}
    all_events = [e for e in all_events if e["event_uid"] not in replayed]
    model_calls = None if bundle.model_calls is None else [c for c in bundle.model_calls
        if c["session_uid"] in ids and scope.contains(c.get("ts"))
        and (scope.model_ids is None or c.get("model_id") in scope.model_ids)
        and (scope.effort_raw is None or c.get("effort_raw") in scope.effort_raw)]
    model_filter = scope.model_ids is not None or scope.effort_raw is not None
    matching_turns = {c.get("turn_uid") for c in model_calls or [] if c.get("turn_uid")}
    ambiguous_turns = set()
    if model_filter:
        selected_calls = {c["call_uid"] for c in model_calls or []}
        ambiguous_turns = {c.get("turn_uid") for c in bundle.model_calls or [] if c["session_uid"] in ids
                           and c.get("turn_uid") in matching_turns and c["call_uid"] not in selected_calls}
        matching_turns -= ambiguous_turns
    def event_member(e):
        return (scope.contains(e.get("ts")) and (not model_filter or e.get("turn_uid") in matching_turns)
                and (scope.scene is None or e.get("attrs", {}).get("scene") == scope.scene))
    members = [e for e in all_events if event_member(e)]
    member_ids = {e["event_uid"] for e in members}
    lookup = {e["event_uid"]: e for e in all_events}
    calls = None if bundle.tool_calls is None else []
    for c in bundle.tool_calls or []:
        if c["session_uid"] not in ids or c.get("call_event_uid") in replayed:
            continue
        event = lookup.get(c.get("call_event_uid"))
        selected = (event_member(event) if event else scope.contains(c.get("started_at"))
                    and (not model_filter or c.get("turn_uid") in matching_turns) and scope.scene is None)
        if not selected:
            continue
        c = dict(c)
        if event:
            c["seq"] = event["seq"]
            for key in ("argument_digest", "command_head", "files"):
                if c.get(key) is None and event.get("attrs", {}).get(key) is not None:
                    c[key] = event["attrs"][key]
        result = lookup.get(c.get("result_event_uid"))
        if result:
            for key in ("status_scope", "known_command_results", "failed_command_results", "unknown_return_values"):
                if c.get(key) is None and result.get("attrs", {}).get(key) is not None:
                    c[key] = result["attrs"][key]
        # Future dated results cannot leak into an earlier snapshot. Unknown-time
        # linked results can support status/duration, never calendar membership.
        end = c.get("ended_at")
        future = scope.until_ts is not None and ((end is not None and end >= scope.until_ts)
                    or (result and result.get("ts") is not None and result["ts"] >= scope.until_ts))
        if future:
            for key in ("result_event_uid", "status", "duration_ms", "ended_at", "status_scope",
                        "known_command_results", "failed_command_results", "unknown_return_values",
                        "exit_code", "error_class", "approval_wait_ms"):
                c[key] = None
            c.update(duration_quality="missing", duration_source=None, interval_reliable=False)
        calls.append(c)
    if calls is not None:
        calls.sort(key=lambda c: (c["session_uid"], c.get("seq", 0), c["call_uid"]))
    visible_ids = {e["session_uid"] for e in members} | {c["session_uid"] for c in (model_calls or [])}
    bounded = scope.from_ts is not None or scope.until_ts is not None or model_filter or scope.scene
    if bounded:
        sessions = [s for s in sessions if s["session_uid"] in visible_ids
                    or any(c["session_uid"] == s["session_uid"] for c in calls or [])]
    context_events = []
    for c in calls or []:
        result = lookup.get(c.get("result_event_uid"))
        if result and result["event_uid"] not in member_ids:
            context_events.append(result)
    diagnostics = {"excluded_sessions": dict(excluded), "replayed_events_excluded": len(replayed),
                   "model_ambiguous_turns_excluded": len(ambiguous_turns),
                   "context_events": context_events,
                   "time_unknown_events": sum(e.get("ts") is None for e in all_events),
                   "time_unknown_excluded_from_bounded_counts": sum(e.get("ts") is None for e in all_events)
                       if scope.from_ts is not None or scope.until_ts is not None else 0,
                   "selected_event_ids": member_ids}
    return sessions, members, calls, model_calls, diagnostics


def select_canonical(bundle, scope):
    """Honor the data layer's scoped membership; linked context is never counted twice."""
    ids = set(bundle.statistical_members["event_uids"])
    events = bundle.events or []
    if scope.scene:
        humans = [Event(e["event_uid"], e["session_uid"], e["seq"], "user_message", None,
                        text=e.get("text") or "", details=e["attrs"])
                  for e in events if e["kind"] == "message.user" and e["attrs"].get("origin") == "human"]
        contexts, active, selected = task_contexts(humans), {}, set()
        for event in events:
            eid, sid = event["event_uid"], event["session_uid"]
            if eid in contexts:
                active[sid] = contexts[eid]["scene"]
            if eid in ids and active.get(sid) == scope.scene:
                selected.add(eid)
        ids = selected
    members = [e for e in events if e["event_uid"] in ids]
    calls = None if bundle.tool_calls is None else [c for c in bundle.tool_calls
            if c.get("call_event_uid") in ids or c.get("result_event_uid") in ids]
    models = None if bundle.model_calls is None else [c for c in bundle.model_calls if c["usage_event_uid"] in ids]
    visible = {e["session_uid"] for e in members}
    roots = {s["root_uid"] for s in bundle.sessions if s["session_uid"] in visible}
    sessions = [s for s in bundle.sessions if s["session_uid"] in visible | roots]
    linked_results = {c.get("result_event_uid") for c in calls or []}
    diagnostics = {"excluded_sessions": {}, "replayed_events_excluded": 0,
                   "model_ambiguous_turns_excluded": 0,
                   "context_events": [e for e in events if e["event_uid"] not in ids and e["event_uid"] in linked_results],
                   "time_unknown_events": sum(e.get("ts") is None for e in members),
                   "time_unknown_excluded_from_bounded_counts": sum(e.get("ts") is None for e in events if e["event_uid"] not in ids),
                   "selected_event_ids": ids}
    return sessions, members, calls, models, diagnostics


def metadata(bundle, scope, diagnostics):
    return {"input_contract": bundle.input_contract, "scope": asdict(scope),
            "versions": bundle.versions, "sample_boundary": bundle.sample_boundary,
            "coverage": bundle.coverage,
            "selection": {k: v for k, v in diagnostics.items() if k not in ("selected_event_ids", "context_events")}}
