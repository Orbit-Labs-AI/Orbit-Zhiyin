"""Fresh probe contrasts written after v0.5, reported as a regression guard.

Adapter over ``evaluation.pipeline_benchmark(dataset='probe')``. The bar is the currently
measured result (all 12 cases correct, no false positive or negative), i.e. any drop fails.
"""

from __future__ import annotations

from ..contract import EvalContext, SuiteResult
from .pipeline import checks_for, summary

ID = "probe"
TITLE = "Pipeline probe (regression guard)"
EV = ("EV-03", "EV-12")
EXPECTED_CASES = 12


def run(ctx: EvalContext) -> SuiteResult:
    from ...evaluation.pipeline import pipeline_benchmark

    result = pipeline_benchmark(dataset="probe")
    return SuiteResult(ID, checks_for(result, ID, EXPECTED_CASES), metrics=summary(result))
