"""Recommendation quality: time-split replay with / without AI rerank, gate and score-term
ablations with the RC-09 / RC-17 contribution report, and exposure rates from app.db.

Fixtures are ``evals/recommendation/fixtures/{replay,timeline}-cases.json`` (repo only; the
suite skips without them). The rerank pass uses ``FakeEngine``, so no model runs. Exposure
rates read ``params.appdb`` or, with ``--real``, ``<home>/app.db``; ablation deltas are
reported in metrics, never asserted (EV-05.2 findings).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..contract import Check, EvalContext, SuiteResult

ID = "recommend"
TITLE = "Recommendation evaluation"
EV = ("EV-05", "EV-05.1", "EV-05.2", "EV-12")
HIT_AT_3, NDCG_AT_3 = .5, .7  # HitRate@3 ≥ 0.5 per plan; nDCG@3 calibrated on the fixture (0.94)


def _fixtures(ctx: EvalContext) -> Path | None:
    if ctx.params.get("fixtures_dir"):
        dirs = [Path(ctx.params["fixtures_dir"])]
    else:
        dirs = [p / "evals" / "recommendation" / "fixtures" for p in Path(__file__).resolve().parents]
    return next((d for d in dirs if (d / "timeline-cases.json").is_file()), None)


def _appdb(ctx: EvalContext) -> Path | None:
    if ctx.params.get("appdb"):
        return Path(ctx.params["appdb"])
    if ctx.real and ctx.home is not None and (ctx.home / "app.db").is_file():
        return ctx.home / "app.db"
    return None


def _exposure(path: Path) -> dict:
    from orbit_backend.recommend.evaluation import exposure_report

    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return exposure_report(conn)
    finally:
        conn.close()


def run(ctx: EvalContext) -> SuiteResult:
    fixtures = _fixtures(ctx)
    if fixtures is None:
        return SuiteResult(ID, skipped="evals/recommendation/fixtures not found")
    from orbit_backend.ai.engines import FakeEngine
    from orbit_backend.recommend import evaluation as ev

    cases = json.loads((fixtures / "replay-cases.json").read_text(encoding="utf-8"))["cases"]
    timeline = json.loads((fixtures / "timeline-cases.json").read_text(encoding="utf-8"))
    users = ev.link_cases(timeline["users"], cases)
    horizon = timeline.get("horizon_days", ev.HORIZON_DAYS)
    base = ev.time_split(users, horizon_days=horizon)
    engine = FakeEngine({"rerank.fit": {"items": []}})  # neutral judge: every card "unknown"
    reranked = ev.time_split(users, horizon_days=horizon, rerank=ev.engine_rerank(engine))
    with ev.ablated(**ev.BUNDLES["RC-17"]) as build:
        no_rc17 = ev.time_split(users, horizon_days=horizon, build=build)

    hit, ndcg = base["hit_rate@3"], base["ndcg@3"]
    rr_hit, rr_ndcg = reranked["hit_rate@3"], reranked["ndcg@3"]
    on, off = base["repeat_na@3"], no_rc17["repeat_na@3"]
    checks = [
        Check(f"{ID}.split.hit_rate@3", hit >= HIT_AT_3, hit, HIT_AT_3, f"{base['cutoffs']} cutoffs"),
        Check(f"{ID}.split.ndcg@3", ndcg >= NDCG_AT_3, ndcg, NDCG_AT_3),
        Check(f"{ID}.rerank.no_regression", rr_hit >= hit and rr_ndcg >= ndcg, rr_ndcg, ndcg,
              f"rerank calls={len(engine.requests)}"),
        Check(f"{ID}.rc17.repeat_na", on is not None and off is not None and on < off, on, off,
              "repeat not-applicable@3 with RC-17 on (value) vs off (threshold)"),
    ]
    metrics = {"split": {k: v for k, v in base.items() if k != "per_cutoff"},
               "rerank": {k: v for k, v in reranked.items() if k != "per_cutoff"},
               "rc17_off": {k: v for k, v in no_rc17.items() if k != "per_cutoff"},
               "per_cutoff": base["per_cutoff"]}
    if ctx.params.get("ablation", True):
        metrics["ablation"] = ev.ablation_report(cases, users)
    if (path := _appdb(ctx)) is not None:
        exposure = _exposure(path)
        checks.append(Check(f"{ID}.exposure.na_rate", exposure["na_rate_ok"], exposure["max_na_rate"],
                            ev.NA_RATE_MAX, f"{exposure['rated_groups']} groups with n ≥ {ev.MIN_SHOWN}; "
                            f"downweight: {', '.join(exposure['downweight']) or '-'}"))
        metrics["exposure"] = exposure
    return SuiteResult(ID, checks, metrics=metrics)
