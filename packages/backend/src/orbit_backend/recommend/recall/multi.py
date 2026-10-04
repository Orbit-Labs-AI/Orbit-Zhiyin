"""Eleven-route recall with weighted RRF: the general, deterministic candidate generator.

recall_all(inputs, memory, catalog=None) builds problems, runs every route
(each isolated: a failing route becomes a diagnostic, never a failed run),
fuses ranks and merges payloads into RawCand dicts for gating and scoring.
"""

from .. import kb as kb_mod
from .. import problems as problems_mod
from ..ranking.gates import top_agent
from . import (
    catalog_route,
    feature_route,
    generative,
    graph,
    hashed,
    kb_route,
    models,
    subtract,
    templates,
)
from .fusion import fuse

# Weighted RRF (Cormack, Clarke & Büttcher, SIGIR 2009): score = Σ_route w_route / (k + rank).
# RRF_K = 60 is the constant from that paper. The per-route WEIGHTS are NOT calibrated: they
# encode a hand-set trust order (problem-specific KB / inventory evidence > templates > catalog >
# lexical / profile / graph > AI drafts > cold-start generic). evals.recommendation's ablation
# reports route deltas but the synthetic replay set is too small to fit weights; override per run
# with recall_all(weights=..., rrf_k=...) to test alternatives.
WEIGHTS = {"kb": 1., "subtract": 1., "template": .8, "catalog": .7, "model": .6, "hashed_lexical": .5,
           "profile": .4, "feature": .4, "graph": .4, "generative": .3, "generic": .2}
RRF_K = 60
# Whose payload wins when several routes return the same rec_key.
PAYLOAD_ORDER = ["kb", "template", "subtract", "catalog", "feature", "hashed_lexical", "model", "profile", "graph",
                 "generative", "generic"]
COLD_START_SESSIONS, MAX_CANDIDATES = 10, 200
_STATUS = {"active": 0, "below_threshold": 1, "insufficient": 2}


def _generic(rules, inputs: dict, memory: dict, taken: set[str]) -> tuple[list, dict]:
    """RC-11 cold start: broadly useful rules when there is too little history to diagnose."""
    if int((inputs.get("sessions") or {}).get("main") or 0) >= COLD_START_SESSIONS:
        return [], {}
    muted = set(memory.get("muted_kb_rules") or ())
    rows, payload = [], {}
    for rule in rules:
        if not rule.generic or rule.id in muted or f"kb:{rule.id}" in taken:
            continue
        key = f"generic:{rule.id}"
        payload[key] = kb_route.from_rule(rule, None, inputs, rec_key=key, match_basis="generic")
        rows.append((key, .5))
    return rows, payload


def _stronger(a: dict | None, b: dict | None) -> dict | None:
    if a is None or b is None:
        return a or b
    rank = lambda p: (-_STATUS[p["status"]], p["wilson_lo"], p["weekly_count"], p["key"])  # noqa: E731
    return a if rank(a) >= rank(b) else b


def _merge(key: str, payloads: dict[str, dict[str, dict]]) -> dict:
    holders = [route for route in PAYLOAD_ORDER if key in payloads.get(route, {})]
    cand = dict(payloads[holders[0]][key])
    sessions, signals = list(cand["evidence"]["session_uids"]), list(cand["evidence"]["signal_ids"])
    problem = cand["problem"]
    for route in holders[1:]:
        other = payloads[route][key]
        sessions += [uid for uid in other["evidence"]["session_uids"] if uid not in sessions]
        signals += [sid for sid in other["evidence"]["signal_ids"] if sid not in signals]
        # another route may tie the same item to a different problem (e.g. dense similarity to an
        # inventory fact); only a stronger problem of the same type replaces the primary one
        if problem is None or (other["problem"] or {}).get("type") == problem.get("type"):
            problem = _stronger(problem, other["problem"])
        if other.get("feature_overlap") and not cand.get("feature_overlap"):
            cand["feature_overlap"] = other["feature_overlap"]
    counts = dict(cand["evidence"]["counts"])
    counts["sessions"] = max(counts.get("sessions", 0), len(sessions))
    cand["evidence"] = {"session_uids": sessions[:50], "signal_ids": signals[:50], "counts": counts}
    cand["problem"] = problem
    return cand


