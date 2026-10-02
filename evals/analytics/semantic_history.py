"""Opt-in local real-data E2E: raw import -> SQLite -> CLI JSON -> real ASGI app.

Reuses the reference ledger's exact cutoff/exclusions. Never publishes source text.
Output must stay under the repository's ignored .local directory.
"""
import argparse
import contextlib
import io
import json
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tandem_backend.analytics.common import human
from tandem_backend.analytics.inputs import Scope, legacy_bundle, select
from tandem_backend.analytics.service import analyze_store
from tandem_backend.api import create_app
from tandem_backend.cli import main
from tandem_backend.store import Store


def verify(reference_db, output):
    private = (Path(__file__).resolve().parents[2] / ".local").resolve()
    output = Path(output).resolve()
    if not output.is_relative_to(private):
        raise ValueError("Real history outputs must remain under ignored .local/")
    output.mkdir(parents=True, exist_ok=True)
    database = output / "reimport.sqlite"
    if database.exists():
        raise ValueError("Choose a fresh output directory to verify a clean import")
    with sqlite3.connect(f"file:{Path(reference_db).resolve()}?mode=ro", uri=True) as conn:
        policies = [(r[0], json.loads(r[1])) for r in conn.execute("SELECT source_root,data FROM sample_policies")]
    if not policies or any(not p.get("before") for _, p in policies):
        raise ValueError("A fixed reference snapshot is required")
    timings = {}
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        for source, policy in policies:
            args = ["--db", str(database), "import", "--codex-home", source, "--before", policy["before"]]
            for sid in policy.get("exclude", []):
                args += ["--exclude-session", sid]
            main(args)
    timings["raw_import_seconds"] = time.perf_counter() - started
    json_path = output / "analytics.json"
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        main(["--db", str(database), "analytics", "--display-timezone", "Asia/Shanghai", "--output", str(json_path)])
    timings["cli_full_analysis_seconds"] = time.perf_counter() - started
    cli = json.loads(json_path.read_text())
    store = Store(database)
    api_times = {}
    with TestClient(create_app(database)) as client:
        for family in ("tasks", "preferences"):
            started = time.perf_counter()
            response = client.get(f"/v1/analytics/{family}", params={"display_timezone": "Asia/Shanghai"})
            api_times[family] = time.perf_counter() - started
            assert response.status_code == 200
            assert response.json()[family]["records"] == cli[family]["records"]
    b = legacy_bundle(store)
    sessions, events, _, _, _ = select(b, Scope())
    mains = {s["session_uid"] for s in sessions if s["kind"] == "main"}
    eligible = {e["event_uid"] for e in events if human(e, mains)}
    for task in cli["tasks"]["records"]:
        assert set(task["human_evidence_ids"]) <= eligible
        for field in ("domain", "task_type"):
            for evidence in task["label_evidence"][field].values():
                assert {item["event_uid"] for item in evidence} <= eligible
    for pref in cli["preferences"]["records"]:
        assert {p["event_uid"] for p in pref["preference_evidence"]} <= eligible
    reference = analyze_store(Store(reference_db), Scope(display_timezone="Asia/Shanghai"), with_text=False)
    # Freeze the same historical sample: parser refresh must not silently add newer observations.
    assert cli["overview"]["counts"] == reference["overview"]["counts"]
    assert cli["tasks"]["records"] == reference["tasks"]["records"]
    assert cli["preferences"]["records"] == reference["preferences"]["records"]
    summary = {"status": "passed", "pipeline": "raw logs -> fresh SQLite -> CLI JSON -> FastAPI ASGI (no mocks)",
        "cutoffs": [p["before"] for _, p in policies], "counts": cli["overview"]["counts"],
        "task_summary": cli["tasks"]["summary"], "preference_summary": cli["preferences"]["summary"],
        "semantic_coverage": cli["preferences"]["coverage"], "timings": timings, "api_seconds": api_times,
        "checks": ["API/CLI family records equal", "evidence belongs to eligible human messages",
                   "fresh import agrees with reference snapshot", "private records remain local"],
        "quality_limit": "Evidence integrity and reproducibility, not human semantic acceptance"}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.reference_db, args.output), ensure_ascii=False, indent=2))
