"""EV-15: realtime detection replay. Delegates to ``tandem_backend.realtime.replay.run_cases``.

``run_cases()`` returns ``{"cases": [{"id", "passed", "detail"}], "detect_latency_s":
{"failing", "just_finished", "awaiting_approval"}, "false_alarms": int}``.
"""

from __future__ import annotations

import importlib

from ..contract import Check, EvalContext, SuiteResult

ID = "realtime"
TITLE = "Realtime state detection replay"
EV = ("EV-15",)

# 待验证: placeholder latency budgets in seconds until real sessions are measured.
LATENCY_BUDGET_S = {"failing": 30.0, "awaiting_approval": 30.0, "just_finished": 150.0}


def run(ctx: EvalContext) -> SuiteResult:
    try:
        replay = importlib.import_module("tandem_backend.realtime.replay")
    except ImportError:
        replay = None
    run_cases = getattr(replay, "run_cases", None)
    if run_cases is None:
        return SuiteResult(ID, skipped="realtime package not installed")
    out = run_cases()
    checks = [Check(f"realtime.case.{c['id']}", bool(c.get("passed")), detail=str(c.get("detail") or ""))
              for c in out.get("cases") or []]
    alarms = int(out.get("false_alarms") or 0)
    checks.append(Check("realtime.false_alarms", alarms == 0, value=alarms, threshold=0))
    latency = out.get("detect_latency_s") or {}
    for key, budget in LATENCY_BUDGET_S.items():
        value = latency.get(key)
        if value is not None:
            checks.append(Check(f"realtime.latency.{key}", value <= budget, value=value,
                                threshold=budget))
    return SuiteResult(ID, checks, metrics={"cases": len(out.get("cases") or []),
                                            "false_alarms": alarms, **{f"latency_{k}": v
                                                                        for k, v in latency.items()}})