def recall_all(inputs: dict, memory: dict | None = None, *, catalog=None, kb_path=None, features=None,
               weights: dict[str, float] | None = None, rrf_k: int = RRF_K,
               hashed_threshold: float = hashed.THRESHOLD) -> dict:
    """``features`` is the module-level features API (profile / match_items) when bound.

    ``weights`` overrides individual route weights (missing routes keep WEIGHTS); ``rrf_k`` and
    ``hashed_threshold`` override the fusion constant and the hashed-lexical cut-off."""
    route_weights = {**WEIGHTS, **(weights or {})}
    memory = memory or {}
    diagnostics: list[dict] = []
    problems = problems_mod.build(inputs, memory)
    profile = inputs.get("profile")
    if isinstance(profile, dict) and isinstance(profile.get("tags"), list):  # features.profile body
        inputs = {**inputs, "profile": feature_route.legacy_profile(profile)}
    rules, kb_version = kb_mod.load(kb_path)
    inventory = inputs.get("inventory")
    routes: dict[str, list] = {}
    payloads: dict[str, dict[str, dict]] = {}
    meta: dict = {}
    route_audit: dict = {}

    def run(name, call):
        try:
            rows, payload = call()
        except Exception as exc:  # isolate each route: partial recall beats no recall
            diagnostics.append({"source": name, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:300]})
            route_audit[name] = {"status": "failed", "count": None, "reason": type(exc).__name__}
            return
        route_audit[name] = {"status": "ok", "count": len(rows), "candidates": [
            {"rec_key": key, "raw_score": score, "kind": (payload.get(key) or {}).get("kind"),
             "evidence": (payload.get(key) or {}).get("evidence")} for key, score in rows]}
        if rows:
            routes[name], payloads[name] = rows, payload

    if features is not None:
        run("feature", lambda: feature_route.recall(problems, inputs, features, catalog, agent=top_agent(inputs),
                                                    meta=meta))
        if meta.get("feature_profile"):
            inputs = {**inputs, "profile": feature_route.legacy_profile(meta["feature_profile"])}
    run("kb", lambda: kb_route.recall(problems, rules, memory, inputs, inventory))
    run("catalog", lambda: catalog_route.recall(problems, inputs, catalog, diagnostics=diagnostics, meta=meta))
    if meta.get("profile_rows"):
        run("profile", lambda: (meta["profile_rows"], meta["profile_payload"]))
    if (meta.get("vector") or {}).get("status") != "ready":
        legacy = catalog_route.legacy_items() if catalog is None else ()
        run("hashed_lexical", lambda: hashed.recall(problems, rules, inputs, memory, legacy,
                                                     threshold=hashed_threshold))
    else:
        diagnostics.append({"source": "hashed_lexical", "status": "skipped", "reason": "catalog_vector_ready"})
    run("subtract", lambda: subtract.recall(problems, rules, inputs, memory))
    run("template", lambda: templates.recall(problems, rules, inputs, memory))
    run("model", lambda: models.recall(inputs))
    taken = {key for rows in routes.values() for key, _ in rows}
    run("generic", lambda: _generic(rules, inputs, memory, taken))
    pool = {key: cand for route in PAYLOAD_ORDER for key, cand in payloads.get(route, {}).items()}
    run("graph", lambda: graph.recall(rules, inputs, memory, pool))
    covered = {key: cand for route, payload in payloads.items() if route != "generic" for key, cand in payload.items()}
    run("generative", lambda: generative.recall(problems, rules, inputs, memory, covered))

    fused = fuse(routes, k=rrf_k, weights={route: route_weights.get(route, .2) for route in routes})
    candidates = []
    for item in fused[:MAX_CANDIDATES]:
        if not any(item.item_id in payloads.get(route, {}) for route in PAYLOAD_ORDER):
            continue  # a row without payload (e.g. graph re-score of an unknown key) cannot be shown
        cand = _merge(item.item_id, payloads)
        cand["routes"] = {route: {"rank": rank, "raw": item.route_scores[route]}
                          for route, rank in sorted(item.route_ranks.items())}
        cand["fusion"] = round(item.fusion_score, 8)
        candidates.append(cand)
    return {"problems": problems, "candidates": candidates,
            "routes": {route: len(rows) for route, rows in sorted(routes.items())},
            "diagnostics": diagnostics, "kb_version": kb_version, "catalog_generation": meta.get("generation"),
            "profile": inputs.get("profile"),
            "audit": {"routes": route_audit, "unique_fused": len(fused),
                      "fusion_limit": MAX_CANDIDATES,
                      "dropped_by_fusion_limit": [i.item_id for i in fused[MAX_CANDIDATES:]],
                      "feature": meta.get("feature_audit"), "catalog": meta.get("catalog_audit")}}
