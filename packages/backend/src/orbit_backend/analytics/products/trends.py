"""Calendar activity and resource breakdowns with explicit missing denominators."""

from collections import Counter, defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from ..common import human
from ..context import AnalysisContext
from ..cost_time.tokens import prepare_requests, token_total
from .contracts import metric
from .feedback import calendar_key

Record = dict[str, Any]


def resource_groups(context: AnalysisContext) -> Record:
    """Group request-level use by observed model and effort; do not rank capability."""
    if context.model_calls is None:
        return {"status": "unavailable", "rows": None}
    prepared = prepare_requests(context.model_calls)
    groups = defaultdict(list)
    for call in prepared["requests"]:
        groups[(call.get("model_id") or "unknown", call.get("effort_raw") or "unknown")].append(
            call
        )
    rows = []
    for (model, effort), calls in sorted(groups.items()):
        values = [token_total(c) for c in calls if c.get("coverage") == "self"]
        known = [v for v in values if v is not None]
        rows.append(
            {
                "model_id": model,
                "effort_raw": effort,
                "request_count": len(calls),
                "known_tokens": metric(
                    sum(known) if known else None, "token", len(known), len(calls) - len(known)
                ),
                "session_uids": sorted({c["session_uid"] for c in calls}),
            }
        )
    status = context.bundle.coverage.get("model_calls", {}).get("status", "partial")
    return {
        "status": status,
        "rows": rows,
        "invalid_request_rows": prepared["invalid_request_rows"],
        "conflicting_request_ids": prepared["conflicting_request_ids"],
        "meaning": "descriptive request groups, not a model ranking",
    }


def activity_series(context: AnalysisContext, bucket: str = "day") -> Record:
    """Build day/week/month buckets and a joint weekday-hour grid from real message times."""
    if bucket not in ("day", "week", "month"):
        raise ValueError("bucket must be day, week or month")
    if context.bundle.events is None:
        return {"status": context.event_status, "rows": None, "heatmap": None, "bucket": bucket}
    from datetime import datetime, timezone

    zone = ZoneInfo(context.scope.display_timezone)
    groups, heatmap = defaultdict(lambda: Counter()), Counter()
    members, unknown = defaultdict(set), Counter()
    calls = context.families(set(context.session_map))["respond"]["tool_sequence"]
    call_events = {c.get("call_event_uid") for c in calls or []}
    for event in context.events:
        category = (
            "human_messages"
            if human(event, context.main_ids)
            else "tool_calls"
            if event["event_uid"] in call_events
            else None
        )
        if category is None:
            continue
        key = calendar_key(event.get("ts"), zone, bucket)
        if key is None:
            unknown[category] += 1
            continue
        groups[key][category] += 1
        members[key].add(event["session_uid"])
        if category == "human_messages":
            dt = datetime.fromtimestamp(event["ts"] / 1000, timezone.utc).astimezone(zone)
            heatmap[(dt.isoweekday(), dt.hour)] += 1
    return {
        "status": context.event_status,
        "bucket": bucket,
        "display_timezone": context.scope.display_timezone,
        "time_basis": "message and tool-call event observation time, not continuous work",
        "rows": [
            {
                "period": period,
                "human_messages": counts["human_messages"],
                "tool_calls": counts["tool_calls"] if calls is not None else None,
                "session_uids": sorted(members[period]),
            }
            for period, counts in sorted(groups.items())
        ],
        "heatmap": [
            {"weekday": day, "hour": hour, "human_messages": count}
            for (day, hour), count in sorted(heatmap.items())
        ],
        "time_unknown_counts": dict(unknown),
    }


def comparison(current: Record, previous: Record) -> Record:
    """Compare the same metrics; a zero baseline has no percentage change."""
    pairs = [
        (
            "main_sessions",
            current["overview"]["counts"]["main_sessions"],
            previous["overview"]["counts"]["main_sessions"],
        ),
        (
            "human_messages",
            current["overview"]["counts"]["human_messages"],
            previous["overview"]["counts"]["human_messages"],
        ),
        ("tool_calls", current["tools"]["call_count"], previous["tools"]["call_count"]),
        (
            "total_tokens",
            current["overview"]["usage"]["total_tokens"],
            previous["overview"]["usage"]["total_tokens"],
        ),
    ]
    return {
        "current_scope": current["scope"],
        "previous_scope": previous["scope"],
        "rows": [
            {
                "metric": key,
                "current": value,
                "previous": old,
                "difference": value - old if value is not None and old is not None else None,
                "relative_change": (value - old) / old if value is not None and old else None,
            }
            for key, value, old in pairs
        ],
        "meaning": "descriptive differences; changes in task mix and data coverage may explain them",
    }
