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
