"""Opt-in model parsing of a fixed local scope; all history artifacts remain ignored."""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from orbit_data.analysis_input import AnalysisScope, read_analysis

from orbit_backend.analytics.context import AnalysisContext
from orbit_backend.analytics.inputs import AnalysisInputBundle, Scope
from orbit_backend.analytics.semantic_cascade import (
    Budget,
    attach_cache,
    cache_identity,
    run_cascade,
)
from orbit_backend.analytics.semantic_cascade.provider import CodexProvider
from orbit_backend.analytics.service import analyze_bundle

ROOT = Path(__file__).resolve().parents[2]


def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(home, output, scope, budget, *, dry_run=False, cache_path=None, provider=None):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("real-history artifacts must stay under ignored .local/")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    raw = read_analysis(
        home,
        AnalysisScope(
            scope.display_timezone,
            from_ts=scope.from_ts,
            until_ts=scope.until_ts,
            project_ids=tuple(scope.project_ids) if scope.project_ids else None,
        ),
    )
    bundle = AnalysisInputBundle.from_dict(raw)
    context = AnalysisContext.select(bundle, scope)
    identity, candidates, skipped = cache_identity(context.events, context.main_ids, budget)
    save(
        output / "selection.json",
        {"input_fingerprint": identity, "candidates": candidates, "skipped": skipped},
    )
    if dry_run:
        summary = {
            "status": "selection_only",
            "candidate_messages": len(candidates),
            "skipped_messages": len(skipped),
            "model_calls": 0,
            "quality_limit": "no model or semantic-accuracy claim",
        }
    else:
        cache = (
            json.loads(Path(cache_path).read_text())
            if cache_path
            else run_cascade(
                context.events,
                context.main_ids,
                provider or CodexProvider(audit_directory=output / "audit"),
                budget,
            )
        )
        save(output / "cache.json", cache)
        projected = attach_cache(context.events, context.main_ids, cache)
        analysis = analyze_bundle(
            replace(
                bundle,
                sessions=context.sessions,
                events=projected,
                tool_calls=context.calls,
                model_calls=context.model_calls,
            ),
            scope,
            with_text=False,
        )
        save(output / "analytics.json", analysis)
        summary = {
            "status": "parsed"
            if cache["diagnostics"]["parsed_messages"] == len(candidates)
            else "partial",
            "semantic_cascade": cache["diagnostics"],
            "calls": cache["calls"],
            "instruction_messages": analysis["instruction"]["summary"]["effective_n"],
            "preference_evidence": analysis["preferences"]["evidence_summary"],
            "quality_limit": "input/evidence integrity; independent human semantic labels are still required",
        }
    summary["elapsed_seconds"] = time.perf_counter() - started
    save(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-ts", type=int)
    parser.add_argument("--until-ts", type=int)
    parser.add_argument("--project-id")
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    summary = run(
        args.home,
        args.output,
        Scope(
            from_ts=args.from_ts,
            until_ts=args.until_ts,
            project_ids=[args.project_id] if args.project_id else None,
            display_timezone="Asia/Shanghai",
        ),
        Budget(max_calls=args.max_calls, timeout_seconds=args.timeout),
        dry_run=args.dry_run,
        cache_path=args.cache,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if summary["status"] == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(main())
