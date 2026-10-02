"""Rebuild a declared local Codex selection in full/reverse and incremental order."""

import argparse
import hashlib
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store
from tandem_data.validation.integrity import invariants, section_digests

from tandem_backend.analytics.diagnostics import diagnostics, terminal_text
from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.service import analyze_store
from tandem_backend.data_access.store import CanonicalStore
from tandem_backend.recommend.catalog import load_catalog
from tandem_backend.recommend.service import recommend

from .robustness_invariants import validate_result

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "evals/recommendation/fixtures/reviewed-skills.json"
CORE_SECTIONS = (
    "overview",
    "sessions",
    "tools",
    "workflow",
    "projects",
    "bottleneck_features",
    "tasks",
    "preferences",
    "instruction",
    "work_graph",
    "lexical",
    "statistics",
)


def save(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def source_selection(home):
    database = (Path(home) / "tandem.db").resolve()
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as db:
        sources = db.execute(
            "SELECT source_id,root_path FROM source WHERE agent='codex' AND enabled=1 ORDER BY source_id"
        ).fetchall()
        result = []
        for sid, source_root in sources:
            paths = tuple(
                Path(source_root) / r[0]
                for r in db.execute(
                    "SELECT relative_path FROM source_file WHERE source_id=? ORDER BY relative_path",
                    (sid,),
                )
            )
            if paths:
                result.append((Path(source_root), paths))
    if not result:
        raise ValueError("No explicitly indexed/enabled Codex source selection")
    return result


def file_hashes(selections):
    result = {}
    for _root, paths in selections:
        for path in paths:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            result[str(path)] = digest.hexdigest()
    return result


def comparison_core(result):
    """Only the last scan's time and batch size are operational, not history facts."""
    values = {k: result[k] for k in CORE_SECTIONS}
    values["sessions"] = []
    for session in result["sessions"]:
        row = {**session, "coverage": dict(session.get("coverage", {}))}
        scans = row["coverage"].get("source_scans")
        if scans is not None:
            row["coverage"]["source_scans"] = {
                **scans,
                "scans": [
                    {k: v for k, v in scan.items() if k not in ("scanned_at", "indexed_files")}
                    for scan in scans.get("scans", [])
                ],
            }
        values["sessions"].append(row)
    return values


def core(result):
    digest = hashlib.sha256()
    for part in json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False).iterencode(
        comparison_core(result)
    ):
        digest.update(part.encode())
    return digest.hexdigest()


def scan_metadata(result):
    rows = {}
    for session in result["sessions"]:
        for scan in session.get("coverage", {}).get("source_scans", {}).get("scans", []):
            row = {k: scan.get(k) for k in ("source_id", "scanned_at", "indexed_files")}
            rows[json.dumps(row, sort_keys=True)] = row
    return list(rows.values())


