"""A1 overview / Lite home payload, assembled from fact rows with the ``derive`` port.

Mirrors ``40-a1-overview.js``: tiles (n / h / m / a / f with previous-window deltas and
7-day or 12-week trends), outcome mix (estimate), per-agent trend buckets, week × hour heat,
tool top 6, persona mini card and the L0 insight. Filters follow ``pass()``: topic /
outcome / friction / hour narrow the page but not the persona or the tile trends.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from . import CONTRACT, VERSION, derive, insight, persona

TILE_LABELS = (("n", "会话", None), ("h", "协作时长", "h"), ("m", "你发出的消息", None),
               ("a", "自主比", "×"), ("f", "摩擦率", "%"))
TILE_BASIS = {"n": "analysis", "h": "active_estimate", "m": "analysis",
              "a": "l1_turn_steps/analysis", "f": "lexical_candidate"}
MIN_PREV = 5
STRIP_DAYS = 30


def today_in(tz_name: str | None, now_ms: int | None = None) -> date:
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:  # noqa: BLE001
        tz = UTC
    now = datetime.fromtimestamp(now_ms / 1000, tz) if now_ms else datetime.now(tz)
    return now.date()


def _day_index(ts: int, tz_name: str, today: date) -> int:
    return (today_in(tz_name, ts) - today).days


def _round(value, digits):
    return None if value is None else round(value, digits)


def _tile_value(key: str, st: dict):
    # ``auto`` is None when no session in the window has a known step count: shown as unknown.
    return {"n": st["n"], "h": round(st["hours"], 1), "m": st["msgs"], "a": _round(st["auto"], 1),
            "f": round(st["fric"], 1)}[key]


def _delta(key: str, st: dict, prev: dict | None):
    if prev is None:
        return None
    cur_v, prev_v = {"n": (st["n"], prev["n"]), "h": (st["hours"], prev["hours"]),
                     "m": (st["msgs"], prev["msgs"]), "a": (st["auto"], prev["auto"]),
                     "f": (st["fric"], prev["fric"])}[key]
    if cur_v is None or prev_v is None:
        return None
    out = {"cur": round(cur_v, 2), "prev": round(prev_v, 2),
           "unit": "pt" if key in ("a", "f") else "pct"}
    if key == "f":
        out["goodDown"] = True
    return out


def tiles(rows_all: list[dict], L: list[dict], prev: dict | None, f: dict, range_: int,
          end: int, compare: bool, brushed: bool) -> list[dict]:
    st = derive.stats(L, unknown=None)
    cmp = compare and not brushed and prev is not None and prev["n"] >= MIN_PREV
    sub = "刷选范围" if brushed else ("无可比上期" if compare and not cmp else "")
    fns = {"n": len, "h": lambda xs: round(derive.stats(xs)["hours"], 2),
           "m": lambda xs: derive.stats(xs)["msgs"],
           # Sparkline points stay numeric (empty bucket = 0) for the prototype's chart.
           "a": lambda xs: round(derive.stats(xs)["auto"], 2),
           "f": lambda xs: round(derive.stats(xs)["fric"], 2)}
    out = []
    for key, label, unit in TILE_LABELS:
        trend = (derive.daily(fns[key], rows_all, end, 7, f) if range_ == 7
                 else derive.weekly(fns[key], rows_all, end, 12, f))
        tile_sub = sub
        if key == "m" and not cmp and not sub:
            tile_sub = f"{st['per']:.1f} 条 / 会话"
        out.append({"k": key, "label": label, "value": _tile_value(key, st), "unit": unit,
                    "delta": _delta(key, st, prev) if cmp else None, "sub": tile_sub,
                    "trend": trend, "trend_label": "近 7 天" if range_ == 7 else "近 12 周",
                    "basis": TILE_BASIS[key]})
    return out


def trend(L: list[dict], window, metric: str, agents: list[dict], today: date) -> dict:
    ids = [a["id"] for a in agents]
    ser = derive.series(L, window, metric, ids, today)
    weekly = len(ser) != window[1] - window[0] + 1
    last = ser[-1] if ser else None
    partial = bool(weekly and last and last["b"] - last["a"] + 1 < 7)
    totals = [sum(v or 0 for v in b["v"]) for b in ser]
    full = totals[:-1] if partial else totals
    return {
        "bucket": "week" if weekly else "day", "metric": metric,
        "unit": {"n": "sessions", "h": "hours", "tok": "million_tokens"}[metric],
        "basis": {"n": "analysis", "h": "active_estimate", "tok": "l1_model_call"}[metric],
        "x": [{"lbl": b["lbl"], "a": derive.iso(today, b["a"]), "b": derive.iso(today, b["b"]),
               "weekend": (not weekly) and (today.toordinal() + b["a"]) % 7 in (6, 0)}
              for b in ser],
        "series": [{"agent": a["id"], "name": a["name"], "color": derive.agent_color(a["id"], i),
                    "values": [None if b["v"][i] is None else round(b["v"][i], 3) for b in ser]}
                   for i, a in enumerate(agents)],
        "avg": round(sum(full) / len(full), 3) if full else None, "partial_last": partial,
    }


def tools_top(L: list[dict], aux: dict, limit: int = 6) -> dict:
    rows = derive.tool_rows(L, aux)
    return {"top": [{"name": t["name"], "kind": t["kind"], "n": t["n"],
                     "err": None if t["err"] is None else round(t["err"], 4)}
                    for t in rows[:limit]],
            "kinds_total": len(rows), "calls_total": sum(t["n"] for t in rows),
            "err_basis": "known_status_only"}


def scope_note(f: dict) -> str:
    names = [label for key, label in (("topic", "主题"), ("outcome", "结果"), ("fric", "摩擦"),
                                       ("hour", "时段")) if f.get(key) not in (None, "")]
    return " / ".join(names) + "筛选不计入人格" if names else ""


def build(body: dict, params: dict, today: date) -> dict:
    meta = body.get("meta") or {}
    tz = meta.get("display_timezone") or "UTC"
    rows = derive.prepare(body.get("rows") or [], today)
    aux = body.get("aux") or {}
    agents = body.get("agents") or []
    projects = {p["id"]: p for p in body.get("projects") or []}
    first = derive.first_index(rows)
    range_ = params.get("range", 30)
    f = {k: params.get(k) for k in ("agents", "project", "topic", "outcome", "fric", "hour")}
    window = derive.win(range_, first)
    brushed = False
    if params.get("from_ts") is not None or params.get("until_ts") is not None:
        lo = (_day_index(params["from_ts"], tz, today) if params.get("from_ts") is not None
              else window[0])
        hi = (_day_index(params["until_ts"] - 1, tz, today)
              if params.get("until_ts") is not None else window[1])
        window, brushed = (lo, hi), True
    L = derive.sel(rows, window, f)
    st = derive.stats(L, unknown=None)
    pw = derive.prev_win(range_, first)
    prev = derive.stats(derive.sel(rows, pw, f), unknown=None) if pw and not brushed else None
    base_window = derive.win(range_, first)
    p = persona.persona(derive.sel(rows, base_window, f, no_extra=True), aux)
    visible_agents = [a for a in agents if f["agents"] is None or a["id"] in f["agents"]]
    payload = {
        "meta": {"contract": CONTRACT, "version": VERSION, "edition": params.get("edition"),
                 "today": today.isoformat(), "range": range_, "brushed": brushed,
                 "window": [derive.iso(today, window[0]), derive.iso(today, window[1])],
                 "prev_window": ([derive.iso(today, pw[0]), derive.iso(today, pw[1])]
                                 if pw and not brushed else None),
                 "filters": {k: v for k, v in f.items() if v not in (None, "")},
                 "persona_scope_note": scope_note(f), "display_timezone": tz},
        "header": {"window_label": (f"{derive.iso(today, window[0])} — "
                                    f"{derive.iso(today, window[1])[5:]}"),
                   "n": st["n"], "agents_n": len({r.get("a") for r in L if r.get("a")})},
        "tiles": tiles(rows, L, prev, f, range_, window[1], bool(params.get("compare")), brushed),
        "outcome": derive.outcome_mix(L),
        "trend": trend(L, window, params.get("metric") or "n", visible_agents, today),
        "heat": derive.heat(L),
        "tools": tools_top(L, aux),
        "persona_mini": persona.mini(p),
        "insight": insight.build(L, st, p, projects),
        "recs_ref": insight.RECS_REF,
    }
    if params.get("edition") == "lite":
        strip_rows = derive.sel(rows, (-(STRIP_DAYS - 1), 0), f, no_extra=True)
        by_day: dict[int, int] = {}
        for r in strip_rows:
            by_day[r["di"]] = by_day.get(r["di"], 0) + 1
        payload["strip"] = [{"d": derive.iso(today, d), "n": by_day.get(d, 0)}
                            for d in range(-(STRIP_DAYS - 1), 1)]
        payload["completion"] = {"value": _round(st["ok"], 1) if st["n"] else None,
                                 "n": st["ok_n"], "basis": "estimate", "label": "估计完成率"}
    return payload
