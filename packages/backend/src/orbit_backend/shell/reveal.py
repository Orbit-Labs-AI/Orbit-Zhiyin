"""Persona reveal payload (OB-05/OB-06, REV-01/REV-02, SET-19, HLP-03) and the short
persona summary shared by the popover, widgets and onboarding (POP-08, WG-02).

The profile is ``analytics.presentation.profile.build_profile`` over the cached tasks /
instruction / preferences snapshots, built through the export package's
``exporting.sharecard.persona_profile`` so the reveal, the share card and the report show
the same persona. Without the export package the payload says ``persona_unavailable``.

Axis mapping onto the UI's four letters (prototypes/advance/src/js/05-data.js ``AXES``):
UI value 0..100 per axis, ≥50 the first (high) letter, <50 the second; there is no
undetermined band, so a profile always yields a full four-letter code.

    D 委托 ↔ S 掌舵   = delegation   (profile 委托 D ↔ 控制 C)
    I 即兴 ↔ P 规划   = planning, inverted (profile 规划 P ↔ 探索 E)
    M 多线 ↔ F 专注   = orchestration (profile 编排 O ↔ 专精 S)
    V 求证 ↔ T 信任   = verification  (profile 验证 V ↔ 加速 A)

The value is the profile's ``observed_score``; below the profile's own task minimum it falls
back to ``observed_mean`` (delegation) or ``signal_rate`` (single-pole planning /
verification). An axis without any value counts as 50 (high letter) and is reported with
``value = None``. Only a missing profile or no value on any axis blocks the reveal.
"""

from __future__ import annotations

import math
from itertools import product

from . import cached_section, default_scope, has_db, reader, submit_section

MIN_UNITS, MIN_ACTIVE_DAYS = 0, 0
MIDPOINT = 50
SINGLE_POLE = ("planning", "verification")
PERSONA_SECTIONS = ("tasks", "instruction", "preferences", "overview")
# (UI key, profile axis, high letter, high name, low letter, low name, inverted)
UI_AXES = (
    ("D", "delegation", "D", "委托", "S", "掌舵", False),
    ("I", "planning", "I", "即兴", "P", "规划", True),
    ("M", "orchestration", "M", "多线", "F", "专注", False),
    ("V", "verification", "V", "求证", "T", "信任", False),
)
# Profile direction codes → UI letters.
DIRECTION = {"delegation": {"D": "D", "C": "S"}, "planning": {"P": "P", "E": "I"},
             "orchestration": {"O": "M", "S": "F"}, "verification": {"V": "V", "A": "T"}}
SIGNALS = {"delegation": "指令里要求的自主程度（requested_autonomy）",
           "planning": "指令里的执行顺序要求（execution_order，只提取规划侧）",
           "orchestration": "显式编排选择（尚未提取）",
           "verification": "指令里的验证要求（verification_requirements，只提取验证侧）"}
REASON_TEXT = {"persona_unavailable": "画像模块不可用", "insufficient_data": "样本不足",
               "unsettled_code": "有维度尚未定型", "computing": "正在计算"}


def _export():
    """(sharecard, type_copy) from the export package, or None until it is merged."""
    try:
        from ..exporting import sharecard, type_copy  # type: ignore[attr-defined]
    except ImportError:
        return None
    return sharecard, type_copy


def type_table() -> dict[str, tuple[str, str, str]]:
    exp = _export()
    return dict(exp[1].TYPES) if exp else {}


def all_codes() -> list[str]:
    return ["".join(c) for c in product("DS", "IP", "MF", "VT")]


