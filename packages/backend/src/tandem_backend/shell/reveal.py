"""Persona reveal payload (OB-05/OB-06, REV-01/REV-02, SET-19, HLP-03) and the short
persona summary shared by the popover, widgets and onboarding (POP-08, WG-02).

The persona is the A2 one (``uiview.persona.page``, ``uiview-persona-v0``) over the cached
``uiview_facts`` snapshot, requested through ``exporting.sharecard.persona_request`` — the
same payload the persona page, the share card and the report read, so every surface shows
the same code. Rule (main ebdc750e): one session is enough for a full four-letter code;
value ≥ 50 → the high letter (D / I / M / V), < 50 → the low letter (S / P / F / T); an axis
without units counts as 50 and is reported with ``value = None``. Only no persona (no
session in the window) or four axes without any value block the reveal.

Intervals are the persona's own Wilson 95% bounds (session-clustered for D / V, see
``uiview.persona``); nothing is recomputed here.
"""

from __future__ import annotations

from . import cached_section, default_scope, has_db, reader, submit_section

FACTS_SECTION = "uiview_facts"
OVERVIEW_SECTIONS = ("overview",)  # fingerprint / facts lines only
REASON_TEXT = {"persona_unavailable": "画像模块不可用", "insufficient_data": "样本不足",
               "unsettled_code": "有维度尚未定型", "computing": "正在计算"}


# -- pure composition (tests feed real ``uiview.persona.page`` payloads) --------------------
def ui_axes(page: dict | None) -> list[dict]:
    """Persona page axes → reveal axes (value / lo / hi on 0..100, letter, settled)."""
    out = []
    for a in (page or {}).get("axes") or []:
        known = a["value"] is not None
        left, right = a["left"], a["right"]
        # left/right read "D 委托" / "掌舵 S": the name is the word next to the letter.
        names = {left.split()[0]: left.split()[-1], right.split()[-1]: right.split()[0]}
        out.append({"axis": a["k"], "direction": a["letter"] if known else None,
                    "letter": a["letter"], "name": names.get(a["letter"]),
                    "value": a["value"], "lo": a["lo"] if known else None,
                    "hi": a["hi"] if known else None, "strong": a["strong"],
                    "n_units": a["n_units"], "unit": a["unit"], "decided": a["decided"],
                    "settled": known})
    return out


def code_of(axes: list[dict]) -> str:
    return "".join(a["letter"] for a in axes)


def gate(page: dict | None, axes: list[dict]) -> dict:
    from ..exporting import sharecard

    g = sharecard.card_gate(page)
    # Only four axes without any value block the code (main rule); no sample threshold.
    return {**g, "passed": bool((page or {}).get("ok"))
            and any(a["value"] is not None for a in axes)}


def reason_for(page: dict | None, gate_: dict) -> str | None:
    """The share card's reason (``sharecard.card_reason``: the page's ``ok`` / code) plus
    the reveal's own rule that four axes without any value block it."""
    from ..exporting import sharecard

    reason = sharecard.card_reason(page, gate_)
    if reason is None and not gate_["passed"]:
        return "insufficient_data"
    return reason


def matches(page: dict | None, limit: int = 6) -> list[dict]:
    """Closest of the 16 types: ``uiview.persona.candidates`` (an axis without units counts
    as 50, the persona's own code first on ties); ``similarity`` = match / 100."""
    from ..uiview import persona

    if not page or not page.get("ok"):
        return []
    rows = persona.candidates({"ok": True, "code": page["code"], "v": page["v"]}, limit)
    return [{"code": r["code"], "zh": r["zh"], "en": r["en"], "match": r["match"],
             "similarity": round(r["match"] / 100, 3)} for r in rows]


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


