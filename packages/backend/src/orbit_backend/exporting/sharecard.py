"""Share-card payload (EXP-03/04): experimental persona with a hard sample-size gate.

The card reads the A2 persona (``/v1/uiview/persona`` payload, ``uiview-persona-v0``), so the
card and the page always show the same code, axis values and copy. One card per time span:
``span`` names it (7 → 周卡, 30 → 月卡, 90 → 季卡, all → 全时卡, a calendar month → N 月卡), and
the persona inside is the one computed for that window, so different spans can give different
types. Gate: the persona is ``ok`` (≥ 1 session; the
page always gives a full four-letter code, so ``unsettled_code`` only guards legacy payloads).
Rendering (PNG/SVG) belongs to the frontend.

``persona_profile`` / ``gate`` / ``blocked_reason`` remain for the report's persona section
(``presentation.profile`` four axes).
"""

from __future__ import annotations

import time

from .type_copy import copy_for

MIN_UNITS, MIN_ACTIVE_DAYS = 30, 10
DISCLAIMER = "实验性画像，仅供参考"
PERSONA_SECTIONS = ("tasks", "instruction", "preferences", "overview")


def persona_profile(bodies: dict[str, dict | None]) -> dict | None:
    """Profile from section bodies, or None when any input section is missing."""
    from ..analytics.presentation.profile import build_profile

    tasks, instruction, preferences = (bodies.get(k) for k in PERSONA_SECTIONS[:3])
    if not (tasks and instruction and preferences):
        return None
    return build_profile({"scope": tasks.get("scope") or {}, "tasks": tasks.get("tasks") or {},
                          "instruction": instruction.get("instruction") or {},
                          "preferences": preferences.get("preferences") or {},
                          "sessions": [], "coverage": tasks.get("coverage") or {}})


def active_days(overview_body: dict | None) -> int | None:
    rhythm = ((overview_body or {}).get("overview") or {}).get("activity_rhythm") or {}
    return rhythm.get("active_days")


def persona_code(profile: dict) -> str:
    return "".join(axis.get("direction") or "?" for axis in profile["axes"].values())


def gate(profile: dict | None, days: int | None) -> dict:
    axes = [{"axis": key, "n_units": axis.get("effective_task_n") or 0}
            for key, axis in ((profile or {}).get("axes") or {}).items()]
    passed = bool(axes) and all(a["n_units"] >= MIN_UNITS for a in axes) \
        and (days or 0) >= MIN_ACTIVE_DAYS
    return {"min_units": MIN_UNITS, "min_active_days": MIN_ACTIVE_DAYS, "axes": axes,
            "active_days": days, "passed": passed}


def blocked_reason(profile: dict | None, gate_: dict) -> str | None:
    if profile is None:
        return "persona_unavailable"
    if not gate_["passed"]:
        return "insufficient_data"
    if "?" in persona_code(profile):
        return "unsettled_code"
    return None


def card_gate(p: dict | None) -> dict:
    from ..uiview import persona

    axes = [{"axis": a["k"], "n_units": a["n_units"], "state": a["state"]}
            for a in (p or {}).get("axes") or []]
    return {"min_units": dict(persona.MIN_UNITS), "min_active_days": persona.MIN_DAYS,
            "min_sessions": persona.MIN_SESSIONS, "axes": axes,
            "sessions": (p or {}).get("n"), "active_days": (p or {}).get("days")}


def card_reason(p: dict | None, gate_: dict) -> str | None:
    if p is None:
        return "persona_unavailable"
    if not p.get("ok") or any(a["state"] == "insufficient" for a in gate_["axes"]):
        return "insufficient_data"
    if not p.get("code") or "?" in p["code"]:
        return "unsettled_code"
    return None


SPANS = {"7": ("week", "周卡", "WEEKLY"), "30": ("month", "月卡", "MONTHLY"),
         "90": ("quarter", "季卡", "QUARTERLY"), "all": ("all", "全时卡", "ALL TIME")}


def span(period: str | None, label: str | None) -> dict:
    """Which card this is: the time span's kind and its tag (周卡 / 月卡 / 季卡 / 全时卡 / N 月卡)."""
    period = period or "90"
    if period in SPANS:
        kind, tag, tag_en = SPANS[period]
    elif period.isdigit():
        kind, tag, tag_en = "days", f"{period} 天卡", f"{period} DAYS"
    else:
        month = (label or period)[-2:]
        kind, tag = "calendar", (f"{int(month)} 月卡" if month.isdigit() else "月卡")
        tag_en = "MONTH"
    return {"key": period, "kind": kind, "label": label, "tag": tag, "tag_en": tag_en,
            "days": int(period) if period.isdigit() else None}


def stats(p: dict, hide_numbers: bool) -> list[dict]:
    turns = next((a["n_units"] for a in p.get("axes") or [] if a["k"] == "D"), None)
    rows = [("会话", p.get("n"), "个"), ("活跃天数", p.get("days"), "天"),
            ("Agent", p.get("agents_n"), "个"), ("对话轮次", turns, "轮")]
    return [{"label": label, "value": None if hide_numbers else value, "unit": unit,
             "hidden": hide_numbers} for label, value, unit in rows]


def payload(p: dict | None, *, hide_numbers: bool = False, theme: str = "system") -> dict:
    """Card from a ``uiview.persona.page`` payload (``None`` when the facts are missing)."""
    gate_ = card_gate(p)
    reason = card_reason(p, gate_)
    eligible = reason is None
    code = p["code"] if eligible else None
    type_name, copy = copy_for(code)
    axes = [{k: a.get(k) for k in ("k", "value", "letter", "strong", "left", "right", "state")}
            for a in p["axes"]] if eligible else []
    if hide_numbers:
        for a in axes:
            a["strong"] = None
    meta = (p or {}).get("meta") or {}
    return {"eligible": eligible, "blocked_reason": reason, "gate": gate_,
            "code": code, "type_name": type_name or (p["zh"] if eligible else None),
            "copy": copy if eligible else None, "axes": axes,
            "v": dict(p.get("v") or {a["k"]: a["value"] for a in p["axes"]}) if eligible else None,
            "period": meta.get("period"), "period_label": meta.get("period_label"),
            "window": meta.get("window"), "span": span(meta.get("period"), meta.get("period_label")),
            "method": meta.get("method"),
            "stats": stats(p, hide_numbers) if eligible else [],
            "theme": theme, "disclaimer": DISCLAIMER, "generated_at": int(time.time() * 1000)}
