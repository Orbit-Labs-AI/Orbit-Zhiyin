"""Benefit × Wilson × fit scoring with personal weights and exposure decay (RC-05, RC-17).

priority = 100·max(0, B·c·p·f/(1+cost) − 0.1·risk) × personal × decay
Every factor is stored so the card can show why it ranked where it did.
"""

import math

from .gates import evidence_changed, top_agent

PRIOR_MEAN = {"permission_rule": .9, "removal": .9, "hook": .8, "builtin": .7, "skill": .6,
              "rule": .5, "subagent": .5, "mcp": .5, "plugin": .5,
              "prompt": .4, "model": .4, "workflow": .4, "generate": .4}
PRIOR_STRENGTH = 10
BASIS_BENEFIT = {"generic": .1, "model": .3, "profile": .15}
AGENT_FIT = {"native": 1., "manual": .8, "adaptation_required": .4, "unknown": .5, "unsupported": 0.}
RISK = {"low": .05, "medium": .25, "high": .6}
ENGAGED_LABELS = {"install", "installed", "open", "opened", "preview"}


def basis(raw: dict) -> str:
    """problem | model | profile | generic — which evidence the card stands on."""
    if raw.get("problem"):
        return "problem"
    if raw.get("kind") == "model":
        return "model"
    return "profile" if raw.get("match_basis") in {"profile", "preference"} else "generic"


def prior(raw: dict) -> tuple[float, float]:
    given = raw.get("prior") or {}
    if given.get("alpha") and given.get("beta"):
        return float(given["alpha"]), float(given["beta"])
    mean = PRIOR_MEAN.get(raw.get("kind"), .4)
    return PRIOR_STRENGTH * mean, PRIOR_STRENGTH * (1 - mean)


def _confidence(raw: dict, inputs: dict, kind_basis: str) -> float:
    if kind_basis == "problem":
        return float(raw["problem"].get("wilson_lo") or 0)
    if kind_basis == "model":
        return float(raw.get("confidence", .5))
    if kind_basis == "profile":
        ev = (inputs.get("profile") or {}).get("evidence_sessions") or 0
        ev = sum(ev.values()) if isinstance(ev, dict) else ev
        return min(1., ev / 20) * .5
    return .1


def _preference(raw: dict, inputs: dict) -> float:
    tags = {t.lower() for t in raw.get("tags") or []}
    profile = inputs.get("profile") or {}
    mine = {str(t).lower() for key in ("tags", "languages", "frameworks", "tools") for t in profile.get(key) or []}
    return len(tags & mine) / len(tags) if tags and mine else 0.


def _decay(raw: dict, memory: dict) -> float:
    state = (memory.get("state") or {}).get(raw["rec_key"])
    if not state:
        return 1.
    sessions = (raw.get("problem") or {}).get("sessions") or 0
    if evidence_changed(sessions, state.get("last_evidence")):
        return 1.
    labels = (memory.get("labels") or {}).get(raw["rec_key"]) or []
    if state.get("install_id") or any(lb.get("label") in ENGAGED_LABELS for lb in labels):
        return 1.
    return max(.5, .85 ** max(0, (state.get("shown_count") or 0) - 1))


def score(raw: dict, gates: dict, inputs: dict, memory: dict, *, max_fusion: float | None = None) -> dict:
    """Score one RawCand; `max_fusion` is the pool maximum (defaults to its own fusion)."""
    kind_basis = basis(raw)
    problem = raw.get("problem") or {}
    if kind_basis == "problem":
        weekly_saving = (problem.get("weekly_count") or 0) * (raw.get("unit_minutes") or 0)
        benefit = 1 - math.exp(-weekly_saving / 30)
    else:
        benefit = BASIS_BENEFIT[kind_basis]
    confidence = _confidence(raw, inputs, kind_basis)

    alpha, beta = prior(raw)
    post = (memory.get("posteriors") or {}).get(raw["rec_key"]) or {}
    a, b = post.get("alpha", 0), post.get("beta", 0)
    p_effective = (alpha + a) / (alpha + beta + a + b)

    fusion = raw.get("fusion") or 0
    top = max_fusion if max_fusion else fusion
    agent = top_agent(inputs)
    support = (raw.get("agents") or {}).get(agent, "unknown") if agent else "unknown"
    fit = .5 * (min(1., fusion / top) if top else 0) + .3 * AGENT_FIT.get(support, .5) + .2 * _preference(raw, inputs)

    cost_in = raw.get("cost") or {}
    cost = (cost_in.get("setup_minutes") or 0) / 30 + (cost_in.get("context_tokens") or 0) / 2000
    risk = RISK.get((raw.get("risk") or {}).get("level", "low"), .05)

    weights = memory.get("weights") or {}
    personal = (weights.get("kind") or {}).get(raw.get("kind"), 1) * (weights.get("dim") or {}).get(raw.get("dim"), 1)
    personal = min(1.5, max(.5, personal))
    decay = _decay(raw, memory)

    net = benefit * confidence * p_effective * fit / (1 + cost) - .1 * risk
    priority = round(100 * max(0., net) * personal * decay, 2)
    r = 4
    return {"benefit": round(benefit, r), "confidence": round(confidence, r), "p_effective": round(p_effective, r),
            "fit": round(fit, r), "cost": round(cost, r), "risk": risk, "personal": round(personal, r),
            "decay": round(decay, r), "priority": priority,
            # unclipped priority: weak evidence often clips priority to 0, utility keeps the order meaningful
            "utility": round(net * personal * decay, 6)}

