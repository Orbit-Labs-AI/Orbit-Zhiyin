"""Describe what is observed; keep unsupported causal and personality claims out."""

import math
from collections import Counter, defaultdict
from datetime import datetime

from .bottlenecks import diagnose
from .feedback import SCENE_LABELS, signals, task_contexts
from .models import Event
from .store import Store


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> list[float] | None:
    """A binomial reference interval; correlated sessions weaken its interpretation."""
    if trials == 0:
        return None
    if not 0 <= successes <= trials:
        raise ValueError("successes 必须在 0 和 trials 之间")
    p, z2 = successes / trials, z * z
    denominator = 1 + z2 / trials
    center = (p + z2 / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials)) / denominator
    return [round(max(0, center - half), 4), round(min(1, center + half), 4)]


def union_duration(intervals: list[tuple[float, float]]) -> float:
    """Merge nested/concurrent intervals; never double-count the same elapsed second."""
    for start, end in intervals:
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("执行区间无效")
    total, left, right = 0.0, None, None
    for start, end in sorted(intervals):
        if left is None:
            left, right = start, end
        elif start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return total + (right - left if left is not None else 0)


def analyze(store: Store, project_id: str | None = None, model: str | None = None,
            before: str | None = None, scene: str | None = None) -> dict:
    from .models import utc_time
    cutoff = utc_time(before) if before else None
    if before and not cutoff:
        raise ValueError("before 必须是带时区的 ISO 时间")
    if scene and scene not in SCENE_LABELS:
        raise ValueError("未知的分析场景")
    events = store.events(project_id=project_id, model=model)
    if cutoff:
        events = [e for e in events if e.timestamp and e.timestamp <= cutoff]
    context_by_id = task_contexts(events)
    all_observed = signals(events, context_by_id)
    all_bottlenecks, all_gaps = diagnose(events, all_observed, context_by_id)
    if scene:
        # Keep the whole task span after its request. Filtering only messages would
        # remove the results needed to diagnose a bottleneck.
        active_scene = {}
        visible_events = []
        for e in events:
            if e.kind == "user_message":
                active_scene[e.session_id] = context_by_id[e.id]["scene"]
            if active_scene.get(e.session_id) == scene:
                visible_events.append(e)
        events = visible_events
    sessions_by_id = {s["id"]: s for s in store.sessions(project_id)}
    visible = {e.session_id for e in events}
    sessions_by_id = {k: v for k, v in sessions_by_id.items() if k in visible}
    users = [e for e in events if e.kind == "user_message"]
    user_sessions = {e.session_id for e in users}
    visible_user_ids = {e.id for e in users}
    observed = [s for s in all_observed if s.event_id in visible_user_ids]
    preferences = _preferences(observed, user_sessions, sessions_by_id)
    contexts = []
    for key in SCENE_LABELS:
        scene_users = [e for e in users if context_by_id[e.id]["scene"] == key]
        scene_signals = [s for s in observed if s.scene == key]
        if not scene_users:
            continue
        readers = {r["id"]: r for e in scene_users for r in context_by_id[e.id]["readers"]}
        contexts.append({"scene": key, "label": SCENE_LABELS[key],
                         "user_messages": len(scene_users), "user_sessions": len({e.session_id for e in scene_users}),
                         "languages": dict(Counter(context_by_id[e.id]["language"] for e in scene_users)),
                         "preferences": _preferences(scene_signals, {e.session_id for e in scene_users}, sessions_by_id),
                         "readers": list(readers.values())})
    # A revision can refer to a previous reply whose original request used a
    # different scene label. Preserve that evidence without counting it as a new
    # selected-scene requirement; the evidence endpoint can retrieve either side.
    bottlenecks = [b for b in all_bottlenecks if (not scene or b["scene"] == scene)
                   and set(b["profile_evidence_ids"]) <= visible_user_ids]
    gaps = [g for g in all_gaps if g["request_event_id"] in visible_user_ids]
    calls = [e for e in events if e.kind == "tool_call"]
    results = [e for e in events if e.kind == "tool_result"]
    failed = [e for e in results if e.status == "failed"]
    duration = _timing(results)
    return {
        "schema_version": "1.6", "analysis_version": "context-v14",
        "scope": {"project_id": project_id, "model": model, "before": cutoff, "scene": scene},
        "ledger_sample_policies": store.sample_policies(),
        "counts": {"sessions": len(sessions_by_id), "projects": len({s["project_id"] for s in sessions_by_id.values()}),
                   "events": len(events), "user_messages": len(users), "user_sessions": len(user_sessions),
                   "tool_calls": len(calls), "explicit_tool_failures": len(failed)},
        "models": dict(Counter(e.model for e in events if e.kind in ("assistant_message", "tool_call"))),
        "projects": [{"id": pid, "name": next(s["project"] for s in sessions_by_id.values() if s["project_id"] == pid),
                      "sessions": sum(s["project_id"] == pid for s in sessions_by_id.values())}
                     for pid in sorted({s["project_id"] for s in sessions_by_id.values()})],
        "preferences": preferences, "contexts": contexts, "bottlenecks": bottlenecks, "timing": duration,
        "data_gaps": gaps,
        "profile": {"basis": "explicit_requirements", "communication": [p for p in preferences if p["target"] == "communication"],
                    "workflow": [p for p in preferences if p["target"] == "workflow"], "contexts": contexts, "stability": "unverified"},
        "limitations": ["没有反馈不代表满意。", "规则识别的是候选证据，需要回看上下文。",
                        "同一任务或 fork 的会话可能相关；参考区间不能证明长期偏好。",
                        "记录中两次时间戳的跨度不等于模型计算时间或你的工作时间。"],
    }


def _preferences(observed: list, user_sessions: set, sessions_by_id: dict) -> list[dict]:
    """The same counting rule applies globally and within each task context."""
    by_dimension = defaultdict(list)
    for signal in observed:
        by_dimension[signal.dimension].append(signal)
    preferences = []
    for dimension, items in by_dimension.items():
        support = {s.session_id for s in items}
        projects = {sessions_by_id[s]["project_id"] for s in support if s in sessions_by_id}
        # Explicit requirements are useful even with one sample, but cannot establish stability.
        scope = "cross_project_candidate" if len(projects) > 1 and len(support) >= 3 else "observed_request"
        evidence = [s.to_dict() for s in items[:5]]
        readers = {r["id"]: r for s in items for r in s.readers}
        preferences.append({"dimension": dimension, "label": items[0].label,
                            "sessions": len(support), "projects": len(projects),
                            "denominator": len(user_sessions), "scope": scope, "target": items[0].target,
                            "scenes": dict(Counter(s.scene for s in items)),
                            "readers": list(readers.values()),
                            "reference_interval": wilson_interval(len(support), len(user_sessions)),
                            "evidence": evidence})
    preferences.sort(key=lambda p: (-p["sessions"], p["dimension"]))
    return preferences


def _timing(results: list[Event]) -> dict:
    by_session = defaultdict(list)
    for e in results:
        if e.duration_ms is not None and e.timestamp and e.details.get("start"):
            by_session[e.session_id].append((datetime.fromisoformat(e.details["start"]).timestamp(),
                                             datetime.fromisoformat(e.timestamp).timestamp()))
    return {"paired_calls": sum(len(v) for v in by_session.values()), "result_count": len(results),
            "logged_coverage_seconds": round(sum(union_duration(v) for v in by_session.values()), 3),
            "meaning": "各会话内已配对工具记录的覆盖跨度；跨会话相加只用于描述采样规模。"}
