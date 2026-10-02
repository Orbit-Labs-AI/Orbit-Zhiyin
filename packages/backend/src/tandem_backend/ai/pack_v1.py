"""Pack items for the v1 AI tasks (AI-04.x / AI-05.2–05.4).

Each loader reads tandem.db / app.db read-only and returns plain JSON; callers can
always override an item through ``slots`` (AN-18 clusters, AN-14 snapshots and AN-08
profiles are produced by other modules and handed in that way). Every item carries a
``key`` so the narrative endpoint can find the latest result for the same subject.
"""

from __future__ import annotations

from .pack import (
    FAIL_STATUS,
    _Ctx,
    _facet_rows,
    _failure_runs,
    _friction_item,
    _metrics,
    _tool_rows,
    facet_payload,
    is_correction,
    placeholders,
)

FEEDBACK_MAX = 20
FAILURES_PER_CLASS = 30
UNKNOWN_MAX = 4
FAILED_SQL = "(t.status IN ('failed','error') OR t.error_class IS NOT NULL)"


def _prev_assistant(conn, session_uid: str, event_uid: str) -> str:
    row = conn.execute(
        "SELECT a.text FROM event a JOIN event h ON h.event_uid=? WHERE a.session_uid=? AND a.actor='assistant'"
        " AND a.kind LIKE 'message.%' AND a.seq<h.seq AND a.text IS NOT NULL ORDER BY a.seq DESC LIMIT 1",
        (event_uid, session_uid)).fetchone()
    return (row[0] if row else "")[:200]


def feedback_items(c: _Ctx) -> dict:
    """Ambiguous feedback candidates (AI-04.1): explicit ``event_uids`` (A6-10 re-judge) or the
    correction-like human messages of ``session_uids``; each with the preceding assistant reply."""
    if c.conn is None:
        return {"key": "default", "items": []}
    event_uids = list(c.params.get("event_uids") or [])
    if event_uids:
        rows = c.conn.execute(
            f"SELECT h.session_uid, h.event_uid, h.text, s.title FROM v_human_message h JOIN session s"
            f" ON s.session_uid=h.session_uid WHERE h.event_uid IN ({placeholders(event_uids)})"
            f" ORDER BY h.ts LIMIT ?", [*event_uids, FEEDBACK_MAX]).fetchall()
    else:
        uids = list(c.params.get("session_uids") or [])
        where, params = (f"s.session_uid IN ({placeholders(uids)})", uids) if uids else c.where()
        rows = [r for r in c.conn.execute(
            f"SELECT h.session_uid, h.event_uid, h.text, s.title FROM v_human_message h JOIN session s"
            f" ON s.session_uid=h.session_uid WHERE {where} ORDER BY h.ts DESC LIMIT 400", params)
            if is_correction(r[2])][:FEEDBACK_MAX]
    items = [{"signal_id": "sig:" + r[1], "event_uid": r[1], "session_uid": r[0], "text": (r[2] or "")[:300],
              "prev_assistant": _prev_assistant(c.conn, r[0], r[1]), "context": (r[3] or "")[:60],
              "rejudge": bool(event_uids)} for r in rows]
    return {"key": ",".join(event_uids) or "default", "items": items}


def failures(c: _Ctx) -> dict:
    """Failed tool calls grouped by ``error_class`` (AI-04.2); first 200 chars of the output."""
    if c.conn is None:
        return {"key": "default", "groups": []}
    where, params = c.where()
    rows = c.conn.execute(
        f"SELECT COALESCE(t.error_class,'unknown') cls, t.call_uid, t.name, t.command_head, e.text"
        f" FROM tool_call t JOIN session s ON s.session_uid=t.session_uid"
        f" LEFT JOIN event e ON e.event_uid=t.result_event_uid WHERE {where} AND {FAILED_SQL}"
        f" ORDER BY cls, t.started_at DESC LIMIT 2000", params).fetchall()
    groups: dict[str, list] = {}
    for cls, call_uid, name, head, text in rows:
        members = groups.setdefault(cls, [])
        if len(members) < FAILURES_PER_CLASS:
            members.append({"call_uid": call_uid, "tool": name, "command_head": head,
                            "text": (text or "")[:200]})
    key = f"{c.start}:{c.end}:{c.project_id or ''}"
    return {"key": key, "groups": [{"error_class": k, "count": len(v), "members": v}
                                   for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))][:12]}


