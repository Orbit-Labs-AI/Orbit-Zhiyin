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

value = 100·p. Every axis always gets a letter from the value alone: value ≥ 50 → the high
letter (D / I / M / V), value < 50 → the low letter (S / P / F / T); an axis with no units
counts as 50. One session is enough (``ok``); only an empty selection has no persona. The
interval and unit counts stay in the payload as context: ``decided`` marks an axis whose 95%
interval lies wholly outside the 45–55 band, and ``hint`` gently notes a small sample
(< ``SOFT_SESSIONS`` sessions) without withholding the type.

Turns of one session are not independent, so the D/V interval is cluster-robust: the
ratio estimator p = Σk_i/Σn_i over sessions i gets the linearisation variance
m/(m−1)·Σ(k_i − p·n_i)²/(Σn_i)² (Cochran 1977, *Sampling Techniques*, §6.4), which gives an
effective size n_eff = p(1−p)/var (Kish 1965 design effect), capped at the turn count and
at the session count when the variance is 0; the Wilson interval is taken at n_eff.
Duplicating turns inside sessions therefore never narrows the interval. I (one unit per
session) and M (one unit per day) keep the plain Wilson interval.

All bands live in ``CONFIG``; their provenance is in ``docs/modules/analytics/profiling.md``.
They are product defaults, not calibrated against a population baseline.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import derive, facts
from .typecopy import AXES, SOURCE, TYPES, copy

METHOD = "uiview-persona-v0"
# Every threshold of the classifier in one place (see profiling.md for sources).
CONFIG = {
    "soft_sessions": 30,         # below this the payload carries a "more data, more accurate" hint
    "midpoint": 50,              # value ≥ midpoint → high letter, < midpoint → low letter
    "band": (45.0, 55.0),        # an axis is ``decided`` when its interval clears this band
    "step_threshold": facts.STEP_THRESHOLD,  # D: a turn with ≥ this many steps is "delegated"
    "z": 1.96,                   # 95% two-sided
}
MIN_SESSIONS = 1
MIN_DAYS = 1
MIN_UNITS = {"D": 0, "I": 0, "M": 0, "V": 0}
SOFT_SESSIONS = CONFIG["soft_sessions"]
MIDPOINT = CONFIG["midpoint"]
STEP_THRESHOLD = CONFIG["step_threshold"]
# Signals each axis actually uses (the prototype's ``AXES.sig`` copy lists aspirational
# signals that are not computed; the payload reports what is).
SIG_USED = {
    "D": f"单轮步数 ≥ {STEP_THRESHOLD} 的轮次占比（按会话聚类）",
    "I": "首条消息是否无结构（未标执行顺序/验收标准、未达长度阈值、无列表或规格引用）",
    "M": "同日使用 ≥ 2 个 Agent 或会话时间重叠的天数占比",
    "V": "要求验证或运行验证命令的轮次占比（按会话聚类；含 Agent 自行运行的命令）",
}
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


def session_counts(rows: list[dict], aux: dict) -> dict[str, list[tuple[int, int]]]:
    """Per-session (k_i, n_i) for the turn-level axes D and V (sessions with turns only)."""
    out: dict[str, list[tuple[int, int]]] = {"D": [], "V": []}
    for r in rows:
        turns = (aux.get(r["id"]) or {}).get("turns") or []
        if not turns:
            continue
        out["D"].append((sum(1 for t in turns if t[0] >= STEP_THRESHOLD), len(turns)))
        out["V"].append((sum(1 for t in turns if t[1]), len(turns)))
    return out


def cluster_interval(clusters: list[tuple[int, int]], z: float = 1.96
                     ) -> tuple[float, float, float]:
    """(lo, hi, n_eff) of Σk/Σn with sessions as clusters (see module docstring)."""
    n = sum(c[1] for c in clusters)
    if n <= 0:
        return 0.0, 1.0, 0.0
    k = sum(c[0] for c in clusters)
    m = len(clusters)
    p = k / n
    var = (m / (m - 1) * sum((ki - p * ni) ** 2 for ki, ni in clusters) / (n * n)
           if m > 1 else 0.0)
    n_eff = min(float(n), p * (1 - p) / var) if var > 0 else float(min(n, m))
    lo, hi = wilson_p(p, n_eff, z)
    return lo, hi, n_eff


