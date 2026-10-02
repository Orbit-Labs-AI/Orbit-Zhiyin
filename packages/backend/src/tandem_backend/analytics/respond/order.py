"""Native call ordering shared by normalization, workflow and UI products.

Deterministic display order never supplies a missing native sequence value.
Adjacency analyses use ordered_calls and report excluded ambiguous observations.
"""

from collections import Counter, defaultdict
from typing import Any

Record = dict[str, Any]


def call_order_key(call):
    seq = call.get("seq")
    known = isinstance(seq, int) and not isinstance(seq, bool)
    return call["session_uid"], not known, seq if known else 0, call["call_uid"]


def ordered_calls(calls: list[Record]) -> tuple[list[list[Record]], int]:
    """Split tied orders; exclude sessions whose missing seq prevents adjacency claims."""
    sessions = defaultdict(list)
    for call in calls:
        sessions[call["session_uid"]].append(call)
    runs, unknown = [], 0
    for rows in sessions.values():
        if any(not isinstance(c.get("seq"), int) or isinstance(c.get("seq"), bool) for c in rows):
            unknown += len(rows)
            continue
        counts = Counter(c["seq"] for c in rows)
        run = []
        for call in sorted(rows, key=lambda c: (c["seq"], c["call_uid"])):
            if counts[call["seq"]] > 1:
                unknown += 1
                if run:
                    runs.append(run)
                run = []
            else:
                run.append(call)
        if run:
            runs.append(run)
    return runs, unknown