# -- pure composition (tests feed hand-written profiles) -----------------------------------
def ui_axes(profile: dict | None) -> list[dict]:
    """Profile axes → the UI's four axes with value/lo/hi (0..100), letter and settled."""
    axes = (profile or {}).get("axes") or {}
    out = []
    for key, name, hi, hi_name, lo, lo_name, inverted in UI_AXES:
        axis = axes.get(name) or {}
        score = axis.get("observed_score")
        if score is None:
            score = axis.get("signal_rate" if name in SINGLE_POLE else "observed_mean")
        n = int(axis.get("effective_task_n") or 0)
        m = max(n, int(axis.get("observable_task_n") or 0))
        value = lo_v = hi_v = None
        if isinstance(score, (int, float)) and m > 0:
            p = min(1.0, max(0.0, float(score)))
            half = 1.96 * math.sqrt(p * (1 - p) / m)
            low, high = max(0.0, p - half), min(1.0, p + half)
            if inverted:
                p, low, high = 1 - p, 1 - high, 1 - low
            value, lo_v, hi_v = round(p * 100, 1), round(low * 100, 1), round(high * 100, 1)
        letter = hi if (MIDPOINT if value is None else value) >= MIDPOINT else lo
        direction = DIRECTION[name].get(axis.get("direction") or "")
        settled = value is not None
        out.append({"axis": key, "profile_axis": name, "direction": direction,
                    "letter": letter, "name": hi_name if letter == hi else lo_name
                    if letter == lo else None, "value": value, "lo": lo_v, "hi": hi_v,
                    "strong": None if value is None else round(max(value, 100 - value)),
                    "n_units": n, "settled": settled})
    return out


def code_of(axes: list[dict]) -> str:
    return "".join(a["letter"] for a in axes)


def gate(axes: list[dict], active_days: int | None) -> dict:
    rows = [{"axis": a["axis"], "n_units": a["n_units"]} for a in axes]
    # No sample threshold: any axis with a value is enough to give a type.
    passed = any(a["value"] is not None for a in axes)
    return {"min_units": MIN_UNITS, "min_active_days": MIN_ACTIVE_DAYS, "axes": rows,
            "active_days": active_days, "passed": passed}


def reason_for(profile: dict | None, gate_: dict, code: str) -> str | None:
    if profile is None:
        return "persona_unavailable"
    if not gate_["passed"]:
        return "insufficient_data"
    if "?" in code:
        return "unsettled_code"
    return None


def matches(axes: list[dict], code: str | None = None, types: dict | None = None,
            limit: int = 6) -> list[dict]:
    """Closest of the 16 types: similarity = 1 − mean(|value − pole|)/100 over the axes
    with a value (pole 100 for the axis' high letter, 0 for the low one). A fully settled
    ``code`` is listed first."""
    known = [(i, a["value"]) for i, a in enumerate(axes) if a["value"] is not None]
    if not known:
        return []
    types = types if types is not None else type_table()
    highs = [spec[2] for spec in UI_AXES]
    rows = []
    for candidate in all_codes():
        distance = sum(abs(value - (100 if candidate[i] == highs[i] else 0))
                       for i, value in known) / len(known)
        zh, en, _ = types.get(candidate, (None, None, None))
        rows.append({"code": candidate, "zh": zh, "en": en,
                     "similarity": round(1 - distance / 100, 3)})
    rows.sort(key=lambda r: (-r["similarity"], r["code"]))
    if code and "?" not in code:
        rows.sort(key=lambda r: r["code"] != code)  # Stable: winner first, rest unchanged.
    return rows[:limit]


def _hours(rhythm: dict | None) -> tuple[list[int] | None, list[list[int]] | None]:
    sessions = (rhythm or {}).get("sessions") or {}
    by_hour = sessions.get("by_hour")
    by_wh = sessions.get("by_weekday_hour")
    hours = None if by_hour is None else [int(by_hour.get(str(h), 0)) for h in range(24)]
    grid = None
    if by_wh is not None:
        grid = [[0] * 24 for _ in range(7)]
        for key, n in by_wh.items():
            weekday, _, hour = str(key).partition(":")
            if weekday.isdigit() and hour.isdigit() and 1 <= int(weekday) <= 7:
                grid[int(weekday) - 1][int(hour) % 24] += int(n)
    return hours, grid


def fingerprint(overview_body: dict | None, span: tuple[int | None, int | None]) -> dict | None:
    overview = (overview_body or {}).get("overview") or {}
    rhythm = overview.get("activity_rhythm")
    if rhythm is None:
        return None
    hours, grid = _hours(rhythm)
    sessions = (overview.get("counts") or {}).get("main_sessions")
    return {"sessions": sessions, "by_hour": hours, "by_weekday_hour": grid,
            "first_ts": span[0], "last_ts": span[1]}


