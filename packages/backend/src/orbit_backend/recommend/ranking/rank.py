"""Benefit × Wilson × fit scoring with personal weights and exposure decay (RC-05, RC-17).

    value    = (B · c · p · f) ** (1/4)          geometric mean of four [0, 1] factors
    net      = value / (1 + cost) − risk          risk ∈ {.05, .25, .6} on the same [0, 1] scale
    priority = 100 · max(0, net) · personal · decay

Why a geometric mean: the old ``B·c·p·f − .1·risk`` multiplied four sub-unit factors,
so typical products were ~1e-3 and the fixed risk term flipped most cards negative
(12 replay cases: top-1 priority ≤ 2/100, 6 of them 0 with negative net). The geometric
mean keeps the "any factor 0 ⇒ value 0" property of the product while staying on the
factors' own [0, 1] scale, so value and risk are commensurable and priority reads as
"points out of 100 of risk-adjusted expected value". It is a ranking index, not minutes
or a probability; the constants below are uncalibrated design choices (documented in
docs/modules/recommendation/engine.md), not fitted values.

``utility`` keeps the unclipped value; engine gates every candidate with utility ≤ 0
(``net_non_positive``) so nothing with non-positive expected value reaches the slate.
Every factor is stored so the card can show why it ranked where it did.
"""

import math

from ..units import CONTEXT_TOKENS_PER_UNIT
from .gates import agent_support, evidence_changed, target_agents

PRIOR_MEAN = {"permission_rule": .9, "removal": .9, "hook": .8, "builtin": .7, "skill": .6,
              "rule": .5, "subagent": .5, "mcp": .5, "plugin": .5,
              "prompt": .4, "model": .4, "workflow": .4, "generate": .4}
PRIOR_STRENGTH = 10
# Fixed benefit/confidence for cards without a problem (uncalibrated design values, see module doc).
BASIS_BENEFIT = {"generic": .1, "model": .3, "profile": .15, "complement": .15}
# complement: a KB-curated pairs_with edge to something already installed — editor knowledge, no user data.
COMPLEMENT_CONFIDENCE = .3
AGENT_FIT = {"native": 1., "manual": .8, "adaptation_required": .4, "unknown": .5, "unsupported": 0.}
RISK = {"low": .05, "medium": .25, "high": .6}
ENGAGED_LABELS = {"install", "installed", "open", "opened", "preview"}
# Personal weight clamp shared with store._weight (one bound pair, RC-17): labels can move a kind/dim
# at most ±40 % so a handful of clicks never buries or floods a whole category.
PERSONAL_MIN, PERSONAL_MAX = .6, 1.4
# Saturation scale of the minutes benefit: B = 1 − exp(−weekly_minutes / 30); 30 min/week ≈ 63 %.
BENEFIT_SCALE_MINUTES = 30


def clamp_personal(value: float) -> float:
    return min(PERSONAL_MAX, max(PERSONAL_MIN, value))


def combine(benefit: float, confidence: float, p_effective: float, fit: float, cost: float,
            risk: float) -> tuple[float, float]:
    """(value, net) of the module formula; shared with evaluation's ablation recompute."""
    value = max(0., benefit * confidence * p_effective * fit) ** .25
    return value, value / (1 + cost) - risk


def basis(raw: dict) -> str:
    """problem | model | complement | profile | generic — which evidence the card stands on."""
    if raw.get("problem"):
        return "problem"
    if raw.get("kind") == "model":
        return "model"
    if raw.get("match_basis") == "complement":
        return "complement"
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
    if kind_basis == "complement":
        return COMPLEMENT_CONFIDENCE
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
    benefit_basis = kind_basis
    if kind_basis == "problem" and raw.get("kind") == "removal" and raw.get("resident_tokens"):
        # removing resident context is priced in the same unit as adding it (see cost below)
        benefit_basis = "resident_tokens"
        benefit = 1 - math.exp(-raw["resident_tokens"] / CONTEXT_TOKENS_PER_UNIT)
    elif kind_basis == "problem":
        unit = raw.get("unit_minutes")
        weekly = problem.get("weekly_count") or 0
        if unit is None:  # per-event cost unknown: rank on event frequency only (1 event = 1 unit), flagged
            benefit_basis, unit = "frequency_only", 1.
        weekly_saving = weekly * unit
        benefit = 1 - math.exp(-weekly_saving / BENEFIT_SCALE_MINUTES)
    else:
        benefit = BASIS_BENEFIT[kind_basis]
    confidence = _confidence(raw, inputs, kind_basis)

    alpha, beta = prior(raw)
    post = (memory.get("posteriors") or {}).get(raw["rec_key"]) or {}
    a, b = post.get("alpha", 0), post.get("beta", 0)
    p_effective = (alpha + a) / (alpha + beta + a + b)

    fusion = raw.get("fusion") or 0
    top = max_fusion if max_fusion else fusion
    targets = target_agents(raw, inputs)
    agent_fit = max((AGENT_FIT.get(agent_support(raw, a), .5) for a in targets), default=AGENT_FIT.get("unknown", .5))
    fit = .5 * (min(1., fusion / top) if top else 0) + .3 * agent_fit + .2 * _preference(raw, inputs)

    cost_in = raw.get("cost") or {}
    cost = (cost_in.get("setup_minutes") or 0) / 30 + (cost_in.get("context_tokens") or 0) / CONTEXT_TOKENS_PER_UNIT
    risk = RISK.get((raw.get("risk") or {}).get("level", "low"), .05)

    weights = memory.get("weights") or {}
    personal = (weights.get("kind") or {}).get(raw.get("kind"), 1) * (weights.get("dim") or {}).get(raw.get("dim"), 1)
    personal = clamp_personal(personal)
    decay = _decay(raw, memory)

    value, net = combine(benefit, confidence, p_effective, fit, cost, risk)
    priority = round(100 * max(0., net) * personal * decay, 2)
    r = 4
    return {"benefit": round(benefit, r), "benefit_basis": benefit_basis, "confidence": round(confidence, r),
            "p_effective": round(p_effective, r), "fit": round(fit, r), "value": round(value, r),
            "cost": round(cost, r), "risk": risk, "personal": round(personal, r),
            "decay": round(decay, r), "priority": priority,
            # unclipped net; engine gates utility ≤ 0 (net_non_positive), so ranked cards always have utility > 0
            "utility": round(net * personal * decay, 6)}

