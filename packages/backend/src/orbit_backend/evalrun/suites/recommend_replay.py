"""Offline recommendation replay over synthetic cases: hit_rate@3 and nDCG@3.

Adapter over ``evals/recommendation/replay.py`` (the module behind
``tests/recommend/test_replay_eval.py``); thresholds match that calibrated test:
hit_rate@3 >= 0.9 and nDCG@3 >= 0.7. Skips when the repository's ``evals/`` tree is not
present (an installed wheel) or the multi-route recall is missing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ..contract import Check, EvalContext, SuiteResult

ID = "recommend_replay"
TITLE = "Recommendation replay"
EV = ("EV-05.1", "EV-12")
HIT_AT_3, NDCG_AT_3 = 0.9, 0.7


def _replay_path(ctx: EvalContext) -> Path | None:
    if ctx.params.get("replay_path"):
        return Path(ctx.params["replay_path"])
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "evals" / "recommendation" / "replay.py"
        if candidate.is_file():
            return candidate
    return None


def run(ctx: EvalContext) -> SuiteResult:
    path = _replay_path(ctx)
    if path is None or not path.is_file():
        return SuiteResult(ID, skipped="evals/recommendation/replay.py not found")
    if importlib.util.find_spec("orbit_backend.recommend.recall.multi") is None:
        return SuiteResult(ID, skipped="multi-route recall not installed")
    spec = importlib.util.spec_from_file_location("orbit_eval_replay", path)
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    result = replay.run_replay(replay.load_cases())
    hit, ndcg = result["hit_rate@3"], result["ndcg@3"]
    weakest = sorted(result["per_case"], key=lambda c: c["ndcg"])[:3]
    detail = ", ".join(f"{c['id']}={c['ndcg']}" for c in weakest)
    return SuiteResult(ID, [Check(f"{ID}.hit_rate@3", hit >= HIT_AT_3, hit, HIT_AT_3),
                            Check(f"{ID}.ndcg@3", ndcg >= NDCG_AT_3, ndcg, NDCG_AT_3,
                                  f"weakest: {detail}")],
                       metrics={"hit_rate@3": hit, "ndcg@3": ndcg, "cases": len(result["per_case"])})
