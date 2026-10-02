"""Small display rules with explicit units, denominators and missing values."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import log1p
from time import time_ns
from zoneinfo import ZoneInfo

WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def window_scope(scope, window=None, *, now_ts=None):
    """Rolling N*24h windows, with [from, until) membership and local calendar bins."""
    if window is None:
        return scope
    if window == "all":
        if scope.from_ts is not None or scope.until_ts is not None:
            raise ValueError("window=all 不能与 from_ts/until_ts 同时使用")
        return scope
    if window not in WINDOW_DAYS:
        raise ValueError("window 必须是 7d/30d/90d/all")
    if scope.from_ts is not None:
        raise ValueError("window 不能与 from_ts 同时使用；可用 until_ts 指定历史截止时刻")
    until = scope.until_ts if scope.until_ts is not None else now_ts
    if until is None:
        until = time_ns() // 1_000_000
    return replace(scope, from_ts=until - WINDOW_DAYS[window] * 86_400_000, until_ts=until)


def measure(value, unit, basis, *, status="available", unknown_n=0, reason=None,
            evidence_refs=None):
    if value is None:
        status = "unavailable"
    elif status == "available" and unknown_n:
        status = "partial"
    return {"value": value, "unit": unit, "status": status, "basis": basis,
            "unknown_n": unknown_n, "reason": reason,
            "evidence_refs": evidence_refs or []}


def unavailable(reason, unit=None):
    return measure(None, unit, "not_measured", unknown_n=None, reason=reason)


def ranked_counts(counts, *, basis, unknown_n=0, status="available"):
    """Shares of observed occurrences; distinct from multi-label task incidence."""
    if counts is None:
        return {"status": "unavailable", "rows": None, "total": None,
                "unknown_n": unknown_n, "basis": basis}
    total = sum(counts.values())
    return {"status": "partial" if status == "available" and unknown_n else status,
            "total": total, "unknown_n": unknown_n, "basis": basis,
            "rows": [{"name": k, "count": v, "share": v / total if total else None}
                     for k, v in sorted(counts.items(), key=lambda p: (-p[1], p[0]))]}


def activity_view(rhythm, scope, event_status="available"):
    """Separate activity units; log-scaled heatmap intensity is local to this selection."""
    if rhythm is None:
        return {"status": "unavailable", "series": None, "reason": "events_unavailable"}
    zone = ZoneInfo(scope.get("display_timezone", "UTC"))
    dates = None
    start, end = scope.get("from_ts"), scope.get("until_ts")
    if start is not None and end is not None:
        try:
            first = datetime.fromtimestamp(start / 1000, timezone.utc).astimezone(zone).date()
            last = datetime.fromtimestamp((end - 1) / 1000, timezone.utc).astimezone(zone).date()
            # Do not allocate an arbitrary number of days for an untrusted API range.
            span = (last - first).days + 1
            if 0 < span <= 366:
                dates = [(first + timedelta(days=i)).isoformat() for i in range(span)]
        except (ValueError, OverflowError, OSError):
            pass
    result = {}
    for name in ("human_messages", "tool_calls", "model_requests"):
        source = rhythm.get(name)
        if source is None:
            result[name] = {"status": "unavailable", "by_day": None, "by_hour": None}
            continue
        days = source["by_day"]
        maximum = max(days.values(), default=0)
        total = sum(days.values())
        unknown = source.get("time_unknown_n", 0)
        result[name] = {
            "status": "partial" if unknown or event_status != "available" else "available",
            "known_n": total, "time_unknown_n": unknown,
            "by_day": [{"date": day, "count": days.get(day, 0),
                        "share": days.get(day, 0) / total if total else None,
                        "intensity": log1p(days.get(day, 0)) / log1p(maximum) if maximum else 0.0}
                       for day in dates or sorted(days)],
            "by_hour": [{"hour": hour, "count": source["by_hour"].get(str(hour), 0),
                         "share": source["by_hour"].get(str(hour), 0) / total if total else None}
                        for hour in range(24)],
        }
    return {"status": event_status, "series": result,
            "display_timezone": scope.get("display_timezone", "UTC"),
            "calendar": "dense_selected_days" if dates else "observed_days_only",
            "intensity_formula": "log1p(day_count)/log1p(max_day_count_in_selection)",
            "meaning": "各类日志活动量分别统计；热度只在当前筛选内比较，不是工作时长或效率。"}
