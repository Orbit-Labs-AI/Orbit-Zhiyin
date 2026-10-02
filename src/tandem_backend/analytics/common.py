"""Small shared measurement primitives; no feature-family policy."""

import math


def ratio(a, b):
    return a / b if a is not None and b else None


def quantile(values, q):
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def human(e, main_ids):
    return (e["kind"] == "message.user" and e["session_uid"] in main_ids
            and e.get("attrs", {}).get("origin") == "human"
            and e.get("actor") in ("human", "user"))


def nonnegative_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def timestamp(value):
    """The input contract uses integer UTC milliseconds, never bool or NaN."""
    return isinstance(value, int) and not isinstance(value, bool)


def task_uid(event):
    attrs = event.get("attrs", {})
    return event.get("task_uid") or attrs.get("task_uid") or attrs.get("task_id")


def annotation_visible(annotation, until_ts=None):
    """Later annotations cannot rewrite an earlier snapshot; unclocked ones abstain."""
    return until_ts is None or (timestamp(annotation.get("available_at"))
                                and annotation["available_at"] < until_ts)
