"""Report assembly (EXP-01 / FE-19): every number comes from the analytics section snapshots
the pages read for the same scope, so report and page agree (EV-01.2).

Sections are looked up like ``routes_analytics.serve``: exact snapshot, else one interactive
job per missing section with a shared wait (≤ 3 s), else the previous revision (stale), else
``computing``. Nothing is recomputed here and missing numbers are never defaulted to 0.
Narrative text is a fixed template; insufficient samples print 样本不足.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from . import sharecard

SECTION_IDS = ("overview", "metrics", "persona", "projects", "friction", "recommendations",
               "tools")
DEFAULT_SECTIONS = tuple(s for s in SECTION_IDS if s != "persona")
TITLES = {"overview": "概览", "metrics": "核心指标", "persona": "协作画像（实验性）",
          "projects": "项目", "friction": "摩擦", "recommendations": "推荐", "tools": "工具"}
NEEDS = {"overview": ("overview",), "metrics": ("overview",), "tools": ("tools",),
         "projects": ("projects",), "friction": ("overview", "tools"),
         "persona": sharecard.PERSONA_SECTIONS, "recommendations": ()}
BASIS = {"overview": "analytics.overview 快照（与总览页同口径）",
         "metrics": "analytics.overview 快照 counts / usage",
         "tools": "analytics.tools 快照（已知状态的调用为分母）",
         "projects": "analytics.projects 快照",
         "friction": "analytics.tools totals + overview 纠偏信号",
         "persona": "presentation.profile 四轴（每轴有效任务数），实验性",
         "recommendations": "recommend 最新一次运行（标题与状态）"}
MIN_SESSIONS = 5
INSUFFICIENT = "样本不足"
BRAND = "Orbit"  # Product name on user-visible exports; package, env and data paths keep "orbit".
SCOPE_KEYS = ("display_timezone", "project_ids", "from_ts", "until_ts", "model_ids",
              "source_ids", "excluded_session_uids")


# -- scope & section lookup --------------------------------------------------------------
def build_scope(raw: dict) -> dict:
    """Validated analytics Scope as a dict (same normalisation as the analytics routes)."""
    from dataclasses import asdict

    from ..services.routes_analytics import analytics_scope

    unknown = set(raw) - set(SCOPE_KEYS)
    if unknown:
        raise ValueError(f"Unknown scope keys: {sorted(unknown)}")
    return asdict(analytics_scope(**raw))


def fetch_sections(gw, names, scope_dict: dict, wait_ms: int = 3000) -> tuple[dict, str]:
    """{section: (body | None, freshness)} with freshness fresh|stale|computing|failed|none."""
    from ..services.sections import rules_digest
    from ..services.snapshots import SnapshotKey, scope_hash

    h = scope_hash(scope_dict, {})
    rev = gw.revisions.snapshot()
    if rev["data_rev"] is None:
        return {name: (None, "none") for name in names}, h
    rules = rules_digest()
    revision = (rev["data_rev"], rev["inventory_rev"])
    out, pending = {}, {}
    for name in dict.fromkeys(names):
        key = SnapshotKey(name, h, *revision, rules)
        snapshot = gw.snapshots.get(key)
        if snapshot is not None:
            out[name] = (snapshot.body, "fresh")
            continue
        pending[name] = (key, gw.supervisor.analysis.submit(
            name, scope_dict, {}, h, "interactive", revision, rules))
    deadline = time.monotonic() + wait_ms / 1000
    for name, (key, task) in pending.items():
        if task is not None:
            task.done.wait(max(0.0, deadline - time.monotonic()))
            if task.status == "completed" and (snapshot := gw.snapshots.get(key)) is not None:
                out[name] = (snapshot.body, "fresh")
                continue
        old = gw.snapshots.latest(name, h, rules)
        if old is not None:
            out[name] = (old.body, "stale")
        else:
            failed = task is None or task.status == "failed"
            out[name] = (None, "failed" if failed else "computing")
    return out, h


# -- per-section data ----------------------------------------------------------------------
def _overview(body):
    return (body or {}).get("overview") or {}


def _coverage(body) -> dict:
    coverage = (body or {}).get("coverage") or {}
    return {k: v.get("status") for k, v in coverage.items() if isinstance(v, dict)}


def _overview_data(bodies):
    view = _overview(bodies["overview"])
    counts, usage = view.get("counts") or {}, view.get("usage") or {}
    return counts.get("main_sessions"), {
        "main_sessions": counts.get("main_sessions"), "sessions": counts.get("sessions"),
        "human_messages": counts.get("human_messages"), "turns": counts.get("turns"),
        "active_days": sharecard.active_days(bodies["overview"]),
        "request_count": usage.get("request_count"), "total_tokens": usage.get("total_tokens"),
        "cost_usd": usage.get("cost_usd"),
        "top_tools": [{"name": t.get("name_raw"), "calls": t.get("call_count")}
                      for t in (view.get("top_tools") or [])[:5]]}


METRICS = (("sessions", "会话", "个"), ("main_sessions", "主会话", "个"),
           ("human_messages", "人工消息", "条"), ("turns", "轮次", "轮"),
           ("correction_signals", "纠偏信号", "次"), ("correction_signal_rate", "纠偏率", "%"),
           ("request_count", "模型请求", "次"), ("total_tokens", "Token", "tok"),
           ("cost_usd", "成本", "USD"), ("active_days", "活跃天数", "天"))


def _metrics_data(bodies):
    view = _overview(bodies["overview"])
    values = {**(view.get("counts") or {}), **(view.get("usage") or {}),
              "active_days": sharecard.active_days(bodies["overview"])}
    rows = [{"id": key, "label": label, "value": values.get(key), "unit": unit}
            for key, label, unit in METRICS]
    return (view.get("counts") or {}).get("main_sessions"), {"rows": rows}


TOOL_FIELDS = ("call_count", "known_failure_count", "success_rate", "failure_rate",
               "median_duration_ms")


def _tools_data(bodies):
    tools = (bodies["tools"] or {}).get("tools") or {}
    totals = tools.get("totals") or {}
    rows = [{"name": t.get("name_raw"), "kind": t.get("kind"), **{k: t.get(k) for k in TOOL_FIELDS}}
            for t in (tools.get("by_tool") or [])[:15]]
    return tools.get("effective_n"), {"totals": {k: totals.get(k) for k in TOOL_FIELDS},
                                      "rows": rows}


def _projects_data(bodies):
    from ..ai.redact import redact2

    projects = (bodies["projects"] or {}).get("projects")
    if projects is None:
        return None, None
    rows = [{"project": redact2(p.get("name") or p.get("legacy_project_id")
                                or p.get("project_id") or "")[0] or None,
             "project_id": p.get("project_id"), "session_count": p.get("session_count"),
             "main_session_count": p.get("main_session_count"),
             "human_message_count": p.get("human_message_count"),
             "total_tokens": (p.get("usage") or {}).get("total_tokens")}
            for p in sorted(projects, key=lambda p: -(p.get("session_count") or 0))[:20]]
    return len(projects), {"project_count": len(projects), "rows": rows}


def _friction_data(bodies):
    counts = _overview(bodies["overview"]).get("counts") or {}
    totals = ((bodies["tools"] or {}).get("tools") or {}).get("totals") or {}
    return ((bodies["tools"] or {}).get("tools") or {}).get("effective_n"), {
        "tool_failures": totals.get("known_failure_count"),
        "tool_failure_rate": totals.get("failure_rate"),
        "rejected": totals.get("rejected_count"), "interrupted": totals.get("interrupted_count"),
        "correction_signals": counts.get("correction_signals"),
        "correction_signal_rate": counts.get("correction_signal_rate")}


def _persona_data(bodies):
    profile = sharecard.persona_profile(bodies)
    gate = sharecard.gate(profile, sharecard.active_days(bodies["overview"]))
    n = min((a["n_units"] for a in gate["axes"]), default=None)
    reason = sharecard.blocked_reason(profile, gate)
    if reason is not None:  # Same gate as the share card: no persona below it.
        return n, None, reason
    from .type_copy import copy_for

    code = sharecard.persona_code(profile)
    return n, {"code": code, "type_name": copy_for(code)[0], "experimental": True,
               "label": "实验性", "headline": profile.get("headline"),
               "axes": [{"axis": k, "label": a.get("label"), "direction": a.get("direction"),
                         "n_units": a.get("effective_task_n")}
                        for k, a in profile["axes"].items()]}, None


def recommendations(appdb, scope_hash: str) -> dict | None:
    """Titles and status of the newest recommend run for this scope; None without one."""
    import sqlite3

    from ..ai.redact import redact2

    try:
        with appdb.read() as db:
            run = db.execute("SELECT run_id, created_at FROM rec_run WHERE scope_hash = ? "
                             "ORDER BY created_at DESC LIMIT 1", (scope_hash,)).fetchone()
            if run is None:
                return None
            rows = db.execute(
                "SELECT c.title, c.kind, st.status, (SELECT tr.effect_status FROM tracking tr "
                "WHERE tr.rec_key = c.rec_key ORDER BY tr.registered_at DESC LIMIT 1) "
                "FROM rec_candidate c LEFT JOIN rec_state st ON st.rec_key = c.rec_key "
                "WHERE c.run_id = ? AND c.passed = 1 ORDER BY c.rank LIMIT 10",
                (run[0],)).fetchall()
    except sqlite3.OperationalError:
        return None
    return {"run_id": run[0], "run_created_at": run[1], "items": [
        {"title": redact2(r[0])[0], "kind": r[1], "status": r[2] or "new",
         "effect_status": r[3] if r[3] not in (None, "tracking") else "未测"} for r in rows]}


# -- markdown --------------------------------------------------------------------------------
def fmt(value, unit: str | None = None) -> str:
    if value is None:
        return "未知"
    if unit == "%":
        return f"{value * 100:.1f}%"
    if unit == "USD":
        return f"${value:.2f}"
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(head: list[str], rows: list[list]) -> list[str]:
    return [f"| {' | '.join(head)} |", f"|{'---|' * len(head)}",
            *[f"| {' | '.join(fmt(c) for c in row)} |" for row in rows]]


def narrative(sid: str, data: dict) -> str:
    if sid in ("overview", "metrics"):
        values = data if sid == "overview" else {r["id"]: r["value"] for r in data["rows"]}
        return (f"范围内共 {fmt(values.get('main_sessions'))} 个主会话、"
                f"{fmt(values.get('human_messages'))} 条人工消息，活跃 {fmt(values.get('active_days'))} 天。")
    if sid == "tools":
        t = data["totals"]
        return f"共 {fmt(t['call_count'])} 次工具调用，已知状态中失败率 {fmt(t['failure_rate'], '%')}。"
    if sid == "projects":
        top = data["rows"][0]["project"] if data["rows"] else None
        return f"涉及 {data['project_count']} 个项目，会话最多的是 {fmt(top)}。"
    if sid == "friction":
        return (f"工具已知失败 {fmt(data['tool_failures'])} 次（{fmt(data['tool_failure_rate'], '%')}），"
                f"纠偏信号 {fmt(data['correction_signals'])} 次。")
    if sid == "persona":
        return f"实验性画像：{data['code']}「{data['type_name'] or '未收录类型'}」。{data['headline'] or ''}"
    if sid == "recommendations":
        return f"最新一次推荐共 {len(data['items'])} 条；没有效果数据的标为 未测。"
    return ""


def section_markdown(section: dict) -> str:
    sid, data, status = section["id"], section["data"], section["status"]
    out = [f"## {section['title']}", ""]
    if status == "computing":
        return "\n".join([*out, "计算中，暂无数字。"])
    if status == "unavailable":
        return "\n".join([*out, "暂不可用。"])
    if status == "insufficient":
        return "\n".join([*out, f"{INSUFFICIENT}（n = {fmt(section['n'])}），暂不下结论。"])
    out += [narrative(sid, data), ""]
    if sid == "metrics":
        out += table(["指标", "数值"], [[r["label"], fmt(r["value"], r["unit"])]
                                      for r in data["rows"]])
    elif sid == "tools":
        out += table(["工具", "调用", "失败", "失败率", "中位耗时 ms"],
                     [[r["name"], r["call_count"], r["known_failure_count"],
                       fmt(r["failure_rate"], "%"), r["median_duration_ms"]] for r in data["rows"]])
    elif sid == "projects":
        out += table(["项目", "会话", "主会话", "人工消息", "Token"],
                     [[r["project"], r["session_count"], r["main_session_count"],
                       r["human_message_count"], r["total_tokens"]] for r in data["rows"]])
    elif sid == "friction":
        out += table(["信号", "数值"], [["工具失败", data["tool_failures"]],
                                      ["工具失败率", fmt(data["tool_failure_rate"], "%")],
                                      ["被拒绝", data["rejected"]], ["被中断", data["interrupted"]],
                                      ["纠偏信号", data["correction_signals"]],
                                      ["纠偏率", fmt(data["correction_signal_rate"], "%")]])
    elif sid == "persona":
        out += table(["轴", "方向", "有效任务"], [[a["label"], a["direction"] or "?", a["n_units"]]
                                             for a in data["axes"]])
    elif sid == "recommendations" and data["items"]:
        out += table(["推荐", "类型", "状态", "效果"],
                     [[i["title"], i["kind"], i["status"], i["effect_status"]]
                      for i in data["items"]])
    return "\n".join(out).rstrip()


def _iso_day(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d") if ms is not None else "…"


def scope_line(scope: dict) -> str:
    projects = scope.get("project_ids")
    return (f"范围：{_iso_day(scope.get('from_ts'))} 至 {_iso_day(scope.get('until_ts'))}"
            f" · 时区 {scope.get('display_timezone') or 'UTC'}"
            f" · 项目 {'全部' if not projects else len(projects)}")


def document(report: dict) -> str:
    generated = datetime.fromtimestamp(report["generated_at"] / 1000, UTC).strftime(
        "%Y-%m-%d %H:%M UTC")
    parts = [f"# {BRAND} 协作报告", "", f"生成于 {generated}　{scope_line(report['scope'])}", ""]
    parts += [s["markdown"] + "\n" for s in report["sections"]]
    parts += ["## 口径与限制", ""]
    parts += table(["章节", "口径", "样本 n", "覆盖", "新鲜度", "状态"], [
        [s["title"], s["basis"], s["n"],
         ", ".join(f"{k}:{v}" for k, v in (s["coverage"] or {}).items()) or "—",
         s["freshness"], s["status"]] for s in report["sections"]])
    parts += ["", *[f"- {note}" for note in report["notes"]]]
    return "\n".join(parts).rstrip() + "\n"


# -- assembly --------------------------------------------------------------------------------
BUILDERS = {"overview": _overview_data, "metrics": _metrics_data, "tools": _tools_data,
            "projects": _projects_data, "friction": _friction_data}
MIN_N = {"overview": MIN_SESSIONS, "metrics": MIN_SESSIONS, "tools": MIN_SESSIONS,
         "friction": MIN_SESSIONS, "projects": 1}


def build_section(sid: str, fetched: dict, recs: dict | None) -> dict:
    needs = NEEDS[sid]
    bodies = {name: fetched[name][0] for name in needs}
    states = [fetched[name][1] for name in needs]
    section = {"id": sid, "title": TITLES[sid], "basis": BASIS[sid], "n": None,
               "coverage": _coverage(next((b for b in bodies.values() if b), None)),
               "freshness": "stale" if "stale" in states else "fresh",
               "status": "ok", "data": None}
    if sid == "recommendations":
        if recs is None:
            section.update(status="unavailable", freshness="none")
        else:
            section.update(n=len(recs["items"]), data=recs)
    elif any(b is None for b in bodies.values()):
        computing = "computing" in states
        section.update(status="computing" if computing else "unavailable",
                       freshness=next((s for s in states if s not in ("fresh", "stale")), "none"),
                       coverage=None)
    elif sid == "persona":
        n, data, reason = _persona_data(bodies)
        section.update(n=n, data=data, status="ok" if data else
                       "unavailable" if reason == "persona_unavailable" else "insufficient")
    else:
        n, data = BUILDERS[sid](bodies)
        if n is None or data is None:
            section.update(status="unavailable")
        else:
            section.update(n=n, data=data,
                           status="insufficient" if n < MIN_N[sid] else "ok")
    section["markdown"] = section_markdown(section)
    return section


def assemble(gw, section_ids, scope: dict, *, wait_ms: int = 3000) -> dict:
    needed = [name for sid in section_ids for name in NEEDS[sid]]
    fetched, h = fetch_sections(gw, needed, scope, wait_ms)
    recs = recommendations(gw.appdb, h) if "recommendations" in section_ids else None
    sections = [build_section(sid, fetched, recs) for sid in section_ids]
    notes = ["数字取自与页面相同的分析快照；缺失值显示为“未知”，不按 0 处理。"]
    if "persona" in section_ids:
        notes.append("协作画像为实验性，未达分享卡同一样本门槛时不显示。")
    if any(s["status"] == "computing" for s in sections):
        notes.append("部分章节仍在计算，稍后重新导出可得到完整数字。")
    return {"generated_at": int(time.time() * 1000), "scope": scope, "scope_hash": h,
            "sections": sections, "notes": notes}
