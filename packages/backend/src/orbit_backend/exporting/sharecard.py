"""Share-card payload (EXP-03/04) and the persona request shared by the report and the reveal.

The card, the report's persona section and ``/v1/shell/reveal`` all read the A2 persona
(``uiview.persona.page``, ``uiview-persona-v1``), so every surface shows the same code, axis values
and copy under the same rule: one session is enough for a full four-letter code (value ≥ 50 → high
letter, an axis without units counts as 50); only no persona at all (no session in the window)
blocks it. ``unsettled_code`` only guards legacy payloads. One card per time span: ``span`` names
it (7 → 周卡, 30 → 月卡, 90 → 季卡, all → 全时卡, a calendar month → N 月卡), and the persona inside
is the one computed for that window, so different spans can give different types. Rendering
(PNG/SVG) belongs to the frontend.
"""

from __future__ import annotations

import math
import time

from .type_copy import copy_for

DISCLAIMER = "实验性画像，仅供参考"
DAY_MS = 86_400_000
# Fact windows the gateway prewarms (``services.fastpath.LADDER``): a request is served from
# the smallest one that covers it, so the reveal and the report reuse the page's snapshot.
FACT_WINDOWS = (7, 30)


def window_days(scope: dict, now_ms: int | None = None) -> int:
    """Whole days from ``scope['from_ts']`` to now (0 = no lower bound, i.e. all time)."""
    from_ts = scope.get("from_ts")
    if from_ts is None:
        return 0
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    return max(1, math.ceil((now - from_ts) / DAY_MS))


def persona_request(scope: dict, now_ms: int | None = None) -> tuple[dict, dict, list[str]]:
    """(uiview facts scope, ``persona.page`` params, notes) for an analytics scope dict.

    The persona's period counts days back from today, so ``from_ts`` becomes ``period``
    and ``until_ts`` is not applied; one ``project_ids`` entry becomes the page's project
    filter, several are not applied. ``notes`` names every part of the scope left out.
    """
    from ..services.fastpath import windowed
    from ..uiview import fetch

    days = window_days(scope, now_ms)
    base = fetch.default_scope(scope.get("display_timezone"))
    if scope.get("excluded_session_uids") is not None:
        base["excluded_session_uids"] = list(scope["excluded_session_uids"])
    window = next((w for w in FACT_WINDOWS if days and days <= w), 0)
    projects = scope.get("project_ids") or []
    params = {"period": str(days) if days else "all", "agents": None,
              "project": projects[0] if len(projects) == 1 else None, "vs": None}
    notes = []
    if scope.get("until_ts") is not None:
        notes.append("画像按起始日至今统计，未应用结束时间")
    if len(projects) > 1:
        notes.append("画像不支持多个项目筛选，按全部项目统计")
    return windowed(base, window), params, notes


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
