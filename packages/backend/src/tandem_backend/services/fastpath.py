"""First-open fast path: serve a small time window first, warm wider ones in the background.

On a real home (≈1.9k sessions / 770k events) an all-time analysis takes minutes, while the
last 7 days take seconds. Screens that accept ``days``:

- ``days`` omitted ("auto"): the widest window (all time → 30 → 7 days) whose snapshot is
  fresh for the current data revision; otherwise the widest older (stale) snapshot;
  otherwise the 7-day window (or the smallest one holding any event) is computed now
  (interactive) and the wider windows are queued at prewarm priority.
- ``days`` = 7 / 30 / 90 / 0 (0 = all time): exactly that window.

Windows start at a UTC day boundary (``days - 1`` days before today), so one day maps to one
scope hash and the gateway's prewarm produces the same keys. ``meta.window`` reports the
served window and, for each wider one, its state (``ready`` / ``stale`` / ``computing`` /
``queued`` / ``failed`` / ``absent``) and ``scope_hash`` (as in its ``analysis.ready`` SSE
event), so a client can switch once it is ready.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .sections import rules_digest
from .snapshots import SnapshotKey, scope_hash

FAST_DAYS = 7
FULL_PASS = "uiview_facts"  # one complete analysis per window (see uiview.section)
LADDER = (7, 30, 0)  # computation order: small first
ALLOWED_DAYS = (7, 30, 90, 0)


def window_start(days: int, now: datetime | None = None) -> int | None:
    """Epoch ms of the window's first UTC day; ``None`` for all time (0)."""
    if not days:
        return None
    now = now or datetime.now(UTC)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def windowed(scope: dict, days: int, now: datetime | None = None) -> dict:
    """``scope`` restricted to the last ``days`` days (open-ended, like the default scope)."""
    return {**scope, "from_ts": window_start(days, now), "until_ts": None}


def check_days(days: int | None) -> None:
    from .auth import ApiError

    if days is not None and days not in ALLOWED_DAYS:
        raise ApiError(422, "invalid_request", f"days must be one of {ALLOWED_DAYS}")


def state(gw, section: str, scope: dict, params: dict | None = None) -> str:
    """``ready`` / ``stale`` / ``computing`` / ``queued`` / ``failed`` / ``absent``."""
    rev = gw.revisions.snapshot()
    if rev["data_rev"] is None:
        return "absent"
    rules, h = rules_digest(), scope_hash(scope, params or {})
    revision = (rev["data_rev"], rev["inventory_rev"])
    if gw.snapshots.get(SnapshotKey(section, h, *revision, rules)) is not None:
        return "ready"
    analysis = gw.supervisor.analysis
    task = analysis.tasks.get((section, h, *revision, rules)) if hasattr(analysis, "tasks") \
        else None
    if task is not None:
        return "computing" if task.status == "running" else "queued"
    failure = analysis.failure(section, h, revision) if hasattr(analysis, "failure") else None
    if failure is not None:
        return "failed"
    if gw.snapshots.latest(section, h, rules) is not None:
        return "stale"
    return "absent"


def warm(gw, section: str, base: dict, params: dict | None = None,
         windows: tuple[int, ...] = LADDER) -> list[str]:
    """Queue ``section`` for each window lacking a fresh snapshot, at prewarm priority."""
    rev = gw.revisions.snapshot()
    if rev["data_rev"] is None:
        return []
    rules, queued = rules_digest(), []
    revision = (rev["data_rev"], rev["inventory_rev"])
    for days in windows:
        scope = windowed(base, days)
        h = scope_hash(scope, params or {})
        if gw.snapshots.get(SnapshotKey(section, h, *revision, rules)) is not None:
            continue
        task = gw.supervisor.analysis.submit(section, scope, params or {}, h, "prewarm",
                                             revision, rules)
        if task is not None:
            queued.append(task.id)
    return queued


def choose(gw, section: str, base: dict, days: int | None,
           params: dict | None = None) -> tuple[dict, dict]:
    """(scope to serve, ``meta.window``). ``days=None`` picks automatically (see module doc);
    an explicit ``days`` serves exactly that window. Call ``follow_up`` after submitting the
    served scope so wider windows queue behind it instead of preempting it."""
    if days is not None:
        return windowed(base, days), {"days": days, "requested": days, "wider": []}
    states = {d: state(gw, section, windowed(base, d), params) for d in LADDER}
    chosen = next((d for d in (0, 30, 7) if states[d] == "ready"), None)
    if chosen is None:
        chosen = next((d for d in (0, 30, 7) if states[d] == "stale"), None)
    if chosen is None:
        # The smallest window that holds any event: after a quiet week, 7 days is empty.
        chosen = next((d for d in LADDER if d and has_events(gw, d) is not False), 0)
    # scope_hash matches the ``analysis.ready`` SSE event of that window's computation.
    wider = [{"days": d, "state": states[d],
              "scope_hash": scope_hash(windowed(base, d), params or {})}
             for d in LADDER if _wider(d, chosen)]
    return windowed(base, chosen), {"days": chosen, "requested": "auto", "wider": wider}


def has_events(gw, days: int) -> bool | None:
    """Whether any event falls in the window (all sources; one indexed probe per kind on
    ``event_by_kind_time``); ``None`` when the gateway cannot tell."""
    import json

    reads = getattr(gw, "reads", None)
    if reads is None:
        return None
    try:
        with reads.read(check=False) as db:
            kinds = [row[0] for row in db.execute("SELECT DISTINCT kind FROM event")]
            return db.execute(
                "SELECT 1 FROM event WHERE kind IN (SELECT value FROM json_each(?)) AND ts >= ?"
                " LIMIT 1", (json.dumps(kinds), window_start(days))).fetchone() is not None
    except Exception:  # noqa: BLE001  advisory: the caller falls back to the 7-day window
        return None


def follow_up(gw, section: str, base: dict, window: dict, params: dict | None = None) -> dict:
    """Queue the wider windows of an automatic choice that are not ready or on their way."""
    todo = tuple(w["days"] for w in window["wider"]
                 if w["state"] not in ("ready", "computing", "queued"))
    if todo:
        if section != FULL_PASS and not params:
            # The full pass of a window caches every analysis section of it (with and
            # without text), so the section's own task after it is a cache read.
            warm(gw, FULL_PASS, base, None, todo)
        warm(gw, section, base, params, todo)
        for w in window["wider"]:
            if w["days"] in todo:
                w["state"] = state(gw, section, windowed(base, w["days"]), params)
    return window


def _wider(days: int, than: int) -> bool:
    """All time (0) is the widest window."""
    if days == than:
        return False
    if than == 0:
        return False
    return days == 0 or days > than