def wilson_p(p: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson interval for proportion p at (possibly effective, non-integer) size n."""
    if n <= 0:
        return 0.0, 1.0
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


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


def axis(spec: dict, k: int, n: int, days: int,
         clusters: list[tuple[int, int]] | None = None) -> dict:
    """One axis. ``clusters`` (per-session (k_i, n_i)) switches to the clustered interval."""
    key = spec["k"]
    value = 100 * k / n if n else None
    if clusters:
        lo, hi, n_eff = cluster_interval(clusters, CONFIG["z"])
        basis = "wilson_at_cluster_effective_n"
    else:
        lo, hi = wilson(k, n, CONFIG["z"])
        n_eff, basis = float(n), "wilson"
    lo, hi = round(lo * 100, 1), round(hi * 100, 1)
    # No "undetermined" band for the letter: it follows the value's lean; no units counts as 50.
    lean = MIDPOINT if value is None else value
    letter = spec["hi"] if lean >= MIDPOINT else spec["lo"]
    state = "no_data" if value is None else "settled"
    band_lo, band_hi = CONFIG["band"]
    decided = value is not None and (lo >= band_hi or hi <= band_lo)
    left, right = LEFT_RIGHT[key]
    return {"k": key, "value": None if value is None else round(value, 1), "lo": lo, "hi": hi,
            "n_units": n, "k_units": k, "unit": UNITS[key], "letter": letter, "state": state,
            "strong": None if value is None else round(max(value, 100 - value)),
            "left": left, "right": right, "dim": spec["dim"], "q": spec["q"], "sig": SIG_USED[key],
            "ref": REFS[key], "n_eff": round(n_eff, 1), "ci_basis": basis,
            "decided": decided}


def hint(n: int) -> str | None:
    """Gentle sample-size note; never blocks the type."""
    return f"基于 {n} 个会话，数据越多越准" if 0 < n < SOFT_SESSIONS else None


def persona(rows: list[dict], aux: dict, min_n: int = MIN_SESSIONS) -> dict:
    n = len(rows)
    days = len({r["d"] for r in rows})
    if n < max(1, min_n):
        return {"ok": False, "classified": False, "n": n, "days": days, "code": None,
                "zh": None, "en": None, "line": None, "v": None, "axes": [],
                "conf": "低", "hint": None, "decided_axes": 0}
    counts = units(rows, aux)
    clusters = session_counts(rows, aux)
    axes = [axis(spec, *counts[spec["k"]], days, clusters.get(spec["k"])) for spec in AXES]
    code = "".join(a["letter"] for a in axes)
    zh, en, line = copy(code)
    return {"ok": True, "classified": code in TYPES, "n": n, "days": days, "code": code,
            "zh": zh, "en": en, "line": line, "v": {a["k"]: a["value"] for a in axes},
            "axes": axes, "conf": "高" if n >= 100 else "中" if n >= SOFT_SESSIONS else "低",
            "hint": hint(n), "decided_axes": sum(1 for a in axes if a["decided"])}


def mini(p: dict) -> dict:
    return {"ok": p["ok"], "code": p["code"], "zh": p["zh"], "en": p["en"], "conf": p["conf"],
            "n": p["n"], "hint": p["hint"], "decided_axes": p.get("decided_axes", 0),
            "method": METHOD,
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
    open_n = axes["I"]["n_units"]
    # Unknown message counts stay unknown: they are neither a 0 bin nor a 0 average.
    with_msgs = [r for r in rows if r.get("msgs") is not None]
    msgs = sum(r["msgs"] for r in with_msgs)
    per = msgs / len(with_msgs) if with_msgs else None
    # Steps per message only over rows where both are known: an agent without human turns
    # has ``steps=None`` and its messages must not dilute the ratio (same rule as
    # ``derive.stats``'s ``auto``, which additionally requires ``steps``).
    stepped = [r for r in with_msgs if r.get("steps") is not None]
    stepped_msgs = sum(r["msgs"] for r in stepped)
    auto = sum(r["steps"] for r in stepped) / stepped_msgs if stepped_msgs else None
    d_txt = ("消息数未知" if per is None else f"每会话 {per:.1f} 条消息" +
             (f" · 单轮平均 {auto:.1f} 步" if auto is not None else ""))
    verify = st.get("verify")
    return {
        "D": {"txt": d_txt,
              "vals": _hist([r["msgs"] for r in with_msgs], 10, 20) if with_msgs else None,
              "lbl": "消息数 0 → 20+ 的会话数", "missing_n": len(rows) - len(with_msgs),
              "auto_n": len(stepped)},
        "I": {"txt": (f"结构化开场占 {round((open_n - axes['I']['k_units']) / open_n * 100)}%"
                      if open_n else "开场结构未知"),
              "vals": [round(v * 100) for v, _ in plan],
              "lbl": "项目结构化开场占比 · 低 → 高",
              "projects": [derive.project_name(projects, pid) for _, pid in plan]},
        "M": {"txt": f"日均 {avg_s:.1f} 个会话 · 同日 {avg_a:.1f} 个 Agent",
              "vals": _hist(list(by_day.values()), 8, 8), "lbl": "每日会话数 1 → 8+ 的天数"},
        "V": {"txt": ("验证情况未知" if verify is None
                      else f"{round(verify)}% 会话要求或运行了验证"),
              "verify_n": st.get("verify_n"),
              "vals": [round(v * 100) for v, _ in check], "lbl": "项目验证轮次占比 · 低 → 高",
              "projects": [derive.project_name(projects, pid) for _, pid in check]},
    }


def traits(p: dict) -> list[str]:
    """Trait chips for every axis with data (an axis without units gets no chip)."""
    names = {"D": "高吞吐", "S": "亲自掌舵", "I": "边做边想", "P": "先规划", "M": "多线程",
             "F": "单线专注", "V": "验收严格", "T": "信任结果"}
    return [names[a["letter"]] for a in p["axes"] if a["state"] != "no_data"]


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
    """Per-agent outcome rate. Sessions without an outcome are unknown, not failures, so the
    denominator is the sessions with ``out``; ``ok_ci`` is the Wilson 95% interval (±0 at
    0/n or n/n would be a Wald artefact), given from 5 outcomes on."""
    out = []
    for agent in agents:
        xs = [r for r in rows if r.get("a") == agent]
        st = derive.stats(xs, unknown=None)
        ok_n = st["ok_n"]
        ok_est = None if st["ok"] is None else round(st["ok"], 1)
        ci = None
        if ok_n >= 5:
            k = sum(1 for r in xs if r.get("out") == "ok")
            lo, hi = wilson(k, ok_n, CONFIG["z"])
            ci = [round(lo * 100, 1), round(hi * 100, 1)]
        out.append({"a": agent, "n": len(xs), "sessions": [r["id"] for r in xs[-5:]],
                    "corr_rate": round(st["fric"], 2) if st["msgs"] else None,
                    "ok_est": ok_est, "ok_ci": ci, "ok_n": ok_n,
                    "basis": "descriptive_estimate", "off": ok_n < 5})
    return out


def blind_spots(rows: list[dict]) -> list[dict]:
    """Top friction types. ``problem`` is the recommendation problem type the A1 surface
    (``recs_ref``) filters on; no per-item recommendation id is invented here."""
    from .insight import RECS_REF

    counts = sorted(derive.count_by(rows, "fric").items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return [{"type": t, "n": n, "problem": FRIC_PROBLEM.get(t), "recs_ref": RECS_REF}
            for t, n in counts]


def strengths(p: dict) -> list[dict]:
    settled = [a for a in p["axes"] if a["state"] != "no_data"]
    settled.sort(key=lambda a: -(a["strong"] or 0))
    return [{"k": a["k"], "letter": a["letter"], "text": STRENGTH[a["letter"]],
             "strong": a["strong"], "n_units": a["n_units"]} for a in settled[:3]]


def candidates(p: dict, top: int = 6) -> list[dict]:
    if not p["ok"] or not p["v"]:
        return []
    v = {k: MIDPOINT if x is None else x for k, x in p["v"].items()}
    scored = []
    for code, (zh, en, _) in TYPES.items():
        parts = [(v[spec["k"]] if code[i] == spec["hi"] else 100 - v[spec["k"]])
                 for i, spec in enumerate(AXES)]
        scored.append((-round(sum(parts) / 4, 1), code, zh, en))
    # Ties (an axis exactly at 50) keep the persona's own code first.
    scored.sort(key=lambda x: (x[0], x[1] != p["code"], x[1]))
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
    return _page(body, params, today)[0]


def _page(body: dict, params: dict, today: date) -> tuple[dict, list[dict]]:
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
    st = derive.stats(L, unknown=None)
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
        "low": {"n": p["n"], "need": MIN_SESSIONS, "soft": SOFT_SESSIONS},
        "hint": p["hint"],
        "reveal": {"candidates": candidates(p)},
    }
    return payload, L


def reveal(body: dict, params: dict, today: date, cap: int = 400) -> dict:
    """Reveal animation subset: code / copy / axes plus one particle per session."""
    full, L = _page(body, params, today)
    particles = [{"h": r.get("h"), "mi": r.get("mi"), "dur": r.get("dur"), "a": r.get("a")}
                 for r in L[-cap:]]
    keep = ("meta", "ok", "classified", "n", "conf", "code", "zh", "en", "line", "low", "hint")
    return {**{k: full[k] for k in keep},
            "axes": [{k: a[k] for k in ("k", "value", "letter", "strong", "left", "right",
                                        "state")} for a in full["axes"]],
            "candidates": full["reveal"]["candidates"], "particles": particles,
            "particles_total": len(L)}
