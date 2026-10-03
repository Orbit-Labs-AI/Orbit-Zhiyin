"""EV-11: AI usage ledger accuracy over a FakeEngine (no model runs, tmp app.db).

Twelve cheap jobs run through a real ``AIService``; the suite checks that every engine call has
exactly one ``ai_usage`` row, job totals add up, the preview token estimate is close to the
reported input tokens, stored costs match ``ai.prices`` and the daily cap refuses before calling.
"""

from __future__ import annotations

import statistics
from types import SimpleNamespace

from ..contract import Check, EvalContext, SuiteResult

ID = "ai_ledger"
TITLE = "AI usage ledger accuracy"
EV = ("EV-11",)

TASK_ID = "eval.ledger"
MODEL = "claude-haiku-4-5"
N = 12
SCHEMA = {"type": "object", "required": ["answer"], "additionalProperties": False,
          "properties": {"answer": {"type": "string"}}}
GOALS = ["why do my tests fail", "summarize yesterday's sessions in one line",
         "which tool fails most often and how should I configure retries for it",
         "为什么构建总是失败", "list three habits", "explain the last correction",
         "rank my projects by edits " * 3, "what changed in the hooks setup",
         "pick one rule to add to CLAUDE.md", "短问题", "why", "describe a typical long session " * 4]


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))]


class _Engine:
    """FakeEngine variant that prices calls from ai.prices, like the CLI engines do."""

    def __init__(self, fake_cls, result_cls, estimate):
        self.inner = fake_cls({"*": self._answer})
        self.info, self.id, self.name = self.inner.info, "fake", "Fake"
        self.result_cls, self.estimate = result_cls, estimate
        self.calls: list[dict] = []

    def _answer(self, req):
        usage = {"input": (len(req.system) + len(req.prompt)) // 4, "cache_read": 0,
                 "cache_write": 0, "output": 7}
        cost = self.estimate(usage["input"], usage["output"], req.model)
        self.calls.append({"job_id": req.job_id, "usage": usage, "cost": cost})
        return self.result_cls(output={"answer": "ok"}, model_id=req.model, usage=usage,
                               cost_usd=cost, cost_source="price_table", latency_ms=1)

    def call(self, req):
        return self.inner.call(req)


def _rows(appdb, job_id=None) -> list:
    with appdb.read() as db:
        if job_id is None:
            return db.execute("SELECT * FROM ai_usage").fetchall()
        return db.execute("SELECT * FROM ai_usage WHERE job_id = ?", (job_id,)).fetchall()


def run(ctx: EvalContext) -> SuiteResult:
    try:
        from ...ai import prices, registry  # noqa: PLC0415
        from ...ai.engines import EngineResult, FakeEngine  # noqa: PLC0415
        from ...ai.errors import AIError  # noqa: PLC0415
        from ...ai.service import AIService  # noqa: PLC0415
        from ...appdb import AppDB  # noqa: PLC0415
        from ...services.events import EventBus  # noqa: PLC0415
    except ImportError as error:
        return SuiteResult(ID, skipped=f"ai service unavailable: {error}")
    home = ctx.tmp / "ai_ledger" / "orbit"
    gw = SimpleNamespace(home=home, appdb=AppDB(home / "app.db"), bus=EventBus(), reads=None)
    registry.register({"task_id": TASK_ID, "tier": "L2", "slot": "cheap", "system": "Return JSON.",
                       "schema": SCHEMA, "pack_items": [("goal", True)], "cache_ttl_s": 0,
                       "fallback": lambda pack, reason: {"answer": f"fallback:{reason}"}})
    svc = AIService(gw)
    try:
        engine = _Engine(FakeEngine, EngineResult, prices.estimate)
        svc._engines.clear()  # never probe the real claude / codex binaries
        svc.register_engine("fake", engine)
        svc.set_consent({"mode": "agent", "default_engine": "fake",
                         "settings": {"daily_usd_cap": 100.0, "slots": {"fake": {"cheap": MODEL}}},
                         "grants": {"fake": {"summary": True}}})
        return _measure(svc, engine, prices, AIError)
    finally:
        svc.close()
        gw.appdb.close()
        registry.unregister(TASK_ID)


