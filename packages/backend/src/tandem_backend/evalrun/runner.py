"""Run evaluation suites and decide pass/fail (EV-12).

Each suite runs in its own temporary directory. A suite score is the share of its checks
that passed; the run score is the unweighted mean over non-skipped suites. A run passes
when no non-skipped suite has a failed check and, if given, ``score >= fail_under``.
Skipped suites never fail a run; a crash becomes a failed ``<id>.crashed`` check.
"""

from __future__ import annotations

import secrets
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from . import registry
from . import store as eval_store
from .contract import Check, EvalContext, SuiteResult


def _now() -> int:
    return int(time.time() * 1000)


def new_run_id() -> str:
    return secrets.token_hex(8)


def resolve(suite_ids: list[str] | str) -> list[str]:
    known = registry.ids()
    ids = known if suite_ids == "all" else list(dict.fromkeys(suite_ids))
    unknown = [s for s in ids if s not in known]
    if unknown:
        raise ValueError(f"unknown suite: {', '.join(unknown)}")
    if not ids:
        raise ValueError("no suites selected")
    return ids


def run_suite(suite_id: str, *, params: dict | None = None, home: Path | None = None,
              real: bool = False) -> SuiteResult:
    with tempfile.TemporaryDirectory(prefix=f"tandem-eval-{suite_id}-") as tmp:
        ctx = EvalContext(tmp=Path(tmp), home=home, params=dict(params or {}), real=real)
        try:
            result = registry.get(suite_id).run(ctx)
            if not isinstance(result, SuiteResult):
                raise TypeError(f"run() returned {type(result).__name__}, not SuiteResult")
        except Exception as exc:
            return SuiteResult(suite_id, [Check(f"{suite_id}.crashed", False,
                                                detail=f"{type(exc).__name__}: {exc}")])
    result.suite = suite_id
    return result


def _suite_dict(result: SuiteResult) -> dict:
    score = result.score
    return {"suite": result.suite, "skipped": result.skipped,
            "score": None if score is None else round(score, 4),
            "checks": [asdict(c) for c in result.checks], "metrics": result.metrics}


def run(suite_ids: list[str] | str, *, fail_under: float | None = None,
        params: dict | None = None, home: Path | None = None, real: bool = False,
        store=None, progress: Callable[[str, dict | None], None] | None = None,
        run_id: str | None = None) -> dict:
    """Run suites and return a RunReport; ``store`` (AppDB-like) records the history."""
    ids = resolve(suite_ids)
    if fail_under is not None and not 0 <= fail_under <= 1:
        raise ValueError("fail_under must be within 0..1")
    params = dict(params or {})
    run_id = run_id or new_run_id()
    started = _now()
    if store is not None:
        eval_store.queue(store, run_id, ids, fail_under, params, started, status="running")
    try:
        suites = []
        for suite_id in ids:
            if progress:
                progress(suite_id, None)
            row = _suite_dict(run_suite(suite_id, params=params, home=home, real=real))
            suites.append(row)
            if progress:
                progress(suite_id, row)
        report = summarize(run_id, started, suites, fail_under)
    except BaseException as exc:
        if store is not None:
            eval_store.fail(store, run_id, f"{type(exc).__name__}: {exc}", _now())
        raise
    if store is not None:
        eval_store.finish(store, report)
    return report


def summarize(run_id: str, started: int, suites: list[dict], fail_under: float | None) -> dict:
    scored = [s["score"] for s in suites if not s["skipped"] and s["score"] is not None]
    score = round(sum(scored) / len(scored), 4) if scored else None
    failed = any(not c["passed"] for s in suites if not s["skipped"] for c in s["checks"])
    below = fail_under is not None and score is not None and score < fail_under
    return {"run_id": run_id, "started_at": started, "finished_at": _now(), "status": "done",
            "passed": not failed and not below, "score": score, "suites": suites,
            "fail_under": fail_under}
