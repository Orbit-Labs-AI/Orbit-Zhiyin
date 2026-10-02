"""Timestamp coverage and activity distributions in an explicit display timezone."""

from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..common import human, timestamp
from .tokens import prepare_requests


def activity(sessions, events, calls, model_calls, main_ids, scope):
    zone = ZoneInfo(scope.display_timezone)
    def buckets(records):
        day, hour, weekday, unknown = Counter(), Counter(), Counter(), 0
        for ts in records:
            if not timestamp(ts):
                unknown += 1
                continue
            if not scope.contains(ts):
                continue
            try:
                dt = datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone(zone)
            except (ValueError, OverflowError, OSError):
                unknown += 1
                continue
            day[dt.date().isoformat()] += 1
            hour[str(dt.hour)] += 1
            weekday[str(dt.isoweekday())] += 1
        return {"by_day": dict(sorted(day.items())), "by_hour": dict(sorted(hour.items(), key=lambda x: int(x[0]))),
                "weekday_distribution": dict(sorted(weekday.items())), "active_days": len(day),
                "effective_n": sum(day.values()), "time_unknown_n": unknown}
    human_rows = [e for e in events if human(e, main_ids)]
    starts = []
    for s in sessions:
        if s["session_uid"] in main_ids:
            starts.append(s.get("started_at"))
    hs = buckets([e.get("ts") for e in human_rows])
    return {"time_basis": "reported log timestamps; not continuous work", "sessions": buckets(starts),
            "human_messages": hs, "tool_calls": None if calls is None else buckets([c.get("started_at") for c in calls]),
            "model_requests": None if model_calls is None else buckets([c.get("ts") for c in prepare_requests(model_calls)["requests"]]),
            "active_days": hs["active_days"], "hour_distribution": hs["by_hour"],
            "weekday_distribution": hs["weekday_distribution"]}