def method() -> dict:
    from ..uiview import persona

    return {"rules_version": persona.METHOD,
            "axes": [{"axis": k, "signal": persona.SIG_USED[k], "unit": persona.UNITS[k]}
                     for k in "DIMV"],
            "thresholds": {"min_sessions": persona.MIN_SESSIONS,
                           "midpoint": persona.MIDPOINT, "band": list(persona.CONFIG["band"]),
                           "soft_sessions": persona.SOFT_SESSIONS}}


def compose(page: dict | None, overview_body: dict | None, *, reason: str | None = None,
            span=(None, None), extra: dict | None = None, meta: dict | None = None) -> dict:
    """Reveal payload from a ``uiview.persona.page`` payload (None: no persona)."""
    axes = ui_axes(page)
    gate_ = gate(page, axes)
    code = code_of(axes) if axes else None
    reason = reason or reason_for(page, gate_)
    ok = reason is None
    return {
        "ok": ok, "reason": reason, "gate": gate_,
        "code": code if page is not None and page.get("ok") else None,
        "type": {"code": code, "zh": page["zh"], "en": page["en"], "line": page["line"]}
        if ok and page.get("classified") else None,
        "conf": (page or {}).get("conf"), "hint": (page or {}).get("hint"),
        "axes": axes, "fingerprint": fingerprint(overview_body, span),
        "matches": matches(page), "facts": facts(overview_body, extra), "method": method(),
        "share": {"allowed": ok, "blocked_reason": reason},
        "meta": meta or {},
    }


# -- loaders (gateway) -------------------------------------------------------------------
def _overview(gw, scope_dict: dict, submit: bool):
    """(overview body | None, job ids) for the fingerprint and fact lines."""
    body, freshness, key = cached_section(gw, "overview", scope_dict)
    pending = []
    if body is None and submit and freshness == "missing":
        task = submit_section(gw, "overview", scope_dict, key)
        if task:
            pending.append(task)
    return body, pending


def _page(gw, scope_dict: dict, submit: bool):
    """(persona page | None, freshness, reason, notes). ``submit`` enqueues the facts pass
    when missing (``uiview.fetch``); without it only cached snapshots are read."""
    from ..exporting import sharecard
    from ..uiview import facts, fetch, overview, persona

    facts_scope, params, notes = sharecard.persona_request(scope_dict)
    today = overview.today_in(scope_dict.get("display_timezone"))
    try:
        if submit:
            page, freshness, _ = fetch.persona_page(gw, facts_scope, params, today)
            body = None
        else:
            body, freshness, _ = cached_section(gw, FACTS_SECTION, facts_scope)
            page = None
            if body is not None:
                realtime = getattr(gw, "realtime", None)
                body = facts.overlay_live(body, realtime.latest() if realtime else None)
                page = persona.page(body, params, today)
    except Exception:  # noqa: BLE001 - a failed or malformed facts pass reads as unavailable.
        return None, "failed", "persona_unavailable", notes
    if page is None:
        # Nothing imported yet: no data rather than "computing".
        why = "insufficient_data" if freshness == "none" else "computing"
        return None, freshness, why, notes
    return page, freshness, None, notes


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
    page, freshness, why, notes = _page(gw, scope_dict, submit)
    overview_body, pending = _overview(gw, scope_dict, submit)
    span, extra = _sql_extra(gw, scope_dict)
    meta = {"scope_hash": h, "freshness": freshness, "job_ids": pending,
            "persona_scope": (page or {}).get("meta", {}).get("scope_hash"), "notes": notes}
    return compose(page, overview_body, reason=why, span=span, extra=extra, meta=meta)


def persona_summary(gw, scope_dict: dict | None = None) -> dict:
    """{ok, code, name_zh, reason, gate} from cached snapshots only (never computes)."""
    scope_dict = scope_dict or default_scope(gw)
    page, _, why, _ = _page(gw, scope_dict, submit=False)
    payload = compose(page, None, reason=why)
    return {"ok": payload["ok"], "code": payload["code"],
            "name_zh": (payload["type"] or {}).get("zh"), "reason": payload["reason"],
            "gate": payload["gate"]}
