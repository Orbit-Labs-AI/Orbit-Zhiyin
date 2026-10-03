"""A1 「AI 解读」 card (lede + 做得好 / 卡在哪 / 立刻可做).

``build`` is the L0 template (no model). Every column carries the number of sessions behind it
and a ``ref`` the page can open (a filter on the sessions page or the recommendations route).
Completion is an estimate from agent logs, so it is labelled 「估计」.

``with_ai`` swaps in the texts of a model-written ``narrate.overview`` when the gateway's
provider (``set_ai_provider``, bound to ``ai.narratives.latest_overview``) has one for exactly
this window/project and the current ``data_rev``; the card then says ``basis: ai_narrative``
and names the job. Counts and refs stay the L0 ones (they come from the same rows).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from . import derive

WHEN = "规则模板 · 本地生成"
RECS_REF = "/v1/recommendations?surface=A1"
AI_WHEN = "AI 撰写 · 基于当前数据"
_ai_provider: Callable[[dict | None, object], dict | None] | None = None


def set_ai_provider(fn: Callable[[dict | None, object], dict | None] | None) -> None:
    """``fn(scope, data_rev)`` → ``{job_id, engine, finished_at, result}`` or ``None``."""
    global _ai_provider
    _ai_provider = fn


def lede(p: dict) -> str:
    if p["ok"]:
        return f"你像一位{p['zh']}：{p['line']}" + (f"（{p['hint']}）" if p.get("hint") else "")
    return "所选范围还没有会话，暂时无法给出协作画像。"


def build(rows: list[dict], st: dict, p: dict, projects: dict) -> dict:
    n = len(rows)
    verified = sum(1 for r in rows if r.get("verify"))
    ok_n = sum(1 for r in rows if r.get("out") == "ok")
    if n:
        parts = []
        if st["verify"] is not None:
            parts.append(f"{round(st['verify'])}% 的会话要求或运行了验证")
        if st["ok"] is not None:
            parts.append(f"估计完成率 {round(st['ok'])}%")
        good = ("，".join(parts) + "。") if parts else "这段时间的验证与完成情况未知。"
    else:
        good = "这段时间还没有会话。"
    fr = sorted(derive.count_by(rows, "fric").items(), key=lambda kv: (-kv[1], kv[0]))
    by_project = Counter()
    for r in rows:
        if r.get("corr"):
            by_project[r.get("p")] += r["corr"]
    top_p = [derive.project_name(projects, pid) for pid, _ in by_project.most_common(2)]
    if fr:
        kind, count = fr[0]
        stuck = {"text": f"{count} 个会话出现「{kind}」" + (f"，集中在 {'、'.join(top_p)}"
                                                       if top_p else "") + "（规则候选）。",
                 "evidence_n": count, "ref": {"page": "sessions", "filter": {"fric": kind}},
                 "series": [c for _, c in fr[:3]]}
    elif st["corr"]:
        corr_sessions = sum(1 for r in rows if r.get("corr"))
        stuck = {"text": f"{int(st['corr'])} 次纠偏（规则候选），分布在 {corr_sessions} 个会话。",
                 "evidence_n": corr_sessions, "ref": {"page": "sessions", "filter": {}},
                 "series": []}
    else:
        stuck = {"text": "这段时间没有明显的摩擦。", "evidence_n": 0, "ref": None, "series": []}
    next_ = {"text": (f"针对「{fr[0][0]}」查看建议。" if fr else "查看本周建议。"),
             "evidence_n": None, "ref": RECS_REF}
    return {"lede": lede(p), "when": WHEN, "basis": "l0_template",
            "good": {"text": good, "evidence_n": ok_n, "verified_n": verified,
                     "ok_est": round(st["ok"], 1) if n and st["ok"] is not None else None, "basis": "estimate",
                     "ref": {"page": "sessions", "filter": {"outcome": "ok"}}},
            "stuck": stuck, "next": next_}


def with_ai(card: dict, scope: dict | None, data_rev, *, with_scope: bool = False) -> dict:
    """``card`` with the model narrative's texts when one matches; otherwise ``card``.

    ``scope`` is ``None`` when the view has filters a narrative cannot describe (agents,
    topic, outcome, friction, hour, brushed window, 「全部」): the L0 card is kept.
    ``with_scope`` adds ``ai_scope`` (that scope, or ``None``): the page's 「重新生成」 posts a
    ``narrate.overview`` job with exactly this scope, so the result is the one read back here."""
    if with_scope:
        return {**_with_ai(card, scope, data_rev), "ai_scope": scope}
    return _with_ai(card, scope, data_rev)


def _with_ai(card: dict, scope: dict | None, data_rev) -> dict:
    if _ai_provider is None or scope is None or data_rev is None:
        return card
    try:
        found = _ai_provider(scope, data_rev)
    except Exception:  # noqa: BLE001 - app.db unreadable: the L0 card is still correct
        return card
    if not found:
        return card
    out = found["result"]
    scenes = {f.get("scene"): f.get("text") for f in out.get("findings") or [] if f.get("text")}
    if not out.get("summary") or not scenes:
        return card
    merged = {**card, "lede": out["summary"], "when": AI_WHEN, "basis": "ai_narrative",
              "source": {"task_id": "narrate.overview", "job_id": found["job_id"],
                         "engine": found.get("engine"), "finished_at": found.get("finished_at")},
              "caveats": list(out.get("caveats") or [])}
    for scene, key in (("good", "good"), ("stuck", "stuck"), ("next", "next")):
        if scenes.get(scene):
            merged[key] = {**card[key], "text": scenes[scene]}
    return merged
