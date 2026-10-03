"""Multi-signal persona axes from additive sufficient statistics (``uiview-persona-v1``).

Each axis averages several signals; every signal is mapped to a 0–100 *score* (high = the
axis' high letter D / I / M / V) through piecewise-linear anchors, so no single extreme
value dominates (the map is bounded and flat at the ends). The axis value is the weighted
mean of the scores of the signals that have data; a missing signal drops out and the others'
weights are renormalised. Anchors and weights are product defaults, documented with their
reasoning in ``docs/modules/analytics/profiling.md``; they are not fitted to a population.

Two signal kinds:

* ``ratio`` — Σk / Σn over clusters (sessions, or days), mapped through the anchors. The
  interval is the Wilson interval at the cluster-robust effective size (Cochran 1977 §6.4,
  Kish 1965), mapped through the same monotone anchors.
* ``mean`` — mean over units (sessions or days) of an already mapped per-unit score; the
  interval is mean ± z·sd/√m (z·25 when there is a single unit).

Everything a group needs is an additive sufficient statistic: per ratio signal
(K, N, m, Σk², Σkn, Σn²), per mean signal (S, S², m), plus a per-day map
{day: [sessions, agents, self-overlap]}. ``combine`` adds the statistics of groups with
*disjoint agent sets* (the per-day map adds sessions and agents and ORs the overlap flag,
which is exact because two agents on one day already make the day multi-thread). Any agent
subset is therefore one sum of per-agent statistics — nothing is precomputed per subset.
"""

from __future__ import annotations

import math
from collections import defaultdict

STEP_THRESHOLD = 5
Z = 1.96

# (key, axis, weight, kind, unit, anchors, label)
SIGNALS = (
    ("steps", "D", 0.50, "ratio", "turn", ((0, 5), (1, 95)),
     f"单轮自主步数（≥ {STEP_THRESHOLD} 步的轮次占比）"),
    ("msgs", "D", 0.25, "mean", "session",
     ((1, 80), (3, 65), (8, 50), (20, 25), (50, 10)), "每会话消息数（越少越委托）"),
    ("stops", "D", 0.25, "ratio", "turn",
     ((0, 65), (0.1, 50), (0.25, 25), (0.5, 8), (1, 5)), "打断与中止率（越高越掌舵）"),
    ("struct", "I", 0.35, "ratio", "session", ((0, 5), (1, 95)),
     "开场未写执行顺序 / 验收标准的占比"),
    ("spec", "I", 0.20, "ratio", "session",
     ((0, 60), (0.15, 45), (0.4, 20), (1, 5)), "开场引用规格 / 计划文件的占比（越高越规划）"),
    ("length", "I", 0.15, "mean", "session",
     ((0, 85), (20, 85), (80, 62), (200, 40), (600, 18), (1500, 10)),
     "首条消息长度（越长越规划）"),
    ("redirect", "I", 0.30, "mean", "session",
     ((0, 35), (0.1, 55), (0.25, 75), (0.5, 92), (1, 95)), "中途改向（纠偏消息占比）"),
    ("parallel", "M", 0.35, "ratio", "day", ((0, 5), (1, 95)),
     "同日 ≥ 2 个 Agent 或会话时间重叠的天数占比"),
    ("per_day", "M", 0.25, "mean", "day",
     ((1, 20), (2, 40), (3, 52), (5, 70), (10, 90)), "每日会话数"),
    ("agents_day", "M", 0.25, "mean", "day",
     ((1, 30), (2, 70), (3, 88), (5, 95)), "同日使用的 Agent 数"),
    ("subagents", "M", 0.15, "ratio", "session",
     ((0, 40), (0.1, 55), (0.3, 75), (0.6, 92), (1, 95)), "子代理并行度（≥ 2 个子代理同时运行的会话占比）"),
    ("verify", "V", 0.70, "ratio", "turn", ((0, 5), (0.05, 25), (0.3, 50), (0.6, 85), (1, 95)),
     "你要求测试 / 编译 / 检查的轮次占比（Agent 自行跑的不算）"),
    ("rework", "V", 0.30, "ratio", "session",
     ((0, 40), (0.1, 60), (0.25, 80), (0.5, 95), (1, 95)), "回滚与重做率（有回滚 / 重做的会话占比）"),
)
SPEC = {s[0]: s for s in SIGNALS}
BY_AXIS = {k: [s for s in SIGNALS if s[1] == k] for k in "DIMV"}
RATIO = [s[0] for s in SIGNALS if s[3] == "ratio"]
MEAN = [s[0] for s in SIGNALS if s[3] == "mean"]
DAY_SIGNALS = ("parallel", "per_day", "agents_day")


def pl(x: float, anchors) -> float:
    """Piecewise-linear map through ``anchors`` [(x, score), …], flat beyond the ends."""
    if x <= anchors[0][0]:
        return float(anchors[0][1])
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:], strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(anchors[-1][1])