def facts(overview_body: dict | None, extra: dict | None = None) -> list[dict]:
    """Reveal "how we got here" lines; values stay None when unknown (never 0)."""
    overview = (overview_body or {}).get("overview") or {}
    counts = overview.get("counts") or {}
    rhythm = overview.get("activity_rhythm") or {}
    hours, _ = _hours(rhythm)
    extra = extra or {}
    peak = None if not hours or not any(hours) else max(range(24), key=lambda h: hours[h])
    shares = extra.get("agent_hours") or {}
    total = sum(shares.values())
    share_text = " · ".join(f"{agent} {round(v / total * 100)}%" for agent, v in
                            sorted(shares.items(), key=lambda x: -x[1])) if total else None
    friction = extra.get("top_error_class")
    verify = extra.get("verification_share")
    return [
        {"stage": "sessions", "label": "会话", "value": counts.get("main_sessions"),
         "detail": f"{rhythm.get('active_days')} 个活跃日" if rhythm.get("active_days")
         is not None else None},
        {"stage": "tools", "label": "工具调用",
         "value": (overview_body or {}).get("effective_samples", {}).get("tools"),
         "detail": None},
        {"stage": "rhythm", "label": "峰值小时", "value": peak,
         "detail": None if peak is None else f"{peak}:00–{peak + 1}:00 开始的会话最多"},
        {"stage": "agents", "label": "各 Agent 时长占比", "value": share_text,
         "detail": "按会话日志跨度，不是实际工作时长"},
        {"stage": "friction", "label": "最常见摩擦", "value": friction and friction["class"],
         "detail": friction and f"{friction['n']} 次工具失败"},
        {"stage": "verification", "label": "验证占比",
         "value": None if verify is None else round(verify, 3),
         "detail": "运行过测试/构建命令的会话占比"},
    ]


def method(profile: dict | None) -> dict:
    from ..analytics.presentation.profile import PROFILE_VERSION

    return {"rules_version": (profile or {}).get("method_version") or PROFILE_VERSION,
            "axes": [{"axis": key, "signal": SIGNALS[name], "unit": "task"}
                     for key, name, *_ in UI_AXES],
            "thresholds": {"min_units": MIN_UNITS, "min_active_days": MIN_ACTIVE_DAYS,
                           "midpoint": MIDPOINT}}


def compose(profile: dict | None, overview_body: dict | None, *, reason: str | None = None,
            span=(None, None), extra: dict | None = None, types: dict | None = None,
            meta: dict | None = None) -> dict:
    """Reveal payload from a build_profile-shaped dict (None: no profile)."""
    types = types if types is not None else type_table()
    axes = ui_axes(profile)
    rhythm = ((overview_body or {}).get("overview") or {}).get("activity_rhythm") or {}
    gate_ = gate(axes, rhythm.get("active_days"))
    code = code_of(axes)
    reason = reason or reason_for(profile, gate_, code)
    entry = types.get(code) if "?" not in code else None
    return {
        "ok": reason is None, "reason": reason, "gate": gate_,
        "code": code if profile is not None else None,
        "type": {"code": code, "zh": entry[0], "en": entry[1], "line": entry[2]}
        if entry else None,
        "axes": [{k: v for k, v in a.items() if k != "profile_axis"} for a in axes],
        "fingerprint": fingerprint(overview_body, span),
        "matches": matches(axes, code, types) if profile is not None else [],
        "facts": facts(overview_body, extra), "method": method(profile),
        "share": {"allowed": reason is None, "blocked_reason": reason},
        "meta": meta or {},
    }


# -- loaders (gateway) -------------------------------------------------------------------
def _bodies(gw, scope_dict: dict, submit: bool):
    bodies, worst, pending = {}, "fresh", []
    order = {"fresh": 0, "stale": 1, "missing": 2, "none": 3}
    for name in PERSONA_SECTIONS:
        body, freshness, key = cached_section(gw, name, scope_dict)
        bodies[name] = body
        worst = max(worst, freshness, key=order.get)
        if body is None and submit and freshness == "missing":
            task = submit_section(gw, name, scope_dict, key)
            if task:
                pending.append(task)
    return bodies, worst, pending


def _profile(bodies: dict):
    exp = _export()
    if exp is None:
        return None, "persona_unavailable"
    if any(bodies.get(name) is None for name in PERSONA_SECTIONS):
        return None, "computing"
    try:
        profile = exp[0].persona_profile(bodies)
    except Exception:  # noqa: BLE001 - a malformed snapshot reads as unavailable.
        return None, "persona_unavailable"
    return profile, None if profile is not None else "persona_unavailable"


