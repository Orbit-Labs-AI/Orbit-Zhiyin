"""Hand-written readability contrasts: the checker must accept and reject as labelled.

Adapter over ``evaluation.readability.benchmark()``: one check per case.
"""

from __future__ import annotations

from ..contract import Check, EvalContext, SuiteResult

ID = "readability"
TITLE = "Readability contrasts"
EV = ("EV-09", "EV-12")


def run(ctx: EvalContext) -> SuiteResult:
    from ...evaluation.readability import benchmark

    result = benchmark()
    checks = [Check(f"{ID}.{r['case']}", bool(r["matches"]), r["evaluation"].get("score"), None,
                    f"expected checks_passed={r['expected_checks_passed']}")
              for r in result["results"]]
    return SuiteResult(ID, checks, metrics={"version": result["version"],
                                            "cases": result["cases"], "correct": result["correct"]})
