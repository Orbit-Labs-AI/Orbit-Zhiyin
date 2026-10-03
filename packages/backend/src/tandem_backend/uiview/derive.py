"""Python port of the prototype's ``15-derive.js`` (+ ``weekly`` from ``35-visuals.js``).

Same formulas over fact rows; the only deliberate difference is ``auto``: the prototype's
``tools × 1.54 / msgs`` stand-in is replaced by the observed ``steps / msgs``. Day indices
are relative to ``today`` (0 = today, -1 = yesterday …), so windows read like the prototype's
``win(range)`` with ``LASTDAY`` = today. JS ``sum`` treats null as 0; the same holds here,
except that an all-null ``tok`` stays ``None``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta

RANGES = (7, 30, 90, 0)
OUT_IDS = (("ok", "完成", "var(--good)"), ("part", "部分完成", "var(--warn)"),
           ("fail", "放弃", "var(--crit)"))
AGENT_COLORS = {"claude_code": "var(--a1)", "codex": "var(--a2)", "gemini": "var(--a3)",
                "gemini_cli": "var(--a3)", "deepseek": "var(--a4)", "dsh": "var(--a4)",
                "copilot": "var(--a5)"}


def prepare(rows: Iterable[dict], today: date) -> list[dict]:
    """Copy non-excluded dated rows with ``di`` (day index) and ``wd`` (Mon = 0)."""
    out = []
    for row in rows:
        if row.get("excluded") or not row.get("d"):
            continue
        day = date.fromisoformat(row["d"])
        out.append({**row, "di": (day - today).days, "wd": day.weekday()})
    return out


def first_index(rows: list[dict]) -> int:
    return min((r["di"] for r in rows), default=0)


def win(range_: int, first: int = 0) -> tuple[int, int]:
    if range_ in (7, 30, 90):
        return (-(range_ - 1), 0)
    return (min(first, 0), 0)


def prev_win(range_: int, first: int = 0) -> tuple[int, int] | None:
    if not range_:
        return None
    a = win(range_, first)[0]
    start = a - range_
    return None if start < first else (start, a - 1)


def passes(row: dict, f: dict, no_extra: bool = False) -> bool:
    if row.get("live"):
        return False
    agents = f.get("agents")
    if agents is not None and row.get("a") not in agents:
        return False
    if f.get("project") and row.get("p") != f["project"]:
        return False
    if f.get("agent") and row.get("a") != f["agent"]:
        return False
    if not no_extra:
        for key, field in (("topic", "topic"), ("outcome", "out"), ("fric", "fric")):
            if f.get(key) and row.get(field) != f[key]:
                return False
        if f.get("hour") is not None and row.get("h") != f["hour"]:
            return False
    return True


def sel(rows: list[dict], window: tuple[int, int], f: dict | None = None,
        no_extra: bool = False) -> list[dict]:
    f = f or {}
    return [r for r in rows if window[0] <= r["di"] <= window[1] and passes(r, f, no_extra)]


def _sum(rows: list[dict], key: str) -> float:
    return sum(r.get(key) or 0 for r in rows)


def _share(rows: list[dict], key: str, hit, unknown):
    """Share (0–100) of rows whose ``key`` is known and satisfies ``hit``; ``unknown`` if none."""
    known = [r for r in rows if r.get(key) is not None]
    if not known:
        return unknown, 0
    return sum(1 for r in known if hit(r[key])) / len(known) * 100, len(known)


def stats(rows: list[dict], unknown: float | None = 0) -> dict:
    """Window aggregates. Ratios only use rows where their inputs are known.

    ``auto`` = Σsteps / Σmsgs over rows with ``steps`` (agents without human turns have
    ``steps=None`` and must not add their messages to the denominator); ``verify`` / ``ok``
    are shares of rows whose ``verify`` / ``out`` is known. With no known row the ratio is
    ``unknown`` — ``0`` keeps the prototype's numeric contract, the overview passes ``None``.
    ``*_n`` report how many rows each ratio rests on.
    """
    n = len(rows)
    mins, msgs, tools = _sum(rows, "dur"), _sum(rows, "msgs"), _sum(rows, "tools")
    corr, steps = _sum(rows, "corr"), _sum(rows, "steps")
    known = [r for r in rows if r.get("errors") is not None]
    errors = _sum(known, "errors")
    known_tools = _sum(known, "tools")
    toks = [r["tok"] for r in rows if r.get("tok") is not None]
    stepped = [r for r in rows if r.get("steps") is not None]
    stepped_msgs = _sum(stepped, "msgs")
    verify, verify_n = _share(rows, "verify", bool, unknown)
    ok, ok_n = _share(rows, "out", lambda v: v == "ok", unknown)
    return {
        "n": n, "hours": mins / 60, "msgs": msgs, "tools": tools,
        "errors": errors if known else None, "corr": corr, "steps": steps,
        "tok": sum(toks) if toks else None,
        "auto": steps / stepped_msgs if stepped_msgs else unknown, "auto_n": len(stepped),
        "fric": corr / msgs * 100 if msgs else 0,
        "per": msgs / n if n else 0,
        "verify": verify, "verify_n": verify_n, "ok": ok, "ok_n": ok_n,
        "err": errors / known_tools * 100 if known and known_tools else None,
    }


def md(today: date, di: int) -> str:
    day = today + timedelta(days=di)
    return f"{day.month}/{day.day}"


def iso(today: date, di: int) -> str:
    return (today + timedelta(days=di)).isoformat()


def buckets(window: tuple[int, int], today: date) -> list[dict]:
    a0, b0 = window
    if b0 - a0 + 1 <= 31:
        return [{"a": d, "b": d, "lbl": md(today, d)} for d in range(a0, b0 + 1)]
    out, a = [], a0
    while a <= b0:
        wd = (today + timedelta(days=a)).weekday()
        b = min(b0, a + (6 - wd))
        out.append({"a": a, "b": b, "lbl": md(today, a)})
        a = b + 1
    return out


def metric_value(rows: list[dict], metric: str):
    if metric == "h":
        return _sum(rows, "dur") / 60
    if metric == "tok":
        toks = [r["tok"] for r in rows if r.get("tok") is not None]
        return sum(toks) / 1e6 if toks or not rows else None
    return len(rows)


def series(rows: list[dict], window: tuple[int, int], metric: str, agents: list[str],
           today: date) -> list[dict]:
    out = []
    for bk in buckets(window, today):
        values = [metric_value([r for r in rows if r.get("a") == ag and bk["a"] <= r["di"]
                                <= bk["b"]], metric) for ag in agents]
        out.append({**bk, "v": values})
    return out


def weekly(fn: Callable[[list[dict]], float], rows: list[dict], end: int, n: int,
           f: dict | None = None) -> list:
    out = []
    for k in range(n - 1, -1, -1):
        b = end - k * 7
        out.append(fn(sel(rows, (b - 6, b), f, no_extra=True)))
    return out


def daily(fn: Callable[[list[dict]], float], rows: list[dict], end: int, n: int,
          f: dict | None = None) -> list:
    return [fn(sel(rows, (d, d), f, no_extra=True)) for d in range(end - n + 1, end + 1)]


def heat(rows: list[dict]) -> dict:
    hm = [[0] * 24 for _ in range(7)]
    cm = [[0] * 24 for _ in range(7)]
    for r in rows:
        if r.get("h") is None:
            continue
        hm[r["wd"]][r["h"]] += r.get("msgs") or 0
        cm[r["wd"]][r["h"]] += r.get("corr") or 0
    peak = [0, 0]
    for d in range(7):
        for h in range(24):
            if hm[d][h] > hm[peak[0]][peak[1]]:
                peak = [d, h]
    return {"H": hm, "C": cm, "peak": peak}


def tool_rows(rows: list[dict], aux: dict) -> list[dict]:
    """Observed per-tool totals (the prototype scaled a fixed table; this sums L1 rows)."""
    agg: dict[str, list] = {}
    for r in rows:
        for name, (kind, n, fails, known) in ((aux.get(r["id"]) or {}).get("tools") or {}).items():
            entry = agg.setdefault(name, [kind, 0, 0, 0])
            entry[1] += n
            entry[2] += fails
            entry[3] += known
    out = [{"name": name, "kind": v[0], "n": v[1], "fails": v[2] if v[3] else None,
            "err": v[2] / v[3] if v[3] else None, "known": v[3]} for name, v in agg.items()]
    out.sort(key=lambda t: (-t["n"], t["name"]))
    return out


def outcome_mix(rows: list[dict]) -> list[dict]:
    return [{"id": oid, "name": name, "color": color, "basis": "estimate",
             "value": sum(1 for r in rows if r.get("out") == oid)} for oid, name, color in OUT_IDS]


NO_PROJECT = "未归类"  # label for sessions without a project (same word as ai.ask)


def project_name(projects: dict, pid: str | None) -> str:
    """Display name for a project id; sessions without a project (no cwd, Kimi without
    session_index.jsonl) carry ``None`` and get ``NO_PROJECT`` instead of a null label."""
    if pid is None:
        return NO_PROJECT
    return (projects.get(pid) or {}).get("name") or pid


def count_by(rows: list[dict], key: str) -> dict:
    out: dict = {}
    for r in rows:
        value = r.get(key)
        if value is not None:
            out[value] = out.get(value, 0) + 1
    return out


def agent_color(agent: str, index: int) -> str:
    return AGENT_COLORS.get(agent, f"var(--a{(index % 5) + 1})")
