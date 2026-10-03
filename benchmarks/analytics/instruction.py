"""Repeatable synthetic throughput/memory probe. No user data or network required."""

import argparse
import json
import platform
import statistics
import time
import tracemalloc
from pathlib import Path

from orbit_backend.analytics.instruction import (
    extract_instruction_constraints,
    resolve_instruction_scope,
    structure,
    summarize_control_patterns,
)


def benchmark(sizes=(100, 1000, 10000), repeats=3):
    results = []
    for size in sizes:
        events = [
            {"event_uid": str(i), "session_uid": "s", "seq": i, "ts": i,
             "kind": "message.user", "actor": "human",
             "text": f"只修改 src/file_{i}.py。请运行 pytest 并报告结果。不要推送。",
             "attrs": {"origin": "human", "task_id": "t"}} for i in range(size)
        ]
        durations = []
        for _ in range(repeats):
            start = time.perf_counter()
            rows = extract_instruction_constraints(events, main_ids={"s"})
            summary = summarize_control_patterns(rows)
            structures = [structure(e) for e in events]
            resolution = resolve_instruction_scope(rows, {"session_uid": "s", "task_id": "t"})
            durations.append(time.perf_counter() - start)
            assert summary["message_n"] == size and summary["effective_n"] == size
            assert len(structures) == size and len(resolution["active"]) == 4 * size
            assert not resolution["conflicts"]
        tracemalloc.start()
        memory_rows = extract_instruction_constraints(events, main_ids={"s"})
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del memory_rows
        median = statistics.median(durations)
        results.append({"messages": size, "repeats": repeats,
                        "median_seconds": round(median, 4),
                        "slowest_seconds": round(max(durations), 4),
                        "messages_per_second": round(size / median),
                        "extraction_peak_mib": round(peak / 1024 / 1024, 2)})
    return {"environment": {"python": platform.python_version(), "system": platform.system(),
                            "machine": platform.machine()},
            "scope": "extract + summarize + structure + resolve, synthetic distinct file targets",
            "memory_scope": "extraction only, input allocation excluded",
            "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=15,
                        help="Fail if any measured 10k-or-smaller batch median exceeds this budget")
    args = parser.parse_args()
    result = benchmark()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    assert all(r["median_seconds"] <= args.max_seconds for r in result["results"]), "Performance budget exceeded"
