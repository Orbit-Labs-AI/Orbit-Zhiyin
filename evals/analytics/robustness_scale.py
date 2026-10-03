"""Read-only 20/100/all native-session scale sweep with grouped diagnostics."""

import argparse
import gc
import json
import resource
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from tandem_backend.analytics.diagnostics import diagnostics, terminal_text
from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.service import recommend

from .robustness import save
from .robustness_invariants import validate_result

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "evals/recommendation/fixtures/reviewed-skills.json"


def run(home, output, *, sizes=(20, 100), progress=None):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Scale output must remain under ignored .local/")
    with sqlite3.connect(
        f"{(Path(home) / 'tandem.db').resolve().as_uri()}?mode=ro", uri=True
    ) as db:
        native = [
            dict(zip(("session_uid", "kind", "root_uid"), row, strict=True))
            for row in db.execute(
                "SELECT session_uid,kind,root_uid FROM session ORDER BY started_at DESC,session_uid"
            )
        ]
    if not native:
        raise ValueError("Scale sweep requires an existing nonempty canonical database")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    loaded = load_catalog(items=json.loads(CATALOG.read_text())["items"])
    report = {
        "schema_version": "analytics-scale-v1",
        "status": "running",
        "model_calls": 0,
        "native_session_count": len(native),
        "native_kinds": dict(Counter(s["kind"] for s in native)),
        "cases": [],
        "limitations": [
            "Native sessions include review sessions; they are not all main human sessions.",
            "Peak RSS is the process high-water mark, not an isolated per-case measurement.",
            "Scaling is measured for this local history; it does not establish utility or semantic accuracy.",
        ],
    }
    save(output / "summary.json", report)
    try:
        counts = sorted({min(n, len(native)) for n in sizes} | {len(native)})
        for count in counts:
            selected = native[:count]
            scope = Scope(
                root_session_uids=[s["session_uid"] for s in selected], include_children=False
            )
            started = time.perf_counter()
            bundle = CanonicalStore(home).analysis_bundle(scope)
            read_seconds = time.perf_counter() - started
            analysis = analyze_bundle(bundle, scope, with_text=False, with_recommendations=False)
            analyzed_seconds = time.perf_counter() - started - read_seconds
            recommendations = recommend(
                analysis, context={"agent": "codex"}, catalog=loaded.items, family="skills"
            )
            invariant = validate_result(bundle, scope, analysis, recommendations, home=home)
            selected_ids = {s["session_uid"] for s in selected}
            if not {s["session_uid"] for s in bundle.sessions} <= selected_ids:
                raise RuntimeError("Scale selection admitted an unrequested native session")
            folder = output / f"sessions-{count}"
            folder.mkdir()
            grouped = diagnostics(analysis, recommendations, loaded.items)
            save(folder / "diagnostics.json", grouped)
            (folder / "diagnostics.txt").write_text(terminal_text(grouped) + "\n", encoding="utf-8")
            save(folder / "recommendations.json", recommendations)
            save(folder / "invariants.json", invariant)
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            row = {
                "requested_native_sessions": count,
                "requested_kinds": dict(Counter(s["kind"] for s in selected)),
                "reader_sessions": len(bundle.sessions),
                "reader_events": len(bundle.events or []),
                "analysis_counts": analysis["overview"]["counts"],
                "scope": asdict(scope),
                "read_seconds": read_seconds,
                "analysis_seconds": analyzed_seconds,
                "total_seconds": time.perf_counter() - started,
                "process_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
                "status": invariant["status"],
                "diagnostics": str(folder / "diagnostics.json"),
            }
            report["cases"].append(row)
            save(output / "summary.json", report)
            if progress:
                progress({k: v for k, v in row.items() if k != "scope"})
            del analysis, bundle, recommendations, grouped
            gc.collect()
        report["status"] = (
            "passed" if all(r["status"] == "passed" for r in report["cases"]) else "failed"
        )
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        save(output / "summary.json", report)
        raise
    save(output / "summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(
        args.home,
        args.output,
        progress=lambda r: print(json.dumps(r, ensure_ascii=False), flush=True),
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
