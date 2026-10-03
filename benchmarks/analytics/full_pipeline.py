"""Opt-in staged timing of the full analysis pipeline on synthetic input; never a CI gate.

Stages (exclusive wall time, nested stages are subtracted from their parent):

read        canonical mode only: ``read_analysis`` on a synthetic ``orbit.db``
bundle      ``AnalysisInputBundle.from_dict``
select      ``AnalysisContext.select`` (statistical members, linked context)
session_rows ``compute_row_cores`` (per-session rows, possibly in worker processes) excluding text representation
text        task text representation (only with ``--with-text``)
lexical     ``lexical_analysis``
statistics  ``statistical_analysis``
aggregate   remaining ``analyze_context`` work (families, tools, workflow, projects)
products    remaining ``build_products`` work (journeys, feedback, trends, profile)
json        ``json.dumps`` of the product snapshot
history     persisting the snapshot through ``analytics.history.recorded``

Usage::

    uv run python -m benchmarks.analytics.full_pipeline --sizes 500 1000 --repeats 1
    uv run python -m benchmarks.analytics.full_pipeline --sizes 500 --canonical --profile
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import platform
import pstats
import statistics
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

from orbit_backend.analytics import context as context_module
from orbit_backend.analytics import history as history_module
from orbit_backend.analytics import service as service_module
from orbit_backend.analytics.inputs import AnalysisInputBundle, Scope
from orbit_backend.analytics.products import lexical as lexical_module
from orbit_backend.analytics.products import service as products_module
from orbit_backend.analytics.products import statistics as statistics_module

from .synthetic import TIMEZONE, build_canonical_home, generate_bundle

STAGES = (
    "read",
    "bundle",
    "select",
    "session_rows",
    "text",
    "lexical",
    "statistics",
    "aggregate",
    "products",
    "json",
    "history",
)


class StageTimer:
    """Exclusive timings: time spent in a nested stage is not counted for its parent."""

    def __init__(self):
        self.totals, self._stack = dict.fromkeys(STAGES, 0.0), []

    @contextmanager
    def stage(self, name):
        start = time.perf_counter()
        self._stack.append(0.0)
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            nested = self._stack.pop()
            self.totals[name] += elapsed - nested
            if self._stack:
                self._stack[-1] += elapsed

    def wrap(self, name, function):
        def timed(*args, **kwargs):
            with self.stage(name):
                return function(*args, **kwargs)

        return timed


@contextmanager
def instrumented(timer):
    """Temporarily wrap module attributes; the analysis code itself is unchanged."""
    targets = [
        (context_module, "select", "select"),
        (service_module, "compute_row_cores", "session_rows"),
        (service_module, "representation", "text"),
        (lexical_module, "lexical_analysis", "lexical"),
        (statistics_module, "statistical_analysis", "statistics"),
        (products_module, "analyze_context", "aggregate"),
    ]
    with ExitStack() as stack:
        for module, attribute, stage in targets:
            original = getattr(module, attribute)
            setattr(module, attribute, timer.wrap(stage, original))
            stack.callback(setattr, module, attribute, original)
        yield


def run_once(source, scope, with_text, history_home):
    timer = StageTimer()
    with instrumented(timer):
        if isinstance(source, Path):
            from orbit_backend.data_access.store import CanonicalStore

            with timer.stage("read"):
                raw = CanonicalStore(source).read_bundle(scope, include_native=False)
        else:
            raw = source
        with timer.stage("bundle"):
            bundle = AnalysisInputBundle.from_dict(raw)
        with timer.stage("products"):
            products = products_module.build_products(bundle, scope, with_text=with_text)
        with timer.stage("json"):
            payload = json.dumps(products, ensure_ascii=False, default=str)
        with timer.stage("history"):
            history_module.recorded(
                SimpleNamespace(home=history_home),
                "products",
                {"benchmark": True},
                lambda: products,
            )
    events = len(raw["events"] or [])
    return timer.totals, {
        "events": events,
        "sessions": len(raw["sessions"]),
        "json_bytes": len(payload.encode()),
    }


def profile_once(source, scope, with_text, history_home, lines=30):
    profiler = cProfile.Profile()
    profiler.enable()
    run_once(source, scope, with_text, history_home)
    profiler.disable()
    buffer = io.StringIO()
    pstats.Stats(profiler, stream=buffer).sort_stats("cumulative").print_stats(lines)
    # Relative paths keep the report shareable and free of the local checkout location.
    return buffer.getvalue().replace(str(Path(__file__).resolve().parents[2]) + os.sep, "")


def benchmark(sizes, repeats=3, *, with_text=False, canonical=False, profile=False, seed=7):
    scope = Scope(display_timezone=TIMEZONE)
    rows, profile_text = [], None
    with tempfile.TemporaryDirectory(prefix="orbit-bench-") as scratch:
        scratch = Path(scratch)
        for size in sizes:
            setup_start = time.perf_counter()
            if canonical:
                source = build_canonical_home(scratch / f"home-{size}", size, seed, scratch)
            else:
                source = generate_bundle(size, seed)
            setup = time.perf_counter() - setup_start
            history_home = scratch / f"history-{size}"
            history_home.mkdir()
            run_once(source, scope, with_text, history_home)  # warm imports and caches
            samples, shape = [], None
            for _ in range(repeats):
                totals, shape = run_once(source, scope, with_text, history_home)
                samples.append(totals)
            stages = {
                name: {
                    "median_seconds": statistics.median(s[name] for s in samples),
                    "seconds": [s[name] for s in samples],
                }
                for name in STAGES
            }
            total = [sum(s.values()) for s in samples]
            rows.append(
                {
                    "sessions_requested": size,
                    **shape,
                    "setup_seconds": setup,
                    "total_median_seconds": statistics.median(total),
                    "total_seconds": total,
                    "stages": stages,
                }
            )
            if profile and size == max(sizes):
                profile_text = profile_once(source, scope, with_text, history_home)
    return {
        "benchmark": "analysis full pipeline (synthetic)",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "mode": "canonical orbit.db via read_analysis" if canonical else "in-memory bundle",
        "with_text": with_text,
        "repeats": repeats,
        "seed": seed,
        "timing": "exclusive wall time per stage, median over repeats after one warm-up run; "
        "setup (generation or ingest) excluded",
        "results": rows,
        "profile": profile_text.splitlines() if profile_text else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sizes", type=int, nargs="+", default=[500, 1000, 2500], help="main sessions per run"
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--with-text", action="store_true", help="include text representation")
    parser.add_argument(
        "--canonical",
        action="store_true",
        help="ingest synthetic sources into orbit.db and time read_analysis",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="cProfile one run of the largest size, top 30 by cumulative time",
    )
    parser.add_argument("--output", type=Path, help="also write the JSON report here")
    args = parser.parse_args(argv)
    report = benchmark(
        args.sizes,
        args.repeats,
        with_text=args.with_text,
        canonical=args.canonical,
        profile=args.profile,
        seed=args.seed,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
