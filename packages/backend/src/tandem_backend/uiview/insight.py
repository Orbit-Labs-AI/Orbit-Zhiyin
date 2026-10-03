"""L0 template for the A1 「AI 解读」 card (lede + 做得好 / 卡在哪 / 立刻可做), no model.

Every column carries the number of sessions behind it and a ``ref`` the page can open (a
filter on the sessions page or the recommendations route). Completion is an estimate from
agent logs, so it is labelled 「估计」.
"""

from __future__ import annotations

from collections import Counter

from . import derive

WHEN = "规则模板 · 本地生成"
RECS_REF = "/v1/recommendations?surface=A1"


def lede(p: dict) -> str:
    if p["ok"]:
        return f"你像一位{p['zh']}：{p['line']}" + (f"（{p['hint']}）" if p.get("hint") else "")
    return "所选范围还没有会话，暂时无法给出协作画像。"


def build(rows: list[dict], st: dict, p: dict, projects: dict) -> dict:
    n = len(rows)
    verified = sum(1 for r in rows if r.get("verify"))
    ok_n = sum(1 for r in rows if r.get("out") == "ok")
    if n:
        good = (f"{round(st['verify'])}% 的会话要求或运行了验证，估计完成率 {round(st['ok'])}%。")
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
                     "ok_est": round(st["ok"], 1) if n else None, "basis": "estimate",
                     "ref": {"page": "sessions", "filter": {"outcome": "ok"}}},
            "stuck": stuck, "next": next_}
