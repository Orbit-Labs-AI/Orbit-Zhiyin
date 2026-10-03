"""Constructed Codex schema drift, damaged/half-written JSONL, and mtime recovery."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from orbit_data.validation.integrity import section_digests

from orbit_backend.analytics.diagnostics import diagnostics, terminal_text
from orbit_backend.analytics.inputs import Scope
from orbit_backend.analytics.service import analyze_store
from orbit_backend.cli import demo_home
from orbit_backend.data_access.store import CanonicalStore
from orbit_backend.recommend.catalog import load_catalog
from orbit_backend.recommend.service import recommend

from .robustness import save
from .robustness_invariants import validate_result

ROOT = Path(__file__).resolve().parents[2]


def run(output):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Fault replay output must remain under ignored .local/")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    loaded = load_catalog(
        items=json.loads((ROOT / "evals/recommendation/fixtures/reviewed-skills.json").read_text())[
            "items"
        ]
    )
    report = {
        "schema_version": "native-faults-v1",
        "status": "running",
        "cases": [],
        "source": "constructed Codex transcripts",
        "model_calls": 0,
    }

    def measure(
        name,
        source,
        home,
        *,
        expected_unparsed=0,
        expected_unknown=0,
        expected_pending=0,
        layers=None,
        expected_counts=None,
        force_rebuild=False,
        expected_integrity="ok",
    ):
        before = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*.jsonl")
        }
        with Store(home) as store:
            imported = ImportService(store).import_source(ImportRequest("codex", source))
            if force_rebuild:
                store.rebuild()
            verified = store.verify()
            unknown = store.db.execute(
                "SELECT count(*) FROM event WHERE kind='unknown'"
            ).fetchone()[0]
            pending = store.db.execute(
                "SELECT count(*) FROM raw_record r JOIN file_record f USING(record_uid) "
                "WHERE native_type='pending_tail' AND disposition='ignored' "
                "AND json_extract(note,'$.reason')='incomplete_tail_retained_in_L0'"
            ).fetchone()[0]
        scope = Scope()
        reader = CanonicalStore(home)
        analysis = analyze_store(reader, scope, with_text=False)
        recs = recommend(
            analysis, context={"agent": "codex"}, catalog=loaded.items, family="skills"
        )
        relational = validate_result(
            reader.analysis_bundle(scope), scope, analysis, recs, home=home
        )
        after = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*.jsonl")
        }
        checks = {
            "unparsed_retained": imported["current_unparsed"] == expected_unparsed,
            "unknown_events_retained": unknown == expected_unknown,
            "incomplete_tail_retained_in_l0": pending == expected_pending,
            "neighbouring_human_messages_survive": analysis["overview"]["counts"]["human_messages"]
            == 5,
            "source_unchanged_by_import": before == after,
            "relational_invariants": relational["status"] == "passed",
            "source_integrity": verified["integrity"] == expected_integrity,
        }
        if layers is not None:
            checks["logical_layers_equal"] = layers == section_digests(home)
            checks["no_changed_files"] = imported["changed"] == 0
        if expected_counts is not None:
            checks["exact_file_copy_preserves_analysis_counts"] = (
                analysis["overview"]["counts"] == expected_counts
            )
        folder = output / name
        folder.mkdir()
        grouped = diagnostics(analysis, recs, loaded.items)
        save(folder / "diagnostics.json", grouped)
        (folder / "diagnostics.txt").write_text(terminal_text(grouped) + "\n", encoding="utf-8")
        save(folder / "recommendations.json", recs)
        save(folder / "invariants.json", relational)
        save(folder / "import.json", imported)
        save(folder / "verify.json", verified)
        row = {
            "case": name,
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "unparsed": imported["current_unparsed"],
            "unknown_events": unknown,
            "pending_tail_records": pending,
            "analysis_counts": analysis["overview"]["counts"],
        }
        report["cases"].append(row)
        save(output / "summary.json", report)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row

    try:
        for name, tail, unparsed, unknown in (
            ("baseline", "", 0, 0),
            (
                "unknown_schema",
                json.dumps(
                    {
                        "type": "future_unknown_kind",
                        "timestamp": "2026-01-01T00:00:12Z",
                        "payload": {"new_field": [1, 2]},
                    }
                )
                + "\n",
                0,
                1,
            ),
            ("malformed_jsonl", "{bad\n", 1, 0),
            ("half_written", '{"type":"event_msg","payload":', 0, 0),
        ):
            source = demo_home(output / f"source-{name}")
            path = source / "sessions/demo-0.jsonl"
            original = path.read_text()
            path.write_text(original + tail)
            home = output / f"data-{name}"
            measured = measure(
                name,
                source,
                home,
                expected_unparsed=unparsed,
                expected_unknown=unknown,
                expected_pending=1 if name == "half_written" else 0,
            )
            if name == "half_written":
                path.write_text(original)
                measure("completion_recovery", source, home)
            if name == "baseline":
                layers = section_digests(home)
                stat = path.stat()
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
                measure("mtime_only", source, home, layers=layers)
                path.with_name("demo-0-copy.jsonl").write_bytes(path.read_bytes())
                measure(
                    "exact_file_copy", source, home, expected_counts=measured["analysis_counts"]
                )
                path.unlink()
                measure(
                    "missing_original_rebuild",
                    source,
                    home,
                    expected_counts=measured["analysis_counts"],
                    force_rebuild=True,
                    expected_integrity="partial",
                )
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return 0 if run(args.output)["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
