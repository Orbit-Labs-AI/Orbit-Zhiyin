"""A/B session comparison (A3-19 / A3-02): shared time scale, metric table, phase shares.

Works on two detail payloads from ``trajectory.build_detail``; Δ is always B − A. Smaller is
better for duration, errors and corrections; other metrics carry no direction. Unknown values
stay ``None`` and so do their Δ / pct / better.
"""

from __future__ import annotations

from collections import defaultdict

METRICS = (("dur", "时长", True), ("msgs", "你的消息", None), ("tools", "工具调用", None),
           ("errors", "错误", True), ("corr", "纠偏", True), ("auto", "自主比", None))
SLIM_EVENT = ("lane", "t", "w", "err", "corr", "event_uid")


class SameSession(ValueError):
    pass


def _values(detail: dict) -> dict:
    stats, head = detail["stats7"], detail["header"]
    msgs, steps = stats["msgs"], stats["steps"]
    return {"dur": head["dur"], "msgs": msgs, "tools": stats["tools"],
            "errors": stats["errors"], "corr": stats["corr"],
            "auto": round(steps / msgs, 2) if msgs else None}


def row(metric: str, label: str, a, b, good_down: bool | None) -> dict:
    if a is None or b is None:
        return {"metric": metric, "label": label, "a": a, "b": b, "delta": None, "pct": None,
                "better": None}
    delta = round(b - a, 2)
    pct = round(delta / a * 100) if a else None
    better = None
    if good_down is not None and delta:
        better = "b" if (delta < 0) == good_down else "a"
    return {"metric": metric, "label": label, "a": a, "b": b, "delta": delta, "pct": pct,
            "better": better}


def phase_pct(detail: dict) -> list[dict]:
    T = detail["trajectory"]["T"] or 1
    share: dict[str, float] = defaultdict(float)
    labels = {}
    for p in detail["trajectory"]["phases"]:
        share[p["phase"]] += p["t2"] - p["t"]
        labels[p["phase"]] = p["label"]
    return [{"phase": k, "label": labels[k], "pct": round(v / T * 100)} for k, v in share.items()]


def slim(detail: dict) -> dict:
    tr, head = detail["trajectory"], detail["header"]
    return {"id": head["id"], "title": head["title"], "a": head["a"], "dur": head["dur"],
            "T": tr["T"], "start_min": tr["start_min"], "lanes": tr["lanes"],
            "events": [{k: e.get(k) for k in SLIM_EVENT} for e in tr["events"]],
            "phases": tr["phases"], "moments": tr["moments"],
            "tools": detail["stats7"]["tools"], "errors": detail["stats7"]["errors"]}


def compare(a: dict, b: dict) -> dict:
    if a["header"]["id"] == b["header"]["id"]:
        raise SameSession("A 与 B 不能是同一个会话")
    va, vb = _values(a), _values(b)
    return {"T": max(a["trajectory"]["T"], b["trajectory"]["T"]),
            "a": slim(a), "b": slim(b),
            "table": [row(k, label, va[k], vb[k], good) for k, label, good in METRICS],
            "phase_pct": {"a": phase_pct(a), "b": phase_pct(b)},
            "basis": {"dur": "active_estimate", "corr": "lexical_candidate",
                      "auto": "steps_per_message", "phases": "inferred"}}


def suggest_b(rows: list[dict], session_uid: str) -> str | None:
    """Most recent other session of the same project (fact rows are newest first)."""
    me = next((r for r in rows if r["id"] == session_uid), None)
    if me is None or me.get("p") is None:
        return None
    same = [r for r in rows if r["p"] == me["p"] and r["id"] != session_uid]
    before = [r for r in same if (r["started_at"] or 0) <= (me["started_at"] or 0)]
    pick = (before or same)[:1]
    return pick[0]["id"] if pick else None
