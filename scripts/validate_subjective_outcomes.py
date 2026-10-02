"""Repeatable quality/performance checks and opt-in real-data import -> CLI -> API checks.

Run with PYTHONPATH=src python scripts/validate_subjective_outcomes.py --help.
Real history is copied by a read-only SQLite backup; no raw content is printed.
"""

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path
from statistics import median

from fastapi.testclient import TestClient

from tandem_backend.analytics.inputs import AnalysisInputBundle, legacy_bundle
from tandem_backend.analytics.outcome_subjective import analyze_subjective_outcomes
from tandem_backend.analytics.service import analyze_bundle
from tandem_backend.api import create_app
from tandem_backend.store import Store, import_codex

ROOT = Path(__file__).resolve().parents[1]


def synthetic_events(size):
    """A worst-case long task with many delivery versions, each followed by feedback."""
    return [{"event_uid": f"e{i}", "session_uid": "s", "seq": i, "ts": i,
             "turn_uid": f"t{i // 2}", "kind": "message.assistant" if i % 2 == 0 else "message.user",
             "actor": "assistant" if i % 2 == 0 else "human", "text": "交付" if i % 2 == 0 else "可以了",
             "attrs": {"task_id": "task", "phase": "final" if i % 2 == 0 else None,
                       "origin": "assistant" if i % 2 == 0 else "human"}} for i in range(size)]


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


