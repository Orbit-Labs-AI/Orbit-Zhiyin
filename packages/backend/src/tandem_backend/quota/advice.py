"""RC-14 cross-agent quota & task-allocation advice (L0 rules; advice only, never switches).

Per agent the binding window (lowest headroom) decides the verdict:
``avoid`` < 10 % headroom <= ``conserve`` < 30 % <= ``available``; no window -> ``insufficient``.
The recommendation is the comparable agent with the most headroom (observed beats
estimated on ties). For a tight agent that used several models in the last 7 days, the
hint points at its second most used model. Without any comparable agent the result is
``status = 'insufficient'`` with no recommendation.
"""

from __future__ import annotations

from .usage import DAY_MS, calls

AVOID, CONSERVE = 0.10, 0.30
BASIS_RANK = {"observed": 0, "observed_reset": 0, "estimated_peak": 1}
NAMES = {"claude_code": "Claude Code", "codex": "Codex"}


def verdict(headroom: float | None) -> str:
    if headroom is None:
        return "insufficient"
    return "avoid" if headroom < AVOID else "conserve" if headroom < CONSERVE else "available"


def model_mix(db, now_ms: int, excluded=()) -> dict[str, list[dict]]:
    counts: dict[str, dict[str, int]] = {}
    for row in calls(db, now_ms - 7 * DAY_MS, now_ms + 1, excluded):
        per = counts.setdefault(row["agent"] or "unknown", {})
        per[row["model"]] = per.get(row["model"], 0) + 1
    return {agent: [{"model": m, "requests": n, "share": round(n / sum(per.values()), 4)}
                    for m, n in sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))]
            for agent, per in counts.items()}


def advise(snapshot: dict, mix: dict[str, list[dict]]) -> dict:
    items = []
    for agent in snapshot["agents"]:
        v = verdict(agent["headroom"])
        models = mix.get(agent["agent"], [])
        item = {**agent, "verdict": v, "models": models, "model_hint": None,
                "reason": _reason(agent, v)}
        if v in ("avoid", "conserve") and len(models) > 1 and models[0]["share"] >= 0.6:
            item["model_hint"] = {
                "from": models[0]["model"], "to": models[1]["model"],
                "reason": f"{models[0]['model']} 占近 7 天请求 {models[0]['share']:.0%}，"
                          f"额度紧张时可把部分任务改用 {models[1]['model']}"}
        items.append(item)
    comparable = [i for i in items if i["verdict"] in ("available", "conserve")]
    best = min(comparable, key=lambda i: (-i["headroom"], BASIS_RANK.get(i["basis"], 2),
                                          i["agent"]), default=None)
    if best is None:
        status = "insufficient"
    else:
        status = "ok" if all(i["verdict"] != "insufficient" for i in items) else "partial"
    candidate = None
    if best is not None:
        name = NAMES.get(best["agent"], best["agent"])
        candidate = {
            "kind": "workflow", "agent": best["agent"],
            "title": f"这类任务本周优先交给 {name}",
            "reason": best["reason"], "basis": best["basis"],
            "confidence": "low" if best["basis"] == "estimated_peak" or status == "partial"
            else "medium",
        }
    return {"now": snapshot["now"], "status": status, "items": items, "recommendation": candidate}


def _reason(agent: dict, v: str) -> str:
    if v == "insufficient":
        return "缺少额度数据（无 rate_limits 快照或历史用量不足），无法判断余量"
    window = {"five_hour": "5 小时", "weekly": "每周"}.get(agent["binding_window"],
                                                         agent["binding_window"])
    estimated = "（按历史峰值估算）" if agent["basis"] == "estimated_peak" else ""
    return f"{window}窗口剩余约 {agent['headroom']:.0%}{estimated}"