def unknown_failures(c: _Ctx) -> dict:
    """≤4 failures without a usable ``error_class`` (AI-04.4)."""
    if c.conn is None:
        return {"key": "default", "items": []}
    call_uids = list(c.params.get("call_uids") or [])
    if call_uids:
        cond, params = f"t.call_uid IN ({placeholders(call_uids)})", call_uids
    else:
        where, params = c.where()
        cond = f"{where} AND t.status IN ('failed','error') AND COALESCE(t.error_class,'unknown')='unknown'"
    rows = c.conn.execute(
        f"SELECT t.call_uid, t.name, t.command_head, t.exit_code, e.text FROM tool_call t"
        f" JOIN session s ON s.session_uid=t.session_uid LEFT JOIN event e ON e.event_uid=t.result_event_uid"
        f" WHERE {cond} ORDER BY t.started_at DESC LIMIT ?", [*params, UNKNOWN_MAX]).fetchall()
    items = [{"call_uid": r[0], "tool": r[1], "command_head": r[2], "exit_code": r[3], "text": (r[4] or "")[:400]}
             for r in rows]
    return {"key": ",".join(call_uids) or "default", "items": items}


def topic_clusters(c: _Ctx) -> dict:
    """AN-18 clusters are computed elsewhere; callers pass them in ``params.clusters``."""
    clusters = []
    for cl in c.params.get("clusters") or []:
        clusters.append({"cluster_id": str(cl.get("cluster_id")), "size": cl.get("size"),
                         "top_terms": list(cl.get("top_terms") or [])[:20],
                         "summaries": [str(s)[:80] for s in (cl.get("summaries") or [])[:3]]})
    return {"key": c.params.get("key") or "default", "clusters": clusters}


def _key_moments(rows) -> list[dict]:
    moments = [{"kind": "failure_run", **r} for r in _failure_runs(rows)[:5]]
    failed = [r for r in rows if r[4] in FAIL_STATUS or r[5]]
    if failed and not moments:
        moments.append({"kind": "tool_failures", "count": len(failed), "error_class": failed[0][5]})
    return moments


def session_review(c: _Ctx) -> dict:
    """One session's facet, AN-02-style row, signals and key moments (AI-05.2)."""
    uid = c.params.get("session_uid") or ""
    if c.conn is None or not uid:
        return {"key": uid, "session_uid": uid}
    payload = facet_payload(c.conn, uid)
    facet = _facet_rows(c.appdb, [uid]).get(uid)
    project = c.conn.execute("SELECT project_id FROM session WHERE session_uid=? LIMIT 1", (uid,)).fetchone()
    recent = []
    if project and project[0]:
        others = [r[0] for r in c.conn.execute(
            "SELECT session_uid FROM session WHERE project_id=? AND session_uid<>? AND kind='main'"
            " ORDER BY started_at DESC LIMIT 5", (project[0], uid))]
        facets = _facet_rows(c.appdb, others)
        recent = [{"session_uid": o, "summary": facets[o].get("summary")} for o in others
                  if facets.get(o, {}).get("summary")]
    return {"key": uid, "session_uid": uid, "row": payload["row"], "facet": facet,
            "signals": payload["candidates"], "key_moments": _key_moments(_tool_rows(c, [uid], 400)),
            "first_messages": payload["human_messages"][:3], "recent_project_summaries": recent}


def snapshot(c: _Ctx) -> dict:
    """A minimal ``report_snapshot(weekly)`` when AN-14 does not hand one in via slots."""
    return {"key": f"{c.start}:{c.end}:{c.project_id or ''}", "window": {"start_ms": c.start, "end_ms": c.end},
            "metrics": _metrics(c), "friction": _friction_item(c),
            "rec_outcomes": list(c.params.get("rec_outcomes") or [])}


PERSONA_KEYS = ("code", "type_name", "experimental", "axes", "observations", "interaction", "rates",
                "frictions", "problems", "compare_previous", "not_me")


def persona(c: _Ctx) -> dict:
    """AN-08 profile subset (AI-05.4); ``params.profile`` wins over ``features.profile()``."""
    profile = c.params.get("profile")
    if profile is None:
        try:
            profile = c.profile()
        except Exception:  # noqa: BLE001 - features module unavailable
            profile = {}
    out = {k: profile.get(k) for k in PERSONA_KEYS if profile.get(k) is not None}
    out["observations"] = list(out.get("observations") or [])[:5]
    out["frictions"] = list(out.get("frictions") or [])[:3]
    return {"key": c.params.get("key") or str(out.get("code") or "default"), **out}


# key: (label, desc, data_class, loader) — merged into pack.ITEMS
ITEMS_V1 = {
    "feedback_items": ("反馈候选", "≤20 条歧义反馈原话与前一条助手回复", "snippets", feedback_items),
    "failures": ("失败输出", "按错误类别分组的失败输出首 200 字（每类 ≤30）", "snippets", failures),
    "unknown_failures": ("未归类失败", "≤4 条未归类失败的输出", "snippets", unknown_failures),
    "topic_clusters": ("主题簇", "每簇 top terms 与 ≤3 条会话摘要", "summary", topic_clusters),
    "session_review": ("会话复盘材料", "该会话的 facet、统计行、信号、关键时刻与开场原话", "snippets", session_review),
    "snapshot": ("周报快照", "固定窗口指标、问题与建议效果", "summary", snapshot),
    "persona": ("画像", "四轴、前 5 条观察、交互统计与前 3 类摩擦", "summary", persona),
}
