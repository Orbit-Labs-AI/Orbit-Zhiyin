"""Route ⑦ (RC-08 v1-light): suggest a lower thinking effort for read-only sessions.

Two variants: Claude Code (Orbit task preset) and Codex (``model_reasoning_effort`` in
``~/.codex/config.toml``, text from the KB entry ``codex-effort-medium``). Each only
appears when that agent is in ``inputs.agents`` (no agent info keeps the Claude variant).
"""

from .. import kb as kb_mod
from ..problems import wilson_lo
from .kb_route import fill

HIGH_EFFORT = {"high", "xhigh", "max"}
CODEX_HIGH = {"high", "xhigh"}
MIN_SESSIONS, MIN_SHARE = 5, .3
CODEX_RULE = "codex-effort-medium"


def _uids(rows: list[dict]) -> list[str]:
    """Read-only session uids behind the counts, so the card's「依据 N 个会话」is resolvable."""
    out: list[str] = []
    for row in rows:
        out += [uid for uid in row.get("readonly_session_uids") or () if uid not in out]
    return out[:20]


def _stats(rows: list[dict]) -> tuple[int, int, int, str] | None:
    sessions = sum(int(row.get("sessions") or 0) for row in rows)
    readonly = sum(int(row.get("readonly_sessions") or 0) for row in rows)
    if readonly < MIN_SESSIONS or not sessions or readonly / sessions < MIN_SHARE:
        return None
    tokens = sum(int(row.get("tokens") or 0) for row in rows)
    models = "、".join(sorted({str(row.get("model_id")) for row in rows if row.get("model_id")}))
    return readonly, sessions, tokens, models


def recall(inputs: dict) -> tuple[list, dict]:
    mix = (inputs.get("facts") or {}).get("model_mix") or []
    agents = inputs.get("agents") or {}
    rows, payload = [], {}
    if not agents or agents.get("claude_code"):
        claude = [row for row in mix if row.get("agent") != "codex"
                  and str(row.get("effort") or "").lower() in HIGH_EFFORT]
        r, p = _claude(claude, inputs)
        rows, payload = rows + r, {**payload, **p}
    if agents.get("codex"):
        codex = [row for row in mix if row.get("agent") == "codex"
                 and str(row.get("effort") or "").lower() in CODEX_HIGH]
        r, p = _codex(codex, inputs)
        rows, payload = rows + r, {**payload, **p}
    return rows, payload


def _codex(high: list[dict], inputs: dict) -> tuple[list, dict]:
    stats = _stats(high)
    if stats is None:
        return [], {}
    try:
        rule = kb_mod.by_id(kb_mod.load()[0]).get(CODEX_RULE)
    except (OSError, ValueError):
        rule = None
    if rule is None:
        return [], {}
    readonly, sessions, tokens, models = stats
    confidence = round(wilson_lo(readonly, sessions), 4)
    key = "model:codex-effort-medium-readonly"
    values = {"k": readonly, "n": sessions, "share": round(100 * readonly / sessions), "models": models,
              "tokens": tokens}
    cand = {
        "rec_key": key, "problem": None, "kind": "model", "dim": "model", "level": rule.remedy.level,
        "audience_min": rule.audience_min, "title": fill(rule.title, values), "summary": fill(rule.summary, values),
        "match_basis": "inventory_fact", "routes": {}, "fusion": 0.,
        "evidence": {"session_uids": _uids(high), "signal_ids": [], "counts": {"sessions": readonly, "events": 0}},
        "source": {"origin": "template", "item_id": rule.id, "url": None, "license": None,
                   "version": str(rule.version), "verified": True},
        "target": {"agents": ["codex"], "scope": "user", "project_id": None, "path_hint": rule.remedy.path},
        "track": {**rule.track.model_dump(), "extend_days": 28},
        "trial": {"steps": [fill(step, values) for step in rule.steps],
                  "commands": [fill(c, values) if c else None for c in rule.commands],
                  "metric": rule.track.triggered, "follow_days": rule.track.follow_days},
        "alternatives": [], "generate": None, "kb": rule.model_dump(mode="json"), "item": None,
        "agents": dict(rule.remedy.agents), "prior": rule.benefit.prior.model_dump(), "cost": rule.cost.model_dump(),
        "risk": rule.risk.model_dump(), "requirements": {"tools": [], "software": []},
        "gates_hint": rule.gates.model_dump(), "unit_minutes": rule.benefit.unit_minutes,
        "unit_minutes_source": rule.benefit.unit_minutes_source, "tags": list(rule.tags),
        "file": [[fill(line, values), mark] for line, mark in rule.file] or None,
        "explain_hints": {**rule.explain.model_dump(), "basis": "estimated", "confidence": confidence,
                          "vars": values},
    }
    return [(key, confidence or .01)], {key: cand}


def _claude(high: list[dict], inputs: dict) -> tuple[list, dict]:
    stats = _stats(high)
    if stats is None:
        return [], {}
    readonly, sessions, tokens, models = stats
    confidence = round(wilson_lo(readonly, sessions), 4)
    key = "model:effort-medium-readonly"
    agents = sorted((inputs.get("agents") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    values = {"k": readonly, "n": sessions, "share": round(100 * readonly / sessions), "models": models,
              "tokens": tokens}
    cand = {
        "rec_key": key, "problem": None, "kind": "model", "dim": "model", "level": 1, "audience_min": 1,
        "title": "只读审查任务改用 thinking medium",
        "summary": "高思考档位的会话里有相当比例只读不改，可以先用 medium，出现编辑再恢复。",
        "match_basis": "inventory_fact", "routes": {}, "fusion": 0.,
        "evidence": {"session_uids": _uids(high), "signal_ids": [], "counts": {"sessions": readonly, "events": 0}},
        "source": {"origin": "template", "item_id": "effort-medium-readonly", "url": None, "license": None,
                   "version": "1", "verified": True},
        "target": {"agents": [a for a, _ in agents if a == "claude_code"] or ["claude_code"], "scope": "user",
                   "project_id": None, "path_hint": "Orbit 任务预设"},
        "track": {"triggered": "只读会话 tokens", "mechanical": "medium 档会话数", "guardrail": "结论一致率",
                  "follow_days": 7, "extend_days": 28},
        "trial": {"steps": ["应用预设到只读审查类任务", "出现编辑时自动恢复原档位", "7 天后对比 tokens 与结论一致率"],
                  "metric": "只读会话 tokens", "follow_days": 7},
        "alternatives": [], "generate": None, "kb": None, "item": None, "agents": {"claude_code": "native"},
        "prior": {"alpha": 3., "beta": 2.}, "cost": {"setup_minutes": 1., "context_tokens": 0, "reversible": True},
        "risk": {"level": "low", "flags": ["quality_tradeoff"]}, "requirements": {"tools": [], "software": []},
        "gates_hint": {"scenes": None, "language": None}, "unit_minutes": None,
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