def quality():
    path = ROOT / "tests/fixtures/subjective-outcome-quality.json"
    cases = json.loads(path.read_text())
    errors, positives, detected, true_positive = [], 0, 0, 0
    for case in cases:
        events = synthetic_events(2)
        events[1]["text"] = case["text"]
        result = analyze_subjective_outcomes(events, {"s"})
        feedback = result["feedback"]
        observed = [feedback[0]["user_acceptance"], feedback[0]["user_confirmed_completion"],
                    bool(feedback[0]["rework_feedback"])] if feedback else None
        wanted = case["expected"]
        positives += wanted is not None
        detected += observed is not None
        true_positive += wanted is not None and observed is not None
        if observed != wanted:
            errors.append({"id": case["id"], "expected": wanted, "observed": observed})
    report = {"cases": len(cases), "exact_match": len(cases) - len(errors), "errors": errors,
              "detection_precision": true_positive / detected if detected else None,
              "detection_recall": true_positive / positives if positives else None,
              "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "ground_truth": "Synthetic expectations authored for this rule contract; no independently labeled real feedback."}
    assert not errors, json.dumps(errors, ensure_ascii=False)
    return report


def real_flow(source, codex_home, output):
    """Re-import raw real logs into a copy, keeping the recorded cutoff and exclusions."""
    source, codex_home = source.resolve(), codex_home.resolve()
    if not source.is_file() or not codex_home.is_dir():
        raise ValueError("Real database and Codex source directory must already exist")
    snapshot = output / "history-copy.sqlite"
    if snapshot.resolve() == source:
        raise ValueError("Never use the source database as an output")
    before_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        policies = list(src.execute("SELECT source_root,data FROM sample_policies"))
        if not any(Path(root).resolve() == codex_home and json.loads(data).get("before") for root, data in policies):
            raise ValueError("A fixed sample policy for this source is required; this script does not widen history")
        with sqlite3.connect(snapshot) as dest:
            src.backup(dest)
    store = Store(snapshot)
    # Invalidate only the copy's import cache so the test actually parses raw logs.
    with store.connect() as conn:
        conn.execute("UPDATE imports SET signature = ''")
    start = time.perf_counter()
    imported = import_codex(store, codex_home)
    import_seconds = time.perf_counter() - start
    assert imported.imported > 0, "No real source file was parsed"
    with store.connect() as conn:
        after_policies = list(conn.execute("SELECT source_root,data FROM sample_policies"))
    assert sorted(tuple(row) for row in after_policies) == sorted(policies)
    b = legacy_bundle(store)
    start = time.perf_counter()
    expected = analyze_bundle(b, with_text=False)
    analysis_seconds = time.perf_counter() - start
    full_output = output / "real-analytics.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    command = [sys.executable, "-m", "tandem_backend", "--db", str(snapshot), "analytics", "--no-text", "--output", str(full_output)]
    start = time.perf_counter()
    subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    cli_seconds = time.perf_counter() - start
    cli = json.loads(full_output.read_text())
    assert cli == json.loads(json.dumps(expected))
    start = time.perf_counter()
    with TestClient(create_app(snapshot)) as client:
        api = client.get("/v1/analytics/overview")
        assert api.status_code == 200
        assert api.json()["overview"]["subjective_outcomes"] == expected["overview"]["subjective_outcomes"]
        projects = client.get("/v1/analytics/projects")
        assert projects.status_code == 200
        assert [p["subjective_outcomes"] for p in projects.json()["projects"]] == [p["subjective_outcomes"] for p in expected["projects"]]
        selected = next((s for s in expected["sessions"] if s["subjective_outcomes"]["feedback"]), expected["sessions"][0])
        detail = client.get("/v1/analytics/sessions/" + selected["session_uid"])
        assert detail.status_code == 200
        assert detail.json()["session"]["subjective_outcomes"] == selected["subjective_outcomes"]
    api_seconds = time.perf_counter() - start
    # Every emitted evidence reference is checked against the selected source ledger.
    lookup = {e["event_uid"]: e for e in b.events}
    checked = delivery_checked = 0
    for session in expected["sessions"]:
        for delivery in session["subjective_outcomes"]["deliveries"] or []:
            source_event = lookup[delivery["delivery_event_uid"]]
            assert source_event["kind"] == "message.assistant"
            assert source_event["attrs"]["phase"] in ("final", "final_answer")
            delivery_checked += 1
        for f in session["subjective_outcomes"]["feedback"] or []:
            event = lookup[f["event_uid"]]
            assert event["attrs"]["origin"] == "human" and event["kind"] == "message.user"
            if f["delivery_event_uid"]:
                d = lookup[f["delivery_event_uid"]]
                assert d["session_uid"] == event["session_uid"] and d["seq"] < event["seq"]
                assert d["attrs"]["phase"] in ("final", "final_answer")
            checked += 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_digest
    return {"stored_counts": store.counts(), "selected_counts": expected["overview"]["counts"],
            "sample_boundary": expected["sample_boundary"], "source_db_sha256": before_digest,
            "source_db_unchanged": True, "sample_policies_unchanged": True, "raw_parser_exercised": imported.imported > 0,
            "import_counts": {k: v for k, v in imported.to_dict().items() if isinstance(v, (int, float))},
            "summary": expected["overview"]["subjective_outcomes"], "evidence_references_checked": checked, "delivery_references_checked": delivery_checked,
            "seconds": {"import": import_seconds, "analysis_no_text": analysis_seconds,
                        "cli_process": cli_seconds, "api_three_requests": api_seconds},
            "checks": ["raw reimport", "ledger adapter", "CLI equals engine", "API overview/project/detail equals engine", "evidence references"],
            "quality_limit": "Plumbing/evidence validation, not independently labeled real-world semantic accuracy."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/subjective-outcome-validation")
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--real-db", type=Path)
    parser.add_argument("--codex-home", type=Path)
    args = parser.parse_args()
    if any(n < 2 for n in args.sizes) or args.repeats < 1:
        parser.error("sizes must be >= 2 and repeats >= 1")
    if bool(args.real_db) != bool(args.codex_home):
        parser.error("--real-db and --codex-home must be supplied together")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".local"):
        parser.error("outputs must stay inside this checkout's ignored .local directory")
    output.mkdir(parents=True, exist_ok=True)
    report = {"runtime": {"python": platform.python_version(), "platform": platform.platform(), "processor": platform.machine()},
              "quality": quality(), "performance": performance(args.sizes, args.repeats),
              "real_e2e": {"status": "not_requested"}}
    (output / "validation-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    if args.real_db:
        report["real_e2e"] = real_flow(args.real_db, args.codex_home, output)
    (output / "validation-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
