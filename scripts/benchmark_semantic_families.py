"""Opt-in repeatable throughput benchmark; no private inputs, no fixed CI timing assertion."""
import argparse
import json
import platform
import statistics
import time
import tracemalloc

from tandem_backend.analytics.inputs import AnalysisInputBundle
from tandem_backend.analytics.service import analyze_bundle


def workload(count):
    sessions, events = [], []
    for i in range(count):
        sid = f"s-{i // 20}"
        if i % 20 == 0:
            sessions.append({"session_uid": sid, "root_uid": sid, "kind": "main", "project_id": "synthetic", "started_at": i})
        text = "请修复代码，并编写报告" if i % 4 == 0 else "以后这个项目都用中文" if i % 4 == 1 else "请继续解释修改原因"
        events.append({"event_uid": f"e-{i}", "session_uid": sid, "seq": i % 20, "ts": i,
                       "kind": "message.user", "actor": "human", "text": text, "attrs": {"origin": "human"}})
    return AnalysisInputBundle(sessions, events, [], [],
        {k: {"status": "available"} for k in ("sessions", "events", "projects", "tool_calls", "model_calls")})


def benchmark(sizes=(100, 1000, 10000), repeats=3):
    analyze_bundle(workload(20), with_text=False)
    rows = []
    for size in sizes:
        data, durations = workload(size), []
        for _ in range(repeats):
            start = time.perf_counter()
            result = analyze_bundle(data, with_text=False)
            durations.append(time.perf_counter() - start)
            assert result["effective_samples"]["human_messages"] == size
        # Separate memory sampling from the uninstrumented timing measurements.
        tracemalloc.start()
        analyze_bundle(data, with_text=False)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        duration = statistics.median(durations)
        rows.append({"events": size, "sessions": len(data.sessions), "seconds": durations,
                     "median_seconds": duration, "events_per_second": size / duration,
                     "peak_python_allocations_mib": peak / 1024**2,
                     "task_count": result["tasks"]["summary"]["task_count"],
                     "preference_count": result["preferences"]["summary"]["record_count"]})
    return {"python": platform.python_version(), "platform": platform.platform(), "repeats": repeats,
            "scope": "analyze_bundle including both families, with_text=False; input creation/JSON serialization excluded",
            "memory": "tracemalloc peak Python allocations, not process RSS", "results": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.sizes, args.repeats), ensure_ascii=False, indent=2))
