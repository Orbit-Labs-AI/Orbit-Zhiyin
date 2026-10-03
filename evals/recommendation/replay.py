"""Offline replay (EV-05.1 style) on synthetic cases: does the slate put the right fix on top?

Each case = {id, inputs (minimal RecInputs), memory?, relevant:{key: grade 1..3}} or a negative
case {…, relevant: {}, expect: {status, ranked?, max_problem_cards?}} that must produce no
(problem-driven) recommendation. Labels are independent of the engine's priority table (see the
fixture note); the set is synthetic and small, so results are regression signals only.
A relevant key is an exact rec_key, or a selector such as
`type=permission_friction&kind=permission_rule` matched against problem type,
kind, dim and source origin (so cases survive KB id renames).
Fixtures are fictional; no user history is read.

    uv run python -m evals.recommendation.replay [--fixtures PATH] [--ablate ROUTE]
"""

import argparse
import json
import math
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures") / "replay-cases.json"
K = 3
DISCLAIMER = "合成集，仅回归：样例为虚构，样本量小，指标不代表真实用户效果"
EMPTY_MEMORY = {"now": 0, "state": {}, "labels": {}, "muted_kb_rules": [], "muted_problem_types": [],
                "weights": {}, "posteriors": {}, "level": None, "settings": {}}


def _fields(cand: dict) -> dict:
    problem = cand.get("problem") or {}
    return {"rec_key": cand.get("rec_key"), "type": problem.get("type") or cand.get("problem_type"),
            "kind": cand.get("kind"), "dim": cand.get("dim"), "origin": (cand.get("source") or {}).get("origin")}


def _matches(selector: str, cand: dict) -> bool:
    fields = _fields(cand)
    if "=" not in selector:
        return selector == fields["rec_key"]
    return all(fields.get(k) == v for k, v in (part.split("=", 1) for part in selector.split("&")))


def gains(top: list[dict], relevant: dict[str, int]) -> list[int]:
    """Graded gain per position; each relevant key is credited once."""
    unused, out = dict(relevant), []
    for cand in top:
        hit = max((k for k in unused if _matches(k, cand)), key=lambda k: unused[k], default=None)
        out.append(unused.pop(hit) if hit else 0)
    return out


def ndcg(gain: list[int], relevant: dict[str, int], k: int = K) -> float:
    dcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gain[:k]))
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.


def load_cases(path: Path = FIXTURES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _default_build():
    from orbit_backend.recommend.engine import build_slate
    return build_slate


def check_negative(slate: dict, expect: dict) -> list[str]:
    """Violations of a negative case's expectation (empty list = pass)."""
    ranked = [c for c in slate["candidates"] if c.get("rank")]
    problem_cards = [c for c in ranked if c.get("problem")]
    errors = []
    if "status" in expect and slate["status"] != expect["status"]:
        errors.append(f"status {slate['status']} != {expect['status']}")
    if "ranked" in expect and len(ranked) != expect["ranked"]:
        errors.append(f"ranked {len(ranked)} != {expect['ranked']}")
    if "max_problem_cards" in expect and len(problem_cards) > expect["max_problem_cards"]:
        errors.append(f"problem cards {[c['rec_key'] for c in problem_cards]}")
    return errors


def run_replay(cases: list[dict], build=None, k: int = K) -> dict:
    build = build or _default_build()
    per_case, negatives = [], []
    for case in cases:
        slate = build(case["inputs"], EMPTY_MEMORY | (case.get("memory") or {}))
        top = [c for c in slate["candidates"] if c.get("rank")][:k]
        if "expect" in case:
            errors = check_negative(slate, case["expect"])
            negatives.append({"id": case["id"], "status": slate["status"], "top3": [c["rec_key"] for c in top],
                              "passed": not errors, "errors": errors})
            continue
        gain = gains(top, case["relevant"])
        per_case.append({"id": case["id"], "status": slate["status"], "top3": [c["rec_key"] for c in top],
                         "hit": any(gain), "ndcg": round(ndcg(gain, case["relevant"], k), 4)})
    n = len(per_case) or 1
    return {"hit_rate@3": round(sum(c["hit"] for c in per_case) / n, 4),
            "ndcg@3": round(sum(c["ndcg"] for c in per_case) / n, 4),
            "negative_pass_rate": round(sum(c["passed"] for c in negatives) / len(negatives), 4) if negatives else None,
            "n_positive": len(per_case), "n_negative": len(negatives), "disclaimer": DISCLAIMER,
            "per_case": per_case, "negatives": negatives}


def ablation(cases: list[dict], drop_route: str, build=None) -> dict:
    """Metric deltas when candidates reached only through `drop_route` are removed (not asserted)."""
    build = build or _default_build()
    from orbit_backend.recommend.recall.multi import recall_all

    def recall_without(inputs, memory, catalog=None):
        rr = recall_all(inputs, memory, catalog=catalog)
        keep = [c for c in rr["candidates"] if set(c.get("routes") or {}) - {drop_route}]
        return {**rr, "candidates": keep}

    base = run_replay(cases, build)
    dropped = run_replay(cases, lambda i, m: build(i, m, recall=recall_without))
    return {"route": drop_route, **{m: round(dropped[m] - base[m], 4) for m in ("hit_rate@3", "ndcg@3")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--ablate", action="append", default=[], help="route name to drop (repeatable)")
    args = parser.parse_args()
    cases = load_cases(args.fixtures)
    result = run_replay(cases)
    result["ablation"] = [ablation(cases, route) for route in args.ablate]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
