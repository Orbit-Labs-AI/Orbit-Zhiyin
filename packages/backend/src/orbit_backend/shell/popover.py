"""``GET /v1/shell/popover``: one synchronous read for the menu-bar popover and the widgets
(POP-02/05/06/08/11, WG-02/03/04).

Counts come straight from orbit.db grouped by local day (``tz_offset_min``), live cards
from the realtime snapshot, the attention list from the notifier, the top recommendation
from the newest cached run. Nothing here submits an analysis or a recommendation run; the
idle-state opening line is computed once per data revision and day on a background thread
and is ``null`` until then.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from ..uiview.metrics import IDLE_CAP_MS
from . import (
    DAY_MS,
    day_index,
    day_start,
    default_scope,
    enabled_source_ids,
    excluded,
    has_db,
    main_where,
    now_ms,
    reader,
)

AGENTS = ("claude_code", "codex")
ACTIVE = ("awaiting_approval", "failing", "running")
RECENT_DONE = 5
BASELINE_DAYS = 30
_cache: dict[tuple, dict] = {}
_opening: dict[tuple, dict | None] = {}
_opening_busy: set[tuple] = set()
_lock = threading.Lock()


def _date(index: int) -> str:
    return datetime.fromtimestamp(index * 86_400, UTC).date().isoformat()


def _weekday(index: int) -> int:
    """ISO weekday (Mon=1 … Sun=7) of local day ``index``."""
    return (index + 3) % 7 + 1  # 1970-01-01 was a Thursday.


def _empty_week(today: int) -> dict:
    days = [{"date": _date(i), "weekday": _weekday(i), "sessions": 0,
             "by_agent": {"claude_code": 0, "codex": 0, "other": 0}}
            for i in range(today - 6, today + 1)]
    return {"days": days, "avg_per_day": 0.0, "today": 0}


def _counts(gw, now: int, tz: int) -> tuple[dict, dict, list[dict]]:
    """(today, week, recent_done) from orbit.db; zeros when there is no database."""
    today = day_index(now, tz)
    week = _empty_week(today)
    totals = {"date": _date(today), "sessions": 0, "duration_s": 0,
              "duration_basis": "active_estimate"}
    if not has_db(gw):
        return totals, week, []
    where, args = main_where(gw)
    start_week, start_today = day_start(today - 6, tz), day_start(today, tz)
    offset = tz * 60_000
    with reader(gw)() as db:
        rows = db.execute(
            f"SELECT (s.started_at + ?) / {DAY_MS} AS d, src.agent, COUNT(*) FROM session s "
            f"LEFT JOIN source src USING(source_id) WHERE {where} AND s.started_at >= ? "
            f"AND s.started_at <= ? GROUP BY d, src.agent", [offset, *args, start_week, now])
        by_day = {d["date"]: d for d in week["days"]}
        for d, agent, n in rows:
            day = by_day.get(_date(int(d)))
            if day is None:
                continue
            day["sessions"] += n
            day["by_agent"][agent if agent in AGENTS else "other"] += n
        # Sessions started today and their active time: the overview / session list ``dur``
        # (``uiview.metrics.active_ms``: event gaps of the root tree capped at IDLE_CAP_MS),
        # not the wall-clock start→end span, which counted idle hours as work.
        count = db.execute(
            f"SELECT COUNT(*) FROM session s WHERE {where} AND s.started_at >= ? "
            f"AND s.started_at <= ?", [*args, start_today, now]).fetchone()[0]
        active = db.execute(
            f"SELECT COALESCE(SUM(MIN(COALESCE(gap, 0), ?)), 0) FROM ("
            f"SELECT e.ts - LAG(e.ts) OVER (PARTITION BY t.root_uid ORDER BY e.ts) AS gap "
            f"FROM event e JOIN session t ON t.session_uid = e.session_uid "
            f"WHERE e.ts IS NOT NULL AND e.ts <= ? AND t.root_uid IN ("
            f"SELECT s.session_uid FROM session s WHERE {where} AND s.started_at >= ? "
            f"AND s.started_at <= ?))",
            [IDLE_CAP_MS, now, *args, start_today, now]).fetchone()[0]
        done = db.execute(
            f"SELECT s.session_uid, s.title, src.agent, p.name, s.started_at, s.ended_at, "
            f"s.status FROM session s LEFT JOIN source src USING(source_id) "
            f"LEFT JOIN project p ON p.project_id = s.project_id WHERE {where} "
            f"AND s.ended_at >= ? AND s.ended_at <= ? AND s.status != 'active' "
            f"ORDER BY s.ended_at DESC LIMIT ?", [*args, start_today, now, RECENT_DONE]).fetchall()
    total = sum(d["sessions"] for d in week["days"])
    week["avg_per_day"] = round(total / 7, 1)
    week["today"] = week["days"][-1]["sessions"]
    totals.update(sessions=count, duration_s=int(active // 1000))
    recent = [{"session_uid": r[0], "title": r[1], "agent": r[2], "project": r[3],
               "started_at": r[4], "ended_at": r[5],
               "duration_s": None if r[4] is None else max(0, (r[5] - r[4]) // 1000),
               "status": r[6] if r[6] in ("completed", "failed") else "unknown"}
              for r in done]
    return totals, week, recent


def _metrics(gw, start: int, end: int) -> dict:
    from ..ai import queries

    scope = {"start_ms": start, "end_ms": end}
    if (sources := enabled_source_ids(gw)) is not None:
        scope["source_ids"] = sources  # the same session set as ``main_where`` (SET-07)
    rows = queries.run("metrics", {"scope": scope},
                       reads=reader(gw), appdb=gw.appdb, home=gw.home)["rows"]
    return {r["metric"]: r for r in rows}


def _completion(gw, start: int, end: int) -> float | None:
    where, args = main_where(gw)
    with reader(gw)() as db:
        total, ok = db.execute(
            f"SELECT COUNT(*), SUM(s.status = 'completed') FROM session s WHERE {where} "
            f"AND s.started_at >= ? AND s.started_at < ? AND s.status != 'active'",
            [*args, start, end]).fetchone()
    return round((ok or 0) / total, 3) if total else None


def _pct(cur, prev) -> float | None:
    if cur is None or not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _trends(gw, now: int, tz: int) -> tuple[dict | None, dict | None]:
    """(weekly, yesterday): last 7 local days vs the 7 before; yesterday vs a 30-day
    per-day baseline. Cached per data revision, local day and exclusion set."""
    if not has_db(gw):
        return None, None
    today = day_index(now, tz)
    rev = gw.revisions.snapshot()
    sources = enabled_source_ids(gw)
    key = ("trends", rev["data_rev"], today, tz, tuple(excluded(gw)),
           None if sources is None else tuple(sources), now // 600_000)
    with _lock:
        if key in _cache:
            return _cache[key]["weekly"], _cache[key]["yesterday"]
    start_week = day_start(today - 6, tz)
    m = _metrics(gw, start_week, now)
    week = {"sessions": m["sessions"]["value"], "prev_sessions": m["sessions"]["prev"],
            "delta_pct": _pct(m["sessions"]["value"], m["sessions"]["prev"]),
            "hours": m["hours"]["value"], "prev_hours": m["hours"]["prev"],
            "correction_rate": m["correction_rate"]["value"],
            "prev_correction_rate": m["correction_rate"]["prev"]}
    y0, y1 = day_start(today - 1, tz), day_start(today, tz)
    base0 = day_start(today - 1 - BASELINE_DAYS, tz)
    y = _metrics(gw, y0, y1)
    b = _metrics(gw, base0, y0)
    yesterday = None
    if y["sessions"]["value"] or b["sessions"]["value"]:
        yesterday = {
            "date": _date(today - 1), "sessions": y["sessions"]["value"],
            "hours": y["hours"]["value"], "correction_rate": y["correction_rate"]["value"],
            "completion_rate": _completion(gw, y0, y1),
            "baseline": {"days": BASELINE_DAYS,
                         "sessions_per_day": round(b["sessions"]["value"] / BASELINE_DAYS, 2),
                         "hours_per_day": round(b["hours"]["value"] / BASELINE_DAYS, 2),
                         "correction_rate": b["correction_rate"]["value"],
                         "completion_rate": _completion(gw, base0, y0)}}
    with _lock:
        _cache.clear()  # One entry is enough; the key changes at most every 10 minutes.
        _cache[key] = {"weekly": week, "yesterday": yesterday}
    return week, yesterday


def top_rec(gw, surface: str = "menubar") -> dict | None:
    """First visible card of the newest cached run for the all-time scope (read only)."""
    from dataclasses import asdict

    from ..recommend import store
    from ..services.routes_analytics import analytics_scope
    from ..services.snapshots import scope_hash

    h = scope_hash(asdict(analytics_scope()), {})
    now = now_ms()
    try:
        with gw.appdb.read() as conn:
            top = store.top_get(conn, surface, h)
            cards = store.by_keys(conn, top["run_id"], top["rec_keys"][:1]) if top else []
            if not cards:
                run = store.latest_run(conn, h)
                items = store.candidates(conn, run["run_id"], limit=10) if run else []
                states = store.states(conn, [c["rec_key"] for c in items])
                cards = [c for c in items if store.visible(states.get(c["rec_key"]), now)]
    except Exception:  # noqa: BLE001 - no recommend tables yet.
        return None
    if not cards:
        return None
    card = cards[0]
    return {"candidate_id": card.get("candidate_id"), "run_id": card.get("run_id"),
            "title": card.get("title"), "type": card.get("type") or card.get("kind"),
            "gain": card.get("gain"), "level": card.get("level")}


def _opening_key(gw, now: int, tz: int) -> tuple:
    return (gw.revisions.snapshot()["data_rev"], day_index(now, tz), str(gw.home))


def opening(gw, now: int, tz: int, *, wait: bool = False) -> dict | None:
    """Cached ``ai.ask.opening_suggestion``; a miss starts one background computation."""
    if not has_db(gw):
        return None
    key = _opening_key(gw, now, tz)
    with _lock:
        if key in _opening:
            return _opening[key]
        busy = key in _opening_busy
        _opening_busy.add(key)

    def compute():
        from ..ai import ask

        try:
            value = ask.opening_suggestion(reader(gw), gw.appdb, {"days": 7}, gw.home)
        except Exception:  # noqa: BLE001 - the popover simply shows no opening line.
            value = None
        with _lock:
            _opening.clear()
            _opening[key] = value
            _opening_busy.discard(key)

    if busy:
        return None
    if wait:
        compute()
        return _opening.get(key)
    threading.Thread(target=compute, name="shell-opening", daemon=True).start()
    return None


def _realtime(gw):
    rt = getattr(gw, "realtime", None)
    if rt is None:
        from ..realtime.service import Realtime

        rt = gw.realtime = Realtime(gw)
    return rt


def build(gw, *, tz_offset_min: int, now: int | None = None, wait_opening: bool = False) -> dict:
    now = now if now is not None else now_ms()
    collection = gw.platform.collection.status()
    try:
        snap = _realtime(gw).snapshot()
    except Exception:  # noqa: BLE001 - live cards are optional.
        snap = {"status": "paused" if collection.get("paused") else "idle", "sessions": [],
                "counts": {}}
    # Recomputed here: the realtime snapshot may be up to one tick old across a resume.
    live = snap.get("sessions") or []
    status = "paused" if collection.get("paused") else "active" if any(
        s.get("state") in ACTIVE for s in live) else "idle"
    today, week, recent = _counts(gw, now, tz_offset_min)
    counts = snap.get("counts") or {}
    today["running"] = sum(counts.get(k, 0) for k in ("running", "awaiting_approval",
                                                         "failing"))
    today["finished"] = (snap.get("today") or {}).get("sessions_finished", 0)
    attention = [{k: item.get(k) for k in ("id", "type", "severity", "session_uid", "title",
                                            "body", "count", "since", "payload")}
                 for item in gw.platform.notifier.attention()]
    weekly, yesterday = _trends(gw, now, tz_offset_min) if has_db(gw) else (None, None)
    persona = None
    if has_db(gw):
        from .reveal import persona_summary

        summary = persona_summary(gw, default_scope(gw))
        persona = {k: summary[k] for k in ("ok", "code", "name_zh", "reason")}
    return {
        "generated_at": now, "status": status,
        "paused": {"since": collection.get("since"), "reason": collection.get("reason")}
        if collection.get("paused") else None,
        "today": today, "attention": attention,
        "live": live, "recent_done": recent, "week": week,
        "weekly": weekly or {"sessions": 0, "prev_sessions": None, "delta_pct": None,
                             "hours": 0.0, "prev_hours": None, "correction_rate": 0.0,
                             "prev_correction_rate": None},
        "yesterday": yesterday, "persona": persona, "top_rec": top_rec(gw),
        "opening": opening(gw, now, tz_offset_min, wait=wait_opening)
        if status != "active" else None,
    }
