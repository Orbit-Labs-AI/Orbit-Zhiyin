"""Read explicitly reported durations without inferring execution from log gaps."""

import math


def native_duration_ms(item):
    value = item.get("duration_ms")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    value = item.get("duration")
    if not isinstance(value, dict):
        return None
    seconds, nanos = value.get("secs"), value.get("nanos", 0)
    if (
        not all(
            isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
            for v in (seconds, nanos)
        )
        or nanos >= 1_000_000_000
    ):
        return None
    value = seconds * 1000 + nanos / 1_000_000
    return round(value) if math.isfinite(value) and value <= 2**63 - 1 else None