# -- per-session units ------------------------------------------------------------------------
# Meaning of the per-row unit columns on the wire (dk dn vk ...). Part of
# ``services.sections.rules_digest``: bump it when a unit changes meaning so cached
# uiview_facts snapshots are recomputed instead of serving the old unit to new anchors.
# v2: ``vk`` counts only turns where the user asked for verification (was: asked or ran).
UNITS_VERSION = "persona-units-v2"


def requested_turns(turns) -> int:
    """V axis unit: turns in which *the user* asked for a test / build / check.

    The axis asks how the user makes sure the work is right, so validation commands the agent
    runs on its own (Claude Code and Codex often run tests unprompted) are not counted; they
    stay visible as evidence (``agent_only_turns``). A turn is ``[steps, verify, requested,
    ran, …]``; snapshots from before that split carry ``[steps, verify]`` only and fall back
    to ``verify``.
    """
    return sum(1 for t in turns if (t[2] if len(t) >= 4 else t[1]))


def session_units(row: dict, a: dict | None) -> dict:
    """The persona inputs of one session, from a facts row + its aux, or (``a is None``) from
    a wire row that already carries ``dk`` / ``dn`` / … from ``facts.aux_units``."""
    if a is not None:
        turns = a.get("turns") or []
        u = {"dk": sum(1 for t in turns if t[0] >= STEP_THRESHOLD), "dn": len(turns),
             "vk": requested_turns(turns),
             "ik": sum(1 for t in turns if len(t) >= 6 and t[4] and t[5]),
             "kn": sum(1 for t in turns if len(t) >= 6 and t[5]),
             "op": a.get("open"), "ol": a.get("olen"), "oa": a.get("oacc"),
             "os": a.get("ospec"), "sc": a.get("sub"), "rb": a.get("rb"),
             "t0": a.get("t0"), "t1": a.get("t1")}
    else:
        src = row
        u = {k: src.get(k) for k in ("dk", "dn", "vk", "ik", "kn", "op", "ol", "oa", "os",
                                     "sc", "rb", "t0", "t1")}
    # Snapshots from before the split carry only ``open``: it stands in for ``oa`` (new
    # snapshots set both or neither, so this is the same rule as 15-derive.js psContrib).
    if u["oa"] is None and u["op"] is not None:
        u["oa"] = u["op"]
    u["msgs"], u["corr"] = row.get("msgs"), row.get("corr")
    return u


def session_contrib(u: dict) -> dict:
    """{signal: (k, n)} for session-level ratio signals and {signal: score} for mean signals;
    a signal without data for this session is absent."""
    ratio, mean = {}, {}
    if u.get("dn"):
        ratio["steps"] = (u.get("dk") or 0, u["dn"])
        ratio["verify"] = (u.get("vk") or 0, u["dn"])
    if u.get("kn"):
        ratio["stops"] = (u.get("ik") or 0, u["kn"])
    if u.get("oa") is not None:
        ratio["struct"] = (1 - int(bool(u["oa"])), 1)
    if u.get("os") is not None:
        ratio["spec"] = (int(bool(u["os"])), 1)
    if u.get("sc") is not None:
        ratio["subagents"] = (int(u["sc"] >= 2), 1)
    if u.get("rb") is not None:
        ratio["rework"] = (int(bool(u["rb"])), 1)
    msgs = u.get("msgs")
    if msgs:
        mean["msgs"] = pl(msgs, SPEC["msgs"][5])
        if msgs >= 2 and u.get("corr") is not None:
            mean["redirect"] = pl(min(1.0, u["corr"] / msgs), SPEC["redirect"][5])
    if u.get("ol") is not None:
        mean["length"] = pl(u["ol"], SPEC["length"][5])
    return {"ratio": ratio, "mean": mean}


# -- sufficient statistics --------------------------------------------------------------------
def empty() -> dict:
    return {"n": 0, "ratio": {k: [0, 0, 0, 0, 0, 0] for k in RATIO},
            "mean": {k: [0.0, 0.0, 0] for k in MEAN}, "days": {}}


def _add_ratio(acc: list, k: float, n: float) -> None:
    acc[0] += k
    acc[1] += n
    acc[2] += 1
    acc[3] += k * k
    acc[4] += k * n
    acc[5] += n * n


def _add_mean(acc: list, score: float) -> None:
    acc[0] += score
    acc[1] += score * score
    acc[2] += 1


def _overlap(spans: list[tuple[int, int]]) -> bool:
    end = None
    for start, stop in sorted(spans):
        if end is not None and start < end:
            return True
        end = stop if end is None else max(end, stop)
    return False


def suff(rows: list[dict], aux: dict | None = None) -> dict:
    """Sufficient statistics of ``rows`` (facts rows; ``aux`` keyed by row id, or ``None``
    for wire rows that carry their units)."""
    out = empty()
    by_day: dict = defaultdict(list)
    for r in rows:
        u = session_units(r, None if aux is None else aux.get(r["id"]) or {})
        c = session_contrib(u)
        out["n"] += 1
        for key, (k, n) in c["ratio"].items():
            _add_ratio(out["ratio"][key], k, n)
        for key, score in c["mean"].items():
            _add_mean(out["mean"][key], score)
        if r.get("d") is not None:
            by_day[r["d"]].append((r.get("a"), u.get("t0"), u.get("t1")))
    for day, items in by_day.items():
        agents = {a for a, _, _ in items}
        spans = [(t0, t1) for _, t0, t1 in items if t0 is not None and t1 is not None]
        out["days"][day] = [len(items), len(agents), int(_overlap(spans))]
    return out


