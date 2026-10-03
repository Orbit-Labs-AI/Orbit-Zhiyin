"""Shared per-session metrics, so A1 / A3 / A5 report the same number under the same name.

``active_ms`` - "活跃时长": sum of gaps between consecutive event timestamps of a session tree,
each gap capped at ``IDLE_CAP_MS``. A gap longer than the cap is treated as the user being
away, counting only the cap. Five minutes follows the inactivity threshold common in
web/session analytics (e.g. 5-30 min session timeouts; Catledge & Pitkow 1995 used 25.5 min for
browsing, IDE telemetry studies use ~5 min) and keeps a long agent tool run (no events while it
works) from being cut short. It is an estimate: wall-clock span (``span``) is reported
separately and is never called active time.
"""

from __future__ import annotations

from collections.abc import Iterable

IDLE_CAP_MS = 5 * 60_000


def active_ms(stamps: Iterable[int | None]) -> int | None:
    """Capped-gap active time of one session tree; ``None`` without any timestamp."""
    values = sorted(t for t in stamps if t is not None)
    if not values:
        return None
    return sum(min(b - a, IDLE_CAP_MS) for a, b in zip(values, values[1:], strict=False))


# Tool-call result classes, one definition for A1 tiles (``facts``), A3 lists/details
# (``sessions`` / ``trajectory``), A4 (``a4a6_tools``) and A5/A6 (``a4a6_sentiment``). The data
# layer writes completed / failed / interrupted / unknown; the other spellings are older or
# connector-native values. ``stopped`` (interrupted, refused) is a known result that is not a
# failure: it counts in an error rate's denominator, never in its numerator.
TOOL_OK = frozenset(("success", "completed", "ok"))
TOOL_FAILED = frozenset(("failed", "error", "failure"))
TOOL_STOPPED = frozenset(("interrupted", "rejected", "cancelled", "aborted", "denied"))


def tool_state(status: str | None) -> str:
    """``ok`` / ``failed`` / ``stopped`` / ``unknown`` (running, pending, unknown, missing)."""
    value = (status or "").lower()
    if value in TOOL_OK:
        return "ok"
    if value in TOOL_FAILED:
        return "failed"
    if value in TOOL_STOPPED:
        return "stopped"
    return "unknown"
