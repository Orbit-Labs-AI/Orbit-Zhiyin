"""Deterministic four-axis persona (``uiview-persona-v0``): no model, Wilson 95% intervals.

Axes keep the prototype's value semantics (high value → first letter of the pair):
- D 委托 / S 掌舵 — unit = human-triggered turn; p = share of turns with ≥ 5 observed steps.
- I 即兴 / P 规划 — unit = task opening (first human message per session); p = share of
  openings *without* structure (list, acceptance words, spec-file reference, flagged
  ``execution_order`` / ``acceptance_criteria``, or ≥ 200 chars), so a high value reads I.
- M 多线 / F 专注 — unit = active day; p = share of days with time-overlapping sessions or
  ≥ 2 agents.
- V 求证 / T 信任 — unit = human-triggered turn; p = share asking for verification or running
  a validation command in the same turn.

value = 100·p. A letter is given only when the whole Wilson interval sits on one side of the
45–55 band and the axis has enough units (D/I/V ≥ 30, M ≥ 10 days) over ≥ 10 active days;
otherwise ``?``. The persona as a whole needs ≥ 30 sessions (``ok``).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import derive, facts
from .typecopy import AXES, SOURCE, TYPES, copy

METHOD = "uiview-persona-v0"
MIN_SESSIONS = 30
MIN_DAYS = 10
MIN_UNITS = {"D": 30, "I": 30, "M": 10, "V": 30}
STEP_THRESHOLD = facts.STEP_THRESHOLD
UNITS = {"D": "turn", "I": "session_opening", "M": "active_day", "V": "turn"}
LEFT_RIGHT = {"D": ("D 委托", "掌舵 S"), "I": ("P 规划", "即兴 I"), "M": ("M 多线", "专注 F"),
              "V": ("V 求证", "信任 T")}
REFS = {"D": "uiview.facts.steps", "I": "analytics.instruction.execution_order",
        "M": "uiview.facts.d", "V": "analytics.instruction.verification_requirements"}
STRENGTH = {"D": "大块委托，Agent 单轮走得远", "S": "亲自掌舵，节奏可控", "P": "开场交代清楚",
            "I": "边做边想，反应快", "M": "多线并行推进", "F": "单线专注深耕",
            "V": "验收严格", "T": "信任结果，吞吐高"}
FRIC_PROBLEM = {"方向错误": "wrong_approach", "工具 / 环境失败": "tool_env_failure",
                "改动过度": "overreach", "误解需求": "repeated_instruction",
                "并行会话冲突": "parallel_conflict", "流程过重（子代理）": "process_overhead",
                "额度 / 用量中断": "quota_interrupt"}
MONTHS = {k: i + 1 for i, k in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul",
                                          "aug", "sep", "oct", "nov", "dec"))}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _overlap(intervals: list[tuple[int, int]]) -> bool:
    intervals = sorted(intervals)
    end = None
    for start, stop in intervals:
        if end is not None and start < end:
            return True
        end = stop if end is None else max(end, stop)
    return False


def units(rows: list[dict], aux: dict) -> dict[str, tuple[int, int]]:
    """(k, n) per axis over the given rows."""
    turns = [t for r in rows for t in (aux.get(r["id"]) or {}).get("turns") or []]
    opens = [(aux.get(r["id"]) or {}).get("open") for r in rows]
    opens = [o for o in opens if o is not None]
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[r["d"]].append(r)
    multi = 0
    for day_rows in by_day.values():
        agents = {r.get("a") for r in day_rows}
        spans = [(a["t0"], a["t1"]) for a in (aux.get(r["id"]) or {} for r in day_rows)
                 if a.get("t0") is not None and a.get("t1") is not None]
        if len(agents) >= 2 or _overlap(spans):
            multi += 1
    return {"D": (sum(1 for t in turns if t[0] >= STEP_THRESHOLD), len(turns)),
            "I": (sum(1 for o in opens if o == 0), len(opens)),
            "M": (multi, len(by_day)),
            "V": (sum(1 for t in turns if t[1]), len(turns))}


def axis(spec: dict, k: int, n: int, days: int) -> dict:
    key = spec["k"]
    value = 100 * k / n if n else None
    lo, hi = wilson(k, n)
    lo, hi = round(lo * 100, 1), round(hi * 100, 1)
    if n < MIN_UNITS[key] or days < MIN_DAYS or value is None:
        letter, state = "?", "insufficient"
    elif lo >= 55:
        letter, state = spec["hi"], "settled"
    elif hi <= 45:
        letter, state = spec["lo"], "settled"
    else:
        letter, state = "?", "experimental"
    left, right = LEFT_RIGHT[key]
    return {"k": key, "value": None if value is None else round(value, 1), "lo": lo, "hi": hi,
            "n_units": n, "k_units": k, "unit": UNITS[key], "letter": letter, "state": state,
            "strong": None if value is None else round(max(value, 100 - value)),
            "left": left, "right": right, "dim": spec["dim"], "q": spec["q"], "sig": spec["sig"],
            "ref": REFS[key]}


def persona(rows: list[dict], aux: dict, min_n: int = MIN_SESSIONS) -> dict:
    n = len(rows)
    days = len({r["d"] for r in rows})
    if n < min_n or not n:
        return {"ok": False, "classified": False, "n": n, "days": days, "code": None,
                "zh": None, "en": None, "line": None, "v": None, "axes": [],
                "conf": "低"}
    counts = units(rows, aux)
    axes = [axis(spec, *counts[spec["k"]], days) for spec in AXES]
    code = "".join(a["letter"] for a in axes)
    zh, en, line = copy(code)
    return {"ok": True, "classified": code in TYPES, "n": n, "days": days, "code": code,
            "zh": zh, "en": en, "line": line, "v": {a["k"]: a["value"] for a in axes},
            "axes": axes, "conf": "高" if n >= 100 else "中"}


def mini(p: dict) -> dict:
    return {"ok": p["ok"], "code": p["code"], "zh": p["zh"], "en": p["en"], "conf": p["conf"],
            "n": p["n"], "method": METHOD,
            "axes": [{"k": a["k"], "value": a["value"], "strong": a["strong"],
                      "letter": a["letter"], "left": a["left"], "right": a["right"]}
                     for a in p["axes"]]}


# -- periods ----------------------------------------------------------------------------
def _month_window(year: int, month: int, today: date):
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return ((first - today).days, (nxt - timedelta(days=1) - today).days), f"{year}-{month:02d}"


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + month - 1 + delta
    return total // 12, total % 12 + 1


def resolve_period(period: str, today: date, first: int):
    """(window, label, prev_window | None, prev_label | None); ValueError when unknown."""
    if period == "all":
        return derive.win(0, first), "全部", None, None
    if period.isdigit() and int(period) > 0:
        days = int(period)
        return (-(days - 1), 0), f"近 {days} 天", (-(2 * days - 1), -days), f"前 {days} 天"
    if period in MONTHS:
        month = MONTHS[period]
        year = today.year if month <= today.month else today.year - 1
    elif len(period) == 7 and period[4] == "-" and period[:4].isdigit() and period[5:].isdigit():
        year, month = int(period[:4]), int(period[5:])
        if not 1 <= month <= 12:
            raise ValueError(f"Unknown period {period}")
    else:
        raise ValueError(f"Unknown period {period}")
    window, label = _month_window(year, month, today)
    prev, prev_label = _month_window(*_shift(year, month, -1), today)
    return window, label, prev, prev_label


def months(rows: list[dict], aux: dict, f: dict, today: date, count: int = 4) -> list[dict]:
    out = []
    for back in range(count - 1, -1, -1):
        year, month = _shift(today.year, today.month, -back)
        window, label = _month_window(year, month, today)
        p = persona(derive.sel(rows, window, f, no_extra=True), aux)
        out.append({"k": label, "lbl": label, "ok": p["ok"], "code": p["code"], "zh": p["zh"],
                    "n": p["n"], "v": p["v"]})
    return out


# -- page pieces ------------------------------------------------------------------------
def _hist(values: list[float], bins: int, top: float) -> list[int]:
    out = [0] * bins
    for v in values:
        out[min(bins - 1, int(v / top * bins))] += 1
    return out


def _by_ratio(item: tuple[float, str | None]) -> tuple[float, bool, str]:
    return item[0], item[1] is None, item[1] or ""


def evidence(rows: list[dict], aux: dict, p: dict, st: dict, projects: dict) -> dict:
    by_day = Counter(r["d"] for r in rows)
    agents_per_day = defaultdict(set)
    for r in rows:
        agents_per_day[r["d"]].add(r.get("a"))
    avg_s = len(rows) / len(by_day) if by_day else 0
    avg_a = sum(len(v) for v in agents_per_day.values()) / len(by_day) if by_day else 0
    per_project: dict[str | None, list] = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        a = aux.get(r["id"]) or {}
        entry = per_project[r.get("p")]
        if a.get("open") is not None:
            entry[0] += a["open"]
            entry[1] += 1
        turns = a.get("turns") or []
        entry[2] += sum(t[1] for t in turns)
        entry[3] += len(turns)
    # Sessions without a project (no cwd, Kimi without session_index.jsonl) share the
    # ``None`` bucket; the key keeps ties total so they never compare str < None.
    plan = sorted(((e[0] / e[1], pid) for pid, e in per_project.items() if e[1]), key=_by_ratio)
    check = sorted(((e[2] / e[3], pid) for pid, e in per_project.items() if e[3]), key=_by_ratio)
    axes = {a["k"]: a for a in p["axes"]}
    open_n = axes["I"]["n_units"] or 1
    return {
        "D": {"txt": f"每会话 {st['per']:.1f} 条消息 · 单轮平均 {st['auto']:.1f} 步",
              "vals": _hist([r.get("msgs") or 0 for r in rows], 10, 20),
              "lbl": "消息数 0 → 20+ 的会话数"},
        "I": {"txt": f"结构化开场占 {round((open_n - axes['I']['k_units']) / open_n * 100)}%",
              "vals": [round(v * 100) for v, _ in plan],
              "lbl": "项目结构化开场占比 · 低 → 高",
              "projects": [derive.project_name(projects, pid) for _, pid in plan]},
        "M": {"txt": f"日均 {avg_s:.1f} 个会话 · 同日 {avg_a:.1f} 个 Agent",
              "vals": _hist(list(by_day.values()), 8, 8), "lbl": "每日会话数 1 → 8+ 的天数"},
        "V": {"txt": f"{round(st['verify'])}% 会话要求或运行了验证",
              "vals": [round(v * 100) for v, _ in check], "lbl": "项目验证轮次占比 · 低 → 高",
              "projects": [derive.project_name(projects, pid) for _, pid in check]},
    }


def traits(p: dict) -> list[str]:
    """Trait chips for settled axes only (an axis showing ``?`` gets no chip)."""
    names = {"D": "高吞吐", "S": "亲自掌舵", "I": "边做边想", "P": "先规划", "M": "多线程",
             "F": "单线专注", "V": "验收严格", "T": "信任结果"}
    return [names[a["letter"]] for a in p["axes"] if a["letter"] in names]


def fingerprint(rows: list[dict], agents: list[str], cap: int = 200) -> dict:
    by_h = [[0] * len(agents) for _ in range(24)]
    dots: dict[int, list[dict]] = defaultdict(list)
    index = {a: i for i, a in enumerate(agents)}
    for r in rows:
        if r.get("h") is None:
            continue
        if r.get("a") in index:
            by_h[r["h"]][index[r["a"]]] += 1
        if len(dots[r["h"]]) < cap:
            dots[r["h"]].append({"id": r["id"], "mi": r.get("mi"), "dur": r.get("dur"),
                                 "a": r.get("a")})
    return {"agents": agents, "byH": by_h, "mxH": max([sum(x) for x in by_h] + [1]),
            "dots": {str(h): v for h, v in sorted(dots.items())}}


def fit(rows: list[dict], agents: list[str]) -> list[dict]:
    out = []
    for agent in agents:
        xs = [r for r in rows if r.get("a") == agent]
        st = derive.stats(xs)
        ok = st["ok"] / 100
        ci = round(1.96 * math.sqrt(ok * (1 - ok) / len(xs)) * 100) if len(xs) >= 5 else None
        out.append({"a": agent, "n": len(xs), "sessions": [r["id"] for r in xs[-5:]],
                    "corr_rate": round(st["fric"], 2) if st["msgs"] else None,
                    "ok_est": round(st["ok"], 1) if xs else None, "ok_ci": ci,
                    "basis": "descriptive_estimate", "off": len(xs) < 5})
    return out


def blind_spots(rows: list[dict]) -> list[dict]:
    counts = sorted(derive.count_by(rows, "fric").items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return [{"type": t, "n": n, "problem": FRIC_PROBLEM.get(t), "rec_id": None,
             "recs_ref": "/v1/recommendations?surface=A1"} for t, n in counts]


def strengths(p: dict) -> list[dict]:
    settled = [a for a in p["axes"] if a["letter"] != "?"]
    settled.sort(key=lambda a: -(a["strong"] or 0))
    return [{"k": a["k"], "letter": a["letter"], "text": STRENGTH[a["letter"]],
             "strong": a["strong"], "n_units": a["n_units"]} for a in settled[:3]]


def candidates(p: dict, top: int = 6) -> list[dict]:
    if not p["ok"] or not p["v"] or any(v is None for v in p["v"].values()):
        return []
    scored = []
    for code, (zh, en, _) in TYPES.items():
        parts = [(p["v"][spec["k"]] if code[i] == spec["hi"] else 100 - p["v"][spec["k"]])
                 for i, spec in enumerate(AXES)]
        scored.append((-round(sum(parts) / 4, 1), code, zh, en))
    scored.sort()
    return [{"code": c, "zh": zh, "en": en, "match": -s, "basis": "axis_distance"}
            for s, c, zh, en in scored[:top]]


def relax(rows: list[dict], window, f: dict, period: str, label: str, first: int,
          agents_meta: list[dict], projects: dict) -> list[dict]:
    out = []
    if f.get("project"):
        g = {**f, "project": None}
        out.append({"k": "project", "t": "项目 · " + projects.get(f["project"], {}).get(
            "name", f["project"]), "n": len(derive.sel(rows, window, g, no_extra=True))})
    if f.get("agents") is not None and set(f["agents"]) != {a["id"] for a in agents_meta}:
        g = {**f, "agents": None}
        shorts = [a["short"] for a in agents_meta if a["id"] in f["agents"]]
        out.append({"k": "agents", "t": "Agent · " + " / ".join(shorts),
                    "n": len(derive.sel(rows, window, g, no_extra=True))})
    if period != "all":
        out.append({"k": "period", "t": "周期 · " + label,
                    "n": len(derive.sel(rows, derive.win(0, first), f, no_extra=True))})
    return out


# -- page payloads ----------------------------------------------------------------------
def _filters(params: dict) -> dict:
    return {"agents": params.get("agents"), "project": params.get("project")}


def page(body: dict, params: dict, today: date) -> dict:
    """A2 / Lite persona payload for ``period`` (``ValueError`` on an unknown period)."""
    from . import CONTRACT, VERSION

    rows = derive.prepare(body.get("rows") or [], today)
    aux = body.get("aux") or {}
    agents_meta = body.get("agents") or []
    projects = {p["id"]: p for p in body.get("projects") or []}
    first = derive.first_index(rows)
    period = params.get("period") or "90"
    window, label, prev_window, prev_label = resolve_period(period, today, first)
    f = _filters(params)
    L = derive.sel(rows, window, f, no_extra=True)
    p = persona(L, aux)
    st = derive.stats(L)
    agent_ids = [a["id"] for a in agents_meta if f["agents"] is None or a["id"] in f["agents"]]
    prev = None
    if prev_window is not None:
        pp = persona(derive.sel(rows, prev_window, f, no_extra=True), aux)
        prev = {"period": prev_label, "ok": pp["ok"], "code": pp["code"], "zh": pp["zh"],
                "n": pp["n"], "v": pp["v"]}
    ev = evidence(L, aux, p, st, projects) if p["ok"] else {}
    axes = [{**a, "evidence": ev.get(a["k"])} for a in p["axes"]]
    payload = {
        "meta": {"contract": CONTRACT, "version": VERSION, "method": METHOD,
                 "type_copy": SOURCE, "today": today.isoformat(), "period": period,
                 "period_label": label,
                 "window": [derive.iso(today, window[0]), derive.iso(today, window[1])],
                 "filters": {k: v for k, v in f.items() if v not in (None, "")},
                 "display_timezone": (body.get("meta") or {}).get("display_timezone")},
        "ok": p["ok"], "classified": p["classified"], "n": p["n"], "days": p["days"],
        "agents_n": len({r.get("a") for r in L if r.get("a")}), "conf": p["conf"],
        "code": p["code"], "zh": p["zh"], "en": p["en"], "line": p["line"], "v": p["v"],
        "axes": axes, "traits": traits(p),
        "months": months(rows, aux, f, today),
        "prev": prev, "vs": params.get("vs"),
        "fp": fingerprint(L, agent_ids), "fit": fit(L, agent_ids),
        "strengths": strengths(p), "blind_spots": blind_spots(L),
        "relax": relax(rows, window, f, period, label, first, agents_meta, projects),
        "low": {"n": p["n"], "need": MIN_SESSIONS},
        "reveal": {"candidates": candidates(p)},
    }
    return payload


def reveal(body: dict, params: dict, today: date, cap: int = 400) -> dict:
    """Reveal animation subset: code / copy / axes plus one particle per session."""
    full = page(body, params, today)
    rows = derive.prepare(body.get("rows") or [], today)
    window, *_ = resolve_period(params.get("period") or "90", today, derive.first_index(rows))
    L = derive.sel(rows, window, _filters(params), no_extra=True)
    particles = [{"h": r.get("h"), "mi": r.get("mi"), "dur": r.get("dur"), "a": r.get("a")}
                 for r in L[-cap:]]
    keep = ("meta", "ok", "classified", "n", "conf", "code", "zh", "en", "line", "low")
    return {**{k: full[k] for k in keep},
            "axes": [{k: a[k] for k in ("k", "value", "letter", "strong", "left", "right",
                                        "state")} for a in full["axes"]],
            "candidates": full["reveal"]["candidates"], "particles": particles,
            "particles_total": len(L)}