def _sql_extra(gw, scope_dict: dict) -> tuple[tuple, dict]:
    """First/last session start, per-agent hours, top error class and verification share
    within the scope window (analysed main sessions only)."""
    from . import main_where

    if not has_db(gw):
        return (None, None), {}
    where, args = main_where(gw)
    if scope_dict.get("from_ts") is not None:
        where += " AND s.started_at >= ?"
        args.append(scope_dict["from_ts"])
    if scope_dict.get("until_ts") is not None:
        where += " AND s.started_at < ?"
        args.append(scope_dict["until_ts"])
    if scope_dict.get("source_ids"):
        where += f" AND s.source_id IN ({','.join('?' * len(scope_dict['source_ids']))})"
        args += list(scope_dict["source_ids"])
    try:
        with reader(gw)() as db:
            first, last = db.execute(f"SELECT MIN(started_at), MAX(started_at) FROM session s "
                                     f"WHERE {where}", args).fetchone()
            agent_hours = {r[0] or "other": (r[1] or 0) / 3_600_000 for r in db.execute(
                f"SELECT src.agent, SUM(MAX(COALESCE(s.ended_at, s.started_at) - s.started_at,"
                f" 0)) FROM session s LEFT JOIN source src USING(source_id) WHERE {where} "
                f"GROUP BY src.agent", args)}
            row = db.execute(
                f"SELECT error_class, COUNT(*) n FROM tool_call WHERE error_class IS NOT NULL "
                f"AND session_uid IN (SELECT s.session_uid FROM session s WHERE {where}) "
                f"GROUP BY error_class ORDER BY n DESC, error_class LIMIT 1", args).fetchone()
            tests = " OR ".join(f"t.command_head LIKE '{p}%'" for p in VERIFY_HEADS)
            total, verified = db.execute(
                f"SELECT COUNT(*), SUM(EXISTS(SELECT 1 FROM tool_call t WHERE "
                f"t.session_uid = s.session_uid AND ({tests}))) FROM session s WHERE {where}",
                args).fetchone()
    except Exception:  # noqa: BLE001 - facts degrade to unknown, the reveal still renders.
        return (None, None), {}
    return (first, last), {
        "agent_hours": {k: v for k, v in agent_hours.items() if v > 0},
        "top_error_class": {"class": row[0], "n": row[1]} if row else None,
        "verification_share": (verified or 0) / total if total else None}


VERIFY_HEADS = ("pytest", "npm test", "pnpm test", "yarn test", "npx jest", "npx vitest",
                "cargo test", "go test", "swift test", "make test", "xcodebuild test",
                "uv run pytest", "python -m pytest", "npm run test", "pnpm check")


def load(gw, scope_dict: dict, *, submit: bool = True) -> dict:
    """GET /v1/shell/reveal body for ``scope_dict``; submits missing sections once."""
    from ..services.snapshots import scope_hash

    h = scope_hash(scope_dict, {})
    if _export() is None:
        return compose(None, None, reason="persona_unavailable",
                       meta={"scope_hash": h, "freshness": "none"})
    bodies, freshness, pending = _bodies(gw, scope_dict, submit)
    profile, why = _profile(bodies)
    span, extra = _sql_extra(gw, scope_dict)
    meta = {"scope_hash": h, "freshness": freshness, "job_ids": pending}
    if why == "computing" and freshness == "none":
        why = "insufficient_data"  # Nothing imported yet: no data rather than "computing".
    return compose(profile, bodies.get("overview"), reason=why, span=span, extra=extra,
                   meta=meta)


def persona_summary(gw, scope_dict: dict | None = None) -> dict:
    """{ok, code, name_zh, reason, gate} from cached snapshots only (never computes)."""
    scope_dict = scope_dict or default_scope(gw)
    if _export() is None:
        return {"ok": False, "code": None, "name_zh": None, "reason": "persona_unavailable",
                "gate": None}
    bodies, freshness, _ = _bodies(gw, scope_dict, submit=False)
    profile, why = _profile(bodies)
    if why == "computing" and freshness == "none":
        why = "insufficient_data"
    payload = compose(profile, bodies.get("overview"), reason=why)
    return {"ok": payload["ok"], "code": payload["code"],
            "name_zh": (payload["type"] or {}).get("zh"), "reason": payload["reason"],
            "gate": payload["gate"]}