def _submit(svc, goal: str) -> str:
    job_id = svc.submit(TASK_ID, {"goal": goal}, waiter=True, skip_preview=True)["job_id"]
    done = svc.runner.done.get(job_id)
    if done is not None:
        done.wait(10)
    return job_id


def _measure(svc, engine, prices, ai_error) -> SuiteResult:
    checks: list[Check] = []
    errors, jobs = [], []
    system = svc._task(TASK_ID)["system"]
    for goal in GOALS[:N]:
        preview = svc.preview(TASK_ID, {"goal": goal})
        estimate = preview["total_tokens"] + len(system) // 4  # what AIService._estimate shows
        job_id = _submit(svc, goal)
        jobs.append(job_id)
        reported = sum(c["usage"]["input"] for c in engine.calls if c["job_id"] == job_id)
        if reported:
            errors.append(abs(estimate - reported) / reported)

    rows = _rows(svc.appdb)
    per_job = [(len(_rows(svc.appdb, j)), sum(c["job_id"] == j for c in engine.calls)) for j in jobs]
    checks.append(Check("ai_ledger.one_row_per_call",
                        len(rows) == len(engine.calls) and all(a == b for a, b in per_job),
                        value=len(rows), threshold=len(engine.calls)))

    mismatched = []
    for job_id in jobs:
        usage = svc.job(job_id)["usage"]
        calls = [c for c in engine.calls if c["job_id"] == job_id]
        want_in = sum(c["usage"]["input"] for c in calls)
        want_out = sum(c["usage"]["output"] for c in calls)
        want_cost = sum(c["cost"] or 0 for c in calls)
        if (usage["input"], usage["output"]) != (want_in, want_out) or \
                abs((usage["cost_usd"] or 0) - want_cost) > 1e-9:
            mismatched.append(job_id)
    checks.append(Check("ai_ledger.job_totals", not mismatched, detail=", ".join(mismatched)))

    median = statistics.median(errors) if errors else None
    p90 = _p90(errors) if errors else None
    checks.append(Check("ai_ledger.estimate.median", median is not None and median <= 0.3,
                        value=median, threshold=0.3))
    checks.append(Check("ai_ledger.estimate.p90", p90 is not None and p90 <= 0.5,
                        value=p90, threshold=0.5))

    off = [r["job_id"] for r in rows if r["cost_usd"] is None or abs(r["cost_usd"] - prices.estimate(
        (r["input_tokens"] or 0) + (r["cache_read_tokens"] or 0) + (r["cache_write_tokens"] or 0),
        r["output_tokens"] or 0, r["model_id"])) > 1e-9]
    checks.append(Check("ai_ledger.cost_matches_prices", bool(rows) and not off,
                        detail=", ".join(off)))

    spent = svc.today_cost()
    checks.append(_cap_check(svc, engine, ai_error, "ai_ledger.cap.exhausted_refused", spent))
    next_cost = prices.estimate(svc.preview(TASK_ID, {"goal": GOALS[0]})["total_tokens"], 7, MODEL)
    checks.append(_cap_check(svc, engine, ai_error, "ai_ledger.cap.estimate_refused",
                             spent + (next_cost or 0) / 2))
    return SuiteResult(ID, checks, metrics={"jobs": len(jobs), "calls": len(engine.calls),
                                            "median_rel_error": median, "p90_rel_error": p90})


def _cap_check(svc, engine, ai_error, cid: str, cap: float) -> Check:
    svc.set_consent({"settings": {"daily_usd_cap": cap}})
    calls, rows = len(engine.calls), len(_rows(svc.appdb))
    try:
        _submit(svc, "one more question for the cap")
        refused = False
    except ai_error as error:
        refused = error.code == "budget_exhausted"
    ok = refused and len(engine.calls) == calls and len(_rows(svc.appdb)) == rows
    return Check(cid, ok, value=cap, detail=f"refused={refused} new_calls={len(engine.calls) - calls}")
