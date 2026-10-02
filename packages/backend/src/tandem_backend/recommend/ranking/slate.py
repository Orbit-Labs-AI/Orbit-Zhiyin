"""MMR slate with quotas (RC-05 / RC-15): one card per need, a short, varied list.

Within one problem a second candidate of the same dimension is folded into the
first card's `alternatives` instead of taking a slot.
"""

from .rank import basis

LAMBDA = .8
PER_PROBLEM = 2
KIND_CAPS = {"skill": 2, "removal": 2, "builtin": 1, "generate": 1}
GENERIC_CAP = 3


def _tags(cand: dict) -> set[str]:
    problem = cand.get("problem") or {}
    return {f"kind:{cand.get('kind')}", f"dim:{cand.get('dim')}", f"problem:{problem.get('type')}",
            *(cand.get("tags") or [])[:20]}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.


def _priority(cand: dict) -> float:
    return (cand.get("score") or {}).get("priority", 0.)


def _utility(cand: dict) -> float:
    score = cand.get("score") or {}
    return score.get("utility", score.get("priority", 0.) / 100)


def order_key(cand: dict) -> tuple:
    """(-priority, -utility, rec_key): utility breaks ties among clipped-to-zero priorities."""
    return -_priority(cand), -_utility(cand), cand["rec_key"]


def select(cands: list[dict], limit: int = 30) -> list[dict]:
    """Pick and rank passing candidates; non-selected ones get `excluded` set in place."""
    pool = sorted(cands, key=order_key)
    driven = [c for c in pool if basis(c) != "generic"]
    if driven:
        for c in pool:
            if basis(c) == "generic":
                c["excluded"] = "generic_suppressed"
        pool = driven
    generic_only = not driven
    top = max((abs(_utility(c)) for c in pool), default=0.) or 1.

    def relevance(c):  # unclipped priority / pool max, so clipped-to-zero priorities still order
        return _utility(c) / top

    tags = {c["rec_key"]: _tags(c) for c in pool}

    chosen: list[dict] = []
    seen: set[str] = set()
    per_problem: dict[str, list[dict]] = {}
    per_kind: dict[str, int] = {}
    remaining = list(pool)
    max_sim = {c["rec_key"]: 0. for c in pool}
    while remaining and len(chosen) < limit and not (generic_only and len(chosen) >= GENERIC_CAP):
        best = max(remaining, key=lambda c: LAMBDA * relevance(c) - (1 - LAMBDA) * max_sim[c["rec_key"]])
        remaining.remove(best)
        key, kind = best["rec_key"], best.get("kind")
        pid = (best.get("problem") or {}).get("problem_id")
        if key in seen:
            best["excluded"] = "duplicate"
            continue
        same_dim = next((s for s in per_problem.get(pid, []) if s.get("dim") == best.get("dim")), None) if pid else None
        if same_dim is not None:
            same_dim["alternatives"] = [*(same_dim.get("alternatives") or []), {
                "rec_key": key, "title": best.get("title"), "kind": kind, "priority": _priority(best)}]
            best["excluded"] = f"folded:{same_dim['rec_key']}"
            continue
        if pid and len(per_problem.get(pid, [])) >= PER_PROBLEM:
            best["excluded"] = "cap:problem"
            continue
        if per_kind.get(kind, 0) >= KIND_CAPS.get(kind, limit):
            best["excluded"] = f"cap:{kind}"
            continue
        seen.add(key)
        per_kind[kind] = per_kind.get(kind, 0) + 1
        if pid:
            per_problem.setdefault(pid, []).append(best)
        chosen.append(best)
        for c in remaining:
            max_sim[c["rec_key"]] = max(max_sim[c["rec_key"]], _jaccard(tags[c["rec_key"]], tags[key]))
    for c in remaining:
        c["excluded"] = "cap:slate"
    for i, c in enumerate(chosen, 1):
        c["rank"] = i
        c["excluded"] = None
    return chosen
