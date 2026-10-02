"""Share-card payload (EXP-03/04): experimental persona with a hard sample-size gate.

The persona is ``analytics.presentation.profile.build_profile`` over the same tasks /
instruction / preferences snapshots the pages read; ``n_units`` per axis is the profile's
``effective_task_n``. Gate: every axis ≥ 30 units and ≥ 10 active days, and every axis
settled (no ``?`` in the code). Rendering (PNG/SVG) belongs to the frontend.
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


def stats(overview_body: dict | None, profile: dict | None, days: int | None,
          hide_numbers: bool) -> list[dict]:
    counts = ((overview_body or {}).get("overview") or {}).get("counts") or {}
    rows = [("会话", counts.get("main_sessions"), "个"), ("活跃天数", days, "天"),
            ("任务", ((profile or {}).get("coverage") or {}).get("task_n"), "个")]
    return [{"label": label, "value": None if hide_numbers else value, "unit": unit,
             "hidden": hide_numbers} for label, value, unit in rows]


def payload(bodies: dict[str, dict | None], *, hide_numbers: bool = False,
            theme: str = "system") -> dict:
    profile = persona_profile(bodies)
    days = active_days(bodies.get("overview"))
    gate_ = gate(profile, days)
    reason = blocked_reason(profile, gate_)
    eligible = reason is None
    code = persona_code(profile) if eligible else None
    type_name, copy = copy_for(code)
    return {"eligible": eligible, "blocked_reason": reason,
            "gate": {k: v for k, v in gate_.items() if k != "passed"},
            "code": code, "type_name": type_name, "copy": copy if eligible else None,
            "stats": stats(bodies.get("overview"), profile, days, hide_numbers) if eligible else [],
            "theme": theme, "disclaimer": DISCLAIMER, "generated_at": int(time.time() * 1000)}