def combine(parts) -> dict:
    """Sum of the statistics of groups with disjoint agent sets (see module docstring)."""
    out = empty()
    for part in parts:
        out["n"] += part["n"]
        for key in RATIO:
            out["ratio"][key] = [a + b for a, b in zip(out["ratio"][key], part["ratio"][key],
                                                       strict=True)]
        for key in MEAN:
            out["mean"][key] = [a + b for a, b in zip(out["mean"][key], part["mean"][key],
                                                      strict=True)]
        for day, (n, agents, ov) in part["days"].items():
            cur = out["days"].setdefault(day, [0, 0, 0])
            cur[0] += n
            cur[1] += agents
            cur[2] = int(cur[2] or ov)
    return out


def by_agent(rows: list[dict], aux: dict | None = None) -> dict:
    """One statistics block per agent (computed once; any subset is ``combine`` of these)."""
    groups: dict = defaultdict(list)
    for r in rows:
        groups[r.get("a")].append(r)
    return {agent: suff(xs, aux) for agent, xs in groups.items()}


def _with_days(s: dict) -> dict:
    """Day-level ratio / mean statistics from the merged per-day map."""
    ratio, mean = [0, 0, 0, 0, 0, 0], {"per_day": [0.0, 0.0, 0], "agents_day": [0.0, 0.0, 0]}
    for n, agents, ov in s["days"].values():
        _add_ratio(ratio, int(agents >= 2 or bool(ov)), 1)
        _add_mean(mean["per_day"], pl(n, SPEC["per_day"][5]))
        _add_mean(mean["agents_day"], pl(agents, SPEC["agents_day"][5]))
    return {"parallel": ratio, **mean}


# -- intervals --------------------------------------------------------------------------------
def wilson_p(p: float, n: float, z: float = Z) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n))) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def ratio_estimate(acc: list) -> tuple[float, float, float, float] | None:
    """(p, lo, hi, n_eff) of Σk/Σn with clusters, or ``None`` without units."""
    k, n, m, kk, kn, nn = acc
    if n <= 0:
        return None
    p = k / n
    ss = kk - 2 * p * kn + p * p * nn  # Σ(k_i − p·n_i)²
    var = m / (m - 1) * max(0.0, ss) / (n * n) if m > 1 else 0.0
    n_eff = min(float(n), p * (1 - p) / var) if var > 0 else float(min(n, m))
    lo, hi = wilson_p(p, n_eff)
    return p, lo, hi, n_eff


def signal(key: str, acc: list) -> dict | None:
    _, axis, weight, kind, unit, anchors, label = SPEC[key]
    if kind == "ratio":
        est = ratio_estimate(acc)
        if est is None:
            return None
        p, lo, hi, n_eff = est
        a, b = pl(lo, anchors), pl(hi, anchors)
        return {"key": key, "label": label, "weight": weight, "unit": unit, "kind": kind,
                "raw": round(p, 4), "score": pl(p, anchors), "lo": min(a, b), "hi": max(a, b),
                "n": acc[1], "m": acc[2], "n_eff": round(n_eff, 1)}
    s, s2, m = acc
    if m <= 0:
        return None
    mean = s / m
    sd = math.sqrt(max(0.0, (s2 - m * mean * mean) / (m - 1))) if m > 1 else None
    half = Z * (sd / math.sqrt(m) if sd is not None else 25.0)
    return {"key": key, "label": label, "weight": weight, "unit": unit, "kind": kind,
            "raw": None, "score": mean, "lo": max(0.0, mean - half), "hi": min(100.0, mean + half),
            "n": m, "m": m, "n_eff": float(m)}


def axis_signals(s: dict, key: str) -> list[dict]:
    days = _with_days(s)
    out = []
    for spec in BY_AXIS[key]:
        name, kind = spec[0], spec[3]
        acc = days[name] if name in DAY_SIGNALS else s[kind][name]
        sig = signal(name, acc)
        if sig is not None:
            out.append(sig)
    return out


def compose(sigs: list[dict]) -> dict:
    """Weighted value, interval and signal agreement of one axis (``None`` value without data)."""
    if not sigs:
        return {"value": None, "lo": 0.0, "hi": 100.0, "agree": None}
    w = sum(x["weight"] for x in sigs)
    value = sum(x["weight"] * x["score"] for x in sigs) / w
    se = math.sqrt(sum((x["weight"] * (x["hi"] - x["lo"]) / (2 * Z)) ** 2 for x in sigs)) / w
    side = value >= 50
    agree = sum(x["weight"] * (0.5 if x["score"] == 50 else float((x["score"] >= 50) == side))
                for x in sigs) / w
    return {"value": value, "lo": max(0.0, value - Z * se), "hi": min(100.0, value + Z * se),
            "agree": agree}