def rebuild(home, selections, *, batches=1, reverse=False, progress=None):
    progress = progress or (lambda _x: None)
    imports = []
    started = time.perf_counter()
    with Store(home) as store:
        service = ImportService(store, progress=progress)
        for root, files in selections:
            ordered = tuple(reversed(files)) if reverse else files
            size = max(1, (len(ordered) + batches - 1) // batches)
            for offset in range(0, len(ordered), size):
                result = service.import_source(
                    ImportRequest("codex", root, files=ordered[offset : offset + size])
                )
                imports.append(result)
                if result["capture_errors"] or result["cancelled"]:
                    raise RuntimeError("Native rebuild incomplete; no partial run can pass")
    return {"seconds": time.perf_counter() - started, "imports": imports}


def _run(home, output, scope, *, batches=3, progress=None, reuse_imports=False):
    if not isinstance(batches, int) or isinstance(batches, bool) or not 2 <= batches <= 10:
        raise ValueError("batches must be between 2 and 10")
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("real native replays must remain under ignored .local/")
    if reuse_imports:
        selection = json.loads((output / "selection.json").read_text())
        if selection["scope"] != asdict(scope):
            raise ValueError("Recheck must use exactly the original selection scope")
    else:
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
    selections = source_selection(home)
    before = file_hashes(selections)
    if reuse_imports and before != selection["source_hashes"]:
        raise ValueError("Frozen source files changed; cannot reuse the imported databases")
    save(
        output / "selection.json",
        {
            "scope": asdict(scope),
            "files": list(before),
            "source_hashes": before,
            "meaning": "existing indexed allowlist only; source files remain read-only",
        },
    )
    loaded = load_catalog(items=json.loads(CATALOG.read_text())["items"])
    products = {}
    report = {
        "schema_version": "native-robustness-v1",
        "scope": asdict(scope),
        "status": "running",
        "model_calls": 0,
        "reuse_imports": reuse_imports,
        "comparison_exclusions": [
            "sessions[].coverage.source_scans.scans[].scanned_at",
            "sessions[].coverage.source_scans.scans[].indexed_files",
        ],
        "cases": {},
        "limitations": [
            "Native equivalence does not establish semantic accuracy or causal utility."
        ],
    }
    save(output / "summary.json", report)
    for name, count, reverse in (("full_reverse", 1, True), ("incremental", batches, False)):
        folder = output / name
        if reuse_imports:
            stage = json.loads((folder / "import.json").read_text())
        else:
            folder.mkdir()
            stage = rebuild(
                folder / "data", selections, batches=count, reverse=reverse, progress=progress
            )
            save(folder / "import.json", stage)
        integrity = invariants(folder / "data")
        save(folder / "integrity.json", integrity)
        if integrity["problems"] or integrity.get("verify", {}).get("integrity") != "ok":
            raise RuntimeError(f"{name} data integrity failed")
        layers = section_digests(folder / "data")
        save(folder / "layers.json", layers)
        store = CanonicalStore(folder / "data")
        result = analyze_store(store, scope, with_text=False)
        recommendations = recommend(
            result, context={"agent": "codex"}, catalog=loaded.items, family="skills"
        )
        grouped = diagnostics(result, recommendations, loaded.items)
        save(folder / "diagnostics.json", grouped)
        (folder / "diagnostics.txt").write_text(terminal_text(grouped) + "\n", encoding="utf-8")
        save(folder / "recommendations.json", recommendations)
        relational = validate_result(
            store.analysis_bundle(scope), scope, result, recommendations, home=folder / "data"
        )
        save(folder / "relational-invariants.json", relational)
        products[name] = {
            "core": core(result),
            "layers": layers,
            "cards": recommendations["recommendations"],
            "scan_metadata": scan_metadata(result),
        }
        report["cases"][name] = {
            "status": relational["status"],
            "seconds": stage["seconds"],
            "raw_records": integrity["records"],
            "events": integrity["events"],
            "invariants": "passed",
            "relational_invariants": relational["status"],
            "diagnostics": str(folder / "diagnostics.json"),
        }
        save(output / "summary.json", report)
        if progress:
            progress({"case": name, "stage": "complete", "seconds": round(stage["seconds"], 2)})
    full, incremental = products["full_reverse"], products["incremental"]
    differences = [
        name
        for name in set(full["layers"]) | set(incremental["layers"])
        if full["layers"].get(name) != incremental["layers"].get(name)
    ]
    report["differential"] = {
        "layer_differences": sorted(differences),
        "core_equal": full["core"] == incremental["core"],
        "recommendation_cards_equal": full["cards"] == incremental["cards"],
        "operational_scan_metadata": {
            "full_reverse": full["scan_metadata"],
            "incremental": incremental["scan_metadata"],
            "meaning": "last scan timestamp and last batch file count are retained and reported separately",
        },
    }
    prior = incremental["layers"]
    duplicate_stage = rebuild(output / "incremental/data", selections, batches=1, progress=progress)
    repeated = section_digests(output / "incremental/data")
    report["idempotence"] = {
        "logical_layers_equal": prior == repeated,
        "changed_files": sum(r["changed"] for r in duplicate_stage["imports"]),
        "seconds": duplicate_stage["seconds"],
    }
    report["source_files_unchanged"] = before == file_hashes(selections)
    checks = (
        not differences,
        report["differential"]["core_equal"],
        report["differential"]["recommendation_cards_equal"],
        report["idempotence"]["logical_layers_equal"],
        report["idempotence"]["changed_files"] == 0,
        report["source_files_unchanged"],
        all(case["status"] == "passed" for case in report["cases"].values()),
    )
    report["status"] = "passed" if all(checks) else "failed"
    save(output / "summary.json", report)
    return report


def run(home, output, scope, *, batches=3, progress=None, reuse_imports=False):
    output = Path(output).resolve()
    existed = output.exists()
    try:
        return _run(
            home, output, scope, batches=batches, progress=progress, reuse_imports=reuse_imports
        )
    except Exception as exc:
        if (
            output.is_relative_to((ROOT / ".local").resolve())
            and (not existed or reuse_imports)
            and output.is_dir()
        ):
            path = output / "summary.json"
            report = json.loads(path.read_text()) if path.exists() else {}
            save(path, {**report, "status": "failed", "error_type": type(exc).__name__})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--from-ts", type=int)
    parser.add_argument("--until-ts", type=int)
    parser.add_argument("--batches", type=int, default=3)
    parser.add_argument("--reuse-imports", action="store_true")
    args = parser.parse_args()

    def progress(value):
        if value.get("stage") != "capture" or value.get("completed", 0) % 20 == 0:
            print(json.dumps(value, ensure_ascii=False), flush=True)

    report = run(
        args.home,
        args.output,
        Scope(
            display_timezone="Asia/Shanghai",
            agent_ids=["codex"],
            from_ts=args.from_ts,
            until_ts=args.until_ts,
        ),
        batches=args.batches,
        progress=progress,
        reuse_imports=args.reuse_imports,
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
