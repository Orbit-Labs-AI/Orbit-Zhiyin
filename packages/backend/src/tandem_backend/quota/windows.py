"""DT-17 quota windows per agent.

* Codex: ``ui.state`` events with ``attrs.state_kind = 'rate_limits'`` (connector keeps the
  native snapshot plus parsed ``windows``). Latest observation per ``window_minutes`` wins;
  a window whose reset time has passed is reported as reset (0 % used).
* Claude Code: no native limit in the logs, so the 5h / weekly windows are *estimated*
  from ``model_call`` tokens (active = input + cache_write + output) relative to the
  user's own historical peak for that window length. Too little history -> insufficient.

Every window carries ``basis`` (observed / observed_reset / estimated_peak / insufficient).
"""

from __future__ import annotations

import json

from .usage import calls

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
FIVE_HOUR, WEEK = 300, 10_080
KIND = {FIVE_HOUR: "five_hour", WEEK: "weekly"}
HISTORY_POINTS = 96
CLAUDE_LOOKBACK_DAYS = 28

LIMITS_SQL = """
SELECT e.session_uid, e.ts, e.attrs, src.agent FROM event e
JOIN session s USING(session_uid) LEFT JOIN source src ON src.source_id = s.source_id
WHERE e.kind = 'ui.state' AND json_extract(e.attrs, '$.state_kind') = 'rate_limits'
  AND e.ts IS NOT NULL AND e.ts >= ? AND e.ts <= ?
ORDER BY e.ts, e.seq
"""


def _num(value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def parse_windows(attrs: dict, ts_ms: int) -> list[dict]:
    """Windows of one snapshot: ``attrs.windows`` if present, else primary/secondary."""
    raw = attrs.get("windows")
    if not isinstance(raw, list):
        snap = attrs.get("snapshot") or {}
        raw = [snap.get(k) for k in ("primary", "secondary")] if isinstance(snap, dict) else []
    out = []
    for w in raw:
        if not isinstance(w, dict) or _num(w.get("window_minutes")) is None:
            continue
        minutes = int(w["window_minutes"])
        resets_at = _num(w.get("resets_at"))
        resets_in = _num(w.get("resets_in_seconds"))
        reset_ms = int(resets_at * 1000) if resets_at is not None else (
            ts_ms + int(resets_in * 1000) if resets_in is not None else None)
        out.append({"window_minutes": minutes, "window_kind": KIND.get(minutes, "other"),
                    "used_percent": _num(w.get("used_percent")), "resets_at": reset_ms})
    return out


def codex_windows(db, now_ms: int, excluded=()) -> list[dict]:
    skip = set(excluded)
    latest: dict[tuple[str, int], dict] = {}
    history: dict[tuple[str, int], list] = {}
    for row in db.execute(LIMITS_SQL, (now_ms - 8 * DAY_MS, now_ms)):
        if row["session_uid"] in skip:
            continue
        try:
            attrs = json.loads(row["attrs"])
        except ValueError:
            continue
        for w in parse_windows(attrs, row["ts"]):
            key = (row["agent"] or "codex", w["window_minutes"])
            latest[key] = {**w, "observed_at": row["ts"]}
            if w["used_percent"] is not None:
                history.setdefault(key, []).append([row["ts"], w["used_percent"]])
    out = []
    for (agent, minutes), w in sorted(latest.items()):
        span = minutes * 60_000
        used, reset = w["used_percent"], w["resets_at"]
        if used is None:
            status = "insufficient"
        elif reset is not None and reset <= now_ms:
            status, used = "observed_reset", 0.0
        elif reset is None and now_ms - w["observed_at"] > span:
            status, used = "insufficient", None  # Stale and no reset time: cannot tell.
        else:
            status = "observed"
        pace = None
        if status == "observed" and reset is not None:
            elapsed = 1 - (reset - now_ms) / span
            pace = round((used / 100) / elapsed, 3) if elapsed > 0.05 else None
        out.append({
            "agent": agent, "window_kind": w["window_kind"], "window_minutes": minutes,
            "used_percent": used, "headroom": None if used is None else round(1 - used / 100, 4),
            "resets_at": reset, "observed_at": w["observed_at"], "basis": status,
            "pace": pace, "history": history.get((agent, minutes), [])[-HISTORY_POINTS:],
        })
    return out


def _active(row: dict) -> int:
    return sum(row[k] or 0 for k in ("input_tokens", "cache_write_tokens", "output_tokens"))


def _peak(bins: dict[int, int], width: int, last_start: int, first: int) -> int:
    """Largest sum of ``width`` consecutive bins whose window ends before ``last_start``."""
    best = 0
    for start in range(first, last_start - width + 1):
        best = max(best, sum(bins.get(start + i, 0) for i in range(width)))
    return best


def claude_windows(db, now_ms: int, agent: str = "claude_code", excluded=()) -> list[dict]:
    rows = [r for r in calls(db, now_ms - CLAUDE_LOOKBACK_DAYS * DAY_MS, now_ms + 1, excluded)
            if r["agent"] == agent]
    out = []
    for minutes, bin_ms, width, min_history_ms in (
            (FIVE_HOUR, HOUR_MS, 5, 3 * DAY_MS), (WEEK, DAY_MS, 7, 14 * DAY_MS)):
        span = minutes * 60_000
        current = [r for r in rows if r["ts"] > now_ms - span]
        tokens = sum(_active(r) for r in current)
        window = {"agent": agent, "window_kind": KIND[minutes], "window_minutes": minutes,
                  "active_tokens": tokens, "requests": len(current), "peak_tokens": None,
                  "used_percent": None, "headroom": None, "resets_at": None,
                  "observed_at": max((r["ts"] for r in current), default=None),
                  "basis": "insufficient", "pace": None, "history": []}
        if rows and now_ms - min(r["ts"] for r in rows) >= min_history_ms:
            bins: dict[int, int] = {}
            for r in rows:
                index = r["ts"] // bin_ms
                bins[index] = bins.get(index, 0) + _active(r)
            first, now_bin = min(bins), now_ms // bin_ms
            peak = _peak(bins, width, now_bin - width + 1, first)
            window["history"] = [[i * bin_ms, bins.get(i, 0)]
                                 for i in range(max(first, now_bin - 4 * width), now_bin + 1)]
            if peak > 0:
                ratio = tokens / peak
                window.update(peak_tokens=peak, used_percent=round(100 * ratio, 2),
                              headroom=round(max(0.0, 1 - ratio), 4), basis="estimated_peak")
        out.append(window)
    return out


def snapshot(db, now_ms: int, excluded=()) -> dict:
    agents = [r[0] for r in db.execute("SELECT DISTINCT agent FROM source ORDER BY agent")]
    windows = codex_windows(db, now_ms, excluded)
    for agent in agents:
        if agent == "claude_code":
            windows += claude_windows(db, now_ms, agent, excluded)
    summary = []
    for agent in agents:
        own = [w for w in windows if w["agent"] == agent and w["headroom"] is not None]
        binding = min(own, key=lambda w: w["headroom"], default=None)
        summary.append({
            "agent": agent,
            "status": "ok" if binding else "insufficient",
            "headroom": binding["headroom"] if binding else None,
            "binding_window": binding["window_kind"] if binding else None,
            "resets_at": binding["resets_at"] if binding else None,
            "basis": binding["basis"] if binding else "insufficient",
        })
    return {"now": now_ms, "agents": summary, "quota_window": windows}
