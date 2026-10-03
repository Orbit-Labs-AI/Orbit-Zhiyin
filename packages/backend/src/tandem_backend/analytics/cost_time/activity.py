"""Timestamp coverage and activity distributions in an explicit display timezone."""

from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from ..common import human, timestamp
from .tokens import prepare_requests


@lru_cache(maxsize=1 << 18)
def local_parts(ts, zone_name):
    """(day, hour, weekday) of one timestamp; the same timestamps recur in every scope."""
    try:
        dt = datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone(ZoneInfo(zone_name))
    except (ValueError, OverflowError, OSError):
        return None
    return dt.date().isoformat(), str(dt.hour), dt.isoweekday()


def activity(sessions, events, calls, model_calls, main_ids, scope):
    zone_name = scope.display_timezone
    ZoneInfo(zone_name)  # an unknown zone still fails here, before any timestamp
    def buckets(records):
        day, hour, weekday, weekday_hour, unknown = Counter(), Counter(), Counter(), Counter(), 0
        for ts in records:
            if not timestamp(ts):
                unknown += 1
                continue
            if not scope.contains(ts):
                continue
            parts = local_parts(ts, zone_name)
            if parts is None:
                unknown += 1
                continue
            d, h, w = parts
            day[d] += 1
            hour[h] += 1
            weekday[str(w)] += 1
            weekday_hour[f"{w}:{h}"] += 1
        return {"by_day": dict(sorted(day.items())), "by_hour": dict(sorted(hour.items(), key=lambda x: int(x[0]))),
                "weekday_distribution": dict(sorted(weekday.items())),
                "by_weekday_hour": dict(sorted(weekday_hour.items())), "active_days": len(day),
                "effective_n": sum(day.values()), "time_unknown_n": unknown}
    human_rows = [e for e in events if human(e, main_ids)]
    starts = []
    for s in sessions:
        if s["session_uid"] in main_ids:
            starts.append(s.get("started_at"))
    hs = buckets([e.get("ts") for e in human_rows])
    agents = {s["session_uid"]: s.get("agent") for s in sessions}
    selected_starts = {}
    for e in events:
        sid, ts = e["session_uid"], e.get("ts")
        if sid in main_ids and timestamp(ts) and scope.contains(ts):
            selected_starts[sid] = min(selected_starts.get(sid, ts), ts)
    agent_series = []
    for agent in sorted(set(agents.values()), key=lambda value: (value is None, str(value))):
        ids = {sid for sid, value in agents.items() if value == agent}
        agent_series.append({"agent": agent,
            "main_session_count": len(main_ids & ids),
            "sessions": buckets([selected_starts.get(sid) for sid in main_ids & ids]),
            "human_messages": buckets([e.get("ts") for e in human_rows if e["session_uid"] in ids]),
            "basis": "selected observed first event per main session; direct human message timestamps"})
    return {"time_basis": "reported log timestamps; not continuous work", "sessions": buckets(starts),
            "agent_series": agent_series,
            "human_messages": hs, "tool_calls": None if calls is None else buckets([c.get("started_at") for c in calls]),
            "model_requests": None if model_calls is None else buckets([c.get("ts") for c in prepare_requests(model_calls)["requests"]]),
            "active_days": hs["active_days"], "hour_distribution": hs["by_hour"],
            "weekday_distribution": hs["weekday_distribution"]}
