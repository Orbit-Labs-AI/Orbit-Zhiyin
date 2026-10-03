"""Task episodes and immutable past/future windows; no random temporal split."""

import hashlib
from dataclasses import asdict

from orbit_backend.analytics.context import AnalysisContext
from orbit_backend.analytics.inputs import Scope
from orbit_backend.data_access.store import CanonicalStore

from .contracts import Episode, TemporalSample

DAY_MS = 86400000
FUTURE_MS = 72 * 3600000


def digest_id(*values):
    return hashlib.sha256("\x00".join(str(v) for v in values).encode()).hexdigest()


def episode_index(home):
    """Use the shared task partition for evaluation sampling, never recommendation input.

    Candidate boundaries remain unreviewed; task counts are not true labels.
    Unknown timestamps, goal-less episodes and subagent-only activity are excluded.
    """
    scope = Scope(agent_ids=["codex"])
    bundle = CanonicalStore(home).analysis_bundle(scope)
    context = AnalysisContext.select(bundle, scope)
    events = {e["event_uid"]: e for e in context.events}
    episodes, excluded = [], []
    for task in context.work_index.task_result["records"]:
        starts = [b["start"].get("ts") for b in task["task_boundaries"]]
        roots = sorted(
            {
                context.session_map[sid].get("root_uid") or sid
                for sid in task["related_session_ids"]
                if sid in context.main_ids
            }
        )
        if not roots or not starts or any(ts is None for ts in starts) or not task.get("task_goal"):
            excluded.append(
                {"task_uid": task["task_uid"], "reason": "goal_main_human_or_start_time_missing"}
            )
            continue
        ends = [b["end"].get("ts") if b.get("end") else None for b in task["task_boundaries"]]
        episodes.append(
            Episode(
                task_uid=task["task_uid"],
                root_session_uids=roots,
                project_id=task.get("project_id"),
                start_ts=min(starts),
                end_ts=max(ends) if ends and all(ts is not None for ts in ends) else None,
                human_event_uids=[uid for uid in task["human_evidence_ids"] if uid in events],
                boundary_quality=task["task_identity_quality"],
                goal_observed=True,
            )
        )
    observed = [e["ts"] for e in context.events if e.get("ts") is not None]
    return {
        "episodes": sorted(episodes, key=lambda e: (e.start_ts, e.task_uid)),
        "event_times": {uid: e.get("ts") for uid, e in events.items()},
        "observed_from_ts": min(observed) if observed else None,
        "observed_until_ts": max(observed) + 1 if observed else None,
        "excluded": excluded,
        "selected_main_sessions": len(context.main_ids),
        "scope": asdict(scope),
    }


def make_sample(index, *, user_id, anchor_ts, history_days=7, future_task_limit=5):
    if index["observed_until_ts"] is None:
        raise ValueError("No timestamped human-task history")
    future_until = anchor_ts + FUTURE_MS
    tasks = []
    for episode in index["episodes"]:
        if anchor_ts <= episode.start_ts < future_until and len(tasks) < future_task_limit:
            data = episode.model_dump()
            data["human_event_uids"] = [
                uid
                for uid in episode.human_event_uids
                if index["event_times"].get(uid) is not None
                and anchor_ts <= index["event_times"][uid] < future_until
            ]
            if episode.end_ts is not None and episode.end_ts >= future_until:
                data["end_ts"] = None
            tasks.append(Episode.model_validate(data))
    return TemporalSample(
        sample_id=digest_id(
            "temporal-sample-v1", user_id, anchor_ts, history_days, future_task_limit
        ),
        user_id=user_id,
        anchor_ts=anchor_ts,
        history_days=history_days,
        history_from_ts=anchor_ts - history_days * DAY_MS,
        history_until_ts=anchor_ts,
        future_task_limit=future_task_limit,
        future_until_ts=future_until,
        future_tasks=tasks,
        observed_until_ts=index["observed_until_ts"],
        future_complete=len(tasks) == future_task_limit
        or index["observed_until_ts"] >= future_until,
    )


def history_scope(sample, **overrides):
    values = {
        "display_timezone": "Asia/Shanghai",
        "agent_ids": ["codex"],
        "from_ts": sample.history_from_ts,
        "until_ts": sample.anchor_ts,
    }
    values.update(overrides)
    return Scope(**values)


def rolling_anchors(index, count=3, *, step_days=1):
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 30:
        raise ValueError("anchor count must be 1–30")
    if isinstance(step_days, bool) or not isinstance(step_days, int) or step_days < 1:
        raise ValueError("anchor step must be positive")
    last = index["observed_until_ts"]
    if last is None:
        raise ValueError("No recorded timestamp for rolling anchors")
    latest = last - FUTURE_MS
    return sorted(
        {
            latest - i * step_days * DAY_MS
            for i in range(count)
            if index["observed_from_ts"] <= latest - i * step_days * DAY_MS
        }
    )
