"""Route ⑦ (RC-08 v1-light): suggest a lower thinking effort for read-only sessions."""

from ..problems import wilson_lo

HIGH_EFFORT = {"high", "xhigh", "max"}
MIN_SESSIONS, MIN_SHARE = 5, .3


def recall(inputs: dict) -> tuple[list, dict]:
    mix = (inputs.get("facts") or {}).get("model_mix") or []
    high = [row for row in mix if str(row.get("effort") or "").lower() in HIGH_EFFORT]
    sessions = sum(int(row.get("sessions") or 0) for row in high)
    readonly = sum(int(row.get("readonly_sessions") or 0) for row in high)
    if readonly < MIN_SESSIONS or not sessions or readonly / sessions < MIN_SHARE:
        return [], {}
    tokens = sum(int(row.get("tokens") or 0) for row in high)
    models = sorted({str(row.get("model_id")) for row in high if row.get("model_id")})
    confidence = round(wilson_lo(readonly, sessions), 4)
    key = "model:effort-medium-readonly"
    agents = sorted((inputs.get("agents") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    values = {"k": readonly, "n": sessions, "share": round(100 * readonly / sessions), "models": "、".join(models),
              "tokens": tokens}
    cand = {
        "rec_key": key, "problem": None, "kind": "model", "dim": "model", "level": 1, "audience_min": 1,
        "title": "只读审查任务改用 thinking medium",
        "summary": "高思考档位的会话里有相当比例只读不改，可以先用 medium，出现编辑再恢复。",
        "match_basis": "inventory_fact", "routes": {}, "fusion": 0.,
        "evidence": {"session_uids": [], "signal_ids": [], "counts": {"sessions": readonly, "events": 0}},
        "source": {"origin": "template", "item_id": "effort-medium-readonly", "url": None, "license": None,
                   "version": "1", "verified": True},
        "target": {"agents": [a for a, _ in agents if a == "claude_code"] or ["claude_code"], "scope": "user",
                   "project_id": None, "path_hint": "Tandem 任务预设"},
        "track": {"triggered": "只读会话 tokens", "mechanical": "medium 档会话数", "guardrail": "结论一致率",
                  "follow_days": 7, "extend_days": 28},
        "trial": {"steps": ["应用预设到只读审查类任务", "出现编辑时自动恢复原档位", "7 天后对比 tokens 与结论一致率"],
                  "metric": "只读会话 tokens", "follow_days": 7},
        "alternatives": [], "generate": None, "kb": None, "item": None, "agents": {"claude_code": "native"},
        "prior": {"alpha": 3., "beta": 2.}, "cost": {"setup_minutes": 1., "context_tokens": 0, "reversible": True},
        "risk": {"level": "low", "flags": ["quality_tradeoff"]}, "requirements": {"tools": [], "software": []},
        "gates_hint": {"scenes": None, "language": None}, "unit_minutes": .5,
        "tags": ["model", "effort", "thinking", "tokens", "readonly"],
        "file": [["# 只读审查类任务预设", " "], ["match: 只读（以 Read / Grep 为主，没有 Edit）", "+"],
                 ["thinking: medium", "+"], ["fallback: 原档位（出现 Edit 时自动恢复）", "ai"]],
        "explain_hints": {"reason_template": "{n} 个高思考档会话里有 {k} 个（{share}%）只读不改。",
                          "mechanism": "只读任务对推理深度要求低，降档主要省 tokens。",
                          "trial": "应用 7 天后对比 tokens 与结论一致率。",
                          "limitation": "收益为估算（basis=estimated），复杂审查仍建议高档。",
                          "basis": "estimated", "confidence": confidence, "vars": values},
    }
    return [(key, confidence or .01)], {key: cand}
