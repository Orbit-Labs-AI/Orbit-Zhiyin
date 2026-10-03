"""Constructed Codex contrasts through the full import → analysis → recommendation chain.

Adapter over ``evaluation.pipeline_benchmark()`` (development split). Thresholds are the
ones in ``tests/regression/test_evaluation_pipeline.py``: 34 cases, every case correct,
zero false positives and false negatives per metric, every evidence check true.
"""

from __future__ import annotations

from ..contract import Check, EvalContext, SuiteResult

ID = "pipeline"
TITLE = "Pipeline contrasts (development)"
EV = ("EV-03", "EV-12")
DATASET = "development"
EXPECTED_CASES = 34


def checks_for(result: dict, prefix: str, expected_cases: int | None) -> list[Check]:
    cases, correct = result["cases"], result["correct"]
    checks = []
    if expected_cases is not None:
        checks.append(Check(f"{prefix}.cases", cases == expected_cases, cases, expected_cases,
                            "dataset size"))
    checks.append(Check(f"{prefix}.correct", correct == cases, correct / cases if cases else None,
                        1.0, f"{correct}/{cases} cases match labels"))
    for key, metric in sorted(result["metrics"].items()):
        for kind in ("false_positive", "false_negative"):
            checks.append(Check(f"{prefix}.{key}.{kind}", metric[kind] == 0, metric[kind], 0,
                                f"{key} precision={metric['precision']} recall={metric['recall']}"))
    broken = [r["case"] for r in result["results"] if not all(r["checks"].values())]
    checks.append(Check(f"{prefix}.evidence_checks", not broken, len(broken), 0,
                        ", ".join(broken[:5])))
    return checks


def summary(result: dict) -> dict:
    return {"version": result["version"], "dataset_sha256": result["dataset_sha256"],
            "split": result["split"], "cases": result["cases"], "correct": result["correct"],
            "metrics": result["metrics"]}


def run(ctx: EvalContext) -> SuiteResult:
    from ...evaluation.pipeline import pipeline_benchmark

    result = pipeline_benchmark(dataset=DATASET)
    return SuiteResult(ID, checks_for(result, ID, EXPECTED_CASES), metrics=summary(result))
