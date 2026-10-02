"""Shared selection validation for data readers and application requests."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_scope(timezone, start, end):
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise ValueError("display_timezone 必须是 IANA 时区名") from error
    for value in (start, end):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError("from_ts/until_ts 必须是 UTC 毫秒整数")
    if start is not None and end is not None and start >= end:
        raise ValueError("时间范围必须满足 from_ts < until_ts")
