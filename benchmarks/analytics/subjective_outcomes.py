"""Measure subjective-outcome performance on synthetic records."""

import argparse
import json
import time
import tracemalloc
from statistics import median

from evals.analytics.fixtures import synthetic_events

from tandem_backend.analytics.inputs import AnalysisInputBundle
from tandem_backend.analytics.outcome_subjective import analyze_subjective_outcomes
from tandem_backend.analytics.service import analyze_bundle


def performance(sizes, repeats):
    analyze_subjective_outcomes(synthetic_events(20), {"s"})
    reports = []
    for size in sizes:
        events = synthetic_events(size)
        durations = []
        for _ in range(repeats):
            start = time.perf_counter()
            report = analyze_subjective_outcomes(events, {"s"})
            durations.append(time.perf_counter() - start)
            assert report["effective_n"] == size // 2
        b = AnalysisInputBundle([{"session_uid": "s", "kind": "main", "root_uid": "s"}], events, [], [],
                                {k: {"status": "available"} for k in ("events", "tool_calls", "model_calls")})
        start = time.perf_counter()
        full = analyze_bundle(b, with_text=False)
        full_seconds = time.perf_counter() - start
        assert full["overview"]["subjective_outcomes"]["effective_n"] == size // 2
        reports.append({"events": size, "feedback": size // 2, "seconds": durations,
                        "median_seconds": median(durations), "events_per_second": size / median(durations),
                        "analytics_no_text_seconds": full_seconds})
    # Memory is measured separately: tracemalloc materially slows down Python execution.
    events = synthetic_events(max(sizes))
    tracemalloc.start()
    report = analyze_subjective_outcomes(events, {"s"})
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert report["effective_n"] == max(sizes) // 2
    return {"samples": reports, "peak_family_allocations_bytes": peak,
            "memory_excludes_input": True, "timing_excludes_input_generation": True,
            "latency_threshold": None, "note": "Hardware-dependent measurements; no production SLA or concurrency claim."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if any(n < 2 for n in args.sizes) or args.repeats < 1:
        parser.error("sizes must be >= 2 and repeats >= 1")
    print(json.dumps(performance(args.sizes, args.repeats), ensure_ascii=False, indent=2, allow_nan=False))
