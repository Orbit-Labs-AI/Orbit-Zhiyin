"""Synthetic-only import benchmark: staged first import, size, rescans and UI queries.

    uv run python -m benchmarks.data.import_bench --preset med --output .local/benchmarks/data-med.json

Prints one JSON document (also written to ``--output``). Field reference: README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from tandem_data.inventory import InventoryRequest, scan_inventory
from tandem_data.query import current_projection, event_page, trajectory_page
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store, readonly_connection

from .synthetic import GENERATOR_VERSION, PRESETS, generate

SCHEMA = "tandem-data-import-bench/1"
# Audit baseline (docs/audits/data-audit.md §3, full preset, Apple M-series, serial import).
AUDIT_BASELINE = {
    "full": {
        "first_import_seconds": 383.4,
        "db_megabytes": 2822.0,
        "append_one_file_seconds": 189.6,
        "append_note": "measured with origin/feat/data-app-integration FK indexes and cProfile",
    }
}


def _sysctl(name: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        return subprocess.run(
            ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def environment() -> dict:
    memory = _sysctl("hw.memsize")
    return {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": _sysctl("machdep.cpu.brand_string") or platform.processor() or None,
        "hardware_model": _sysctl("hw.model"),
        "logical_cpus": os.cpu_count(),
        "memory_gb": round(int(memory) / 2**30, 1) if memory and memory.isdigit() else None,
        "load_average_at_start": [round(value, 2) for value in os.getloadavg()],
    }


class StageClock:
    """Accumulate wall time per progress stage reported by ImportService."""

    def __init__(self):
        self.stages: dict[str, float] = {}
        self.current: str | None = None
        self.since = time.perf_counter()

    def __call__(self, progress: dict) -> None:
        stage = progress.get("stage")
        if stage == self.current:
            return
        now = time.perf_counter()
        if self.current:
            self.stages[self.current] = self.stages.get(self.current, 0.0) + now - self.since
        self.current, self.since = stage, now

    def finish(self) -> dict:
        self({"stage": "__end__"})
        return {name: round(value, 3) for name, value in self.stages.items()}


def prepare_sources(work: Path, preset: str, seed: int) -> tuple[Path, dict, float | None]:
    out = work / f"synthetic-{preset}-{seed}"
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("generator_version") == GENERATOR_VERSION:
            return out, manifest, None
        shutil.rmtree(out)
    started = time.perf_counter()
    manifest = generate(out, preset, seed)
    return out, manifest, round(time.perf_counter() - started, 3)


def import_all(store: Store, out: Path, manifest: dict, progress=None) -> dict:
    service = ImportService(store, progress)
    results = {}
    for agent, relative in sorted(manifest["sources"].items()):
        started = time.perf_counter()
        result = service.import_source(ImportRequest(agent, out / relative))
        results[agent] = {
            "seconds": round(time.perf_counter() - started, 3),
            "files": result.get("files"),
            "changed": result.get("changed"),
            "capture_errors": result.get("capture_errors"),
            "rebuilt": "projection" in result,
        }
    return results


def table_sizes(db) -> dict:
    try:
        rows = db.execute(
            "SELECT name,SUM(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC"
        ).fetchall()
    except sqlite3.Error as error:
        return {"unavailable": str(error)}
    return {name: round(size / 1e6, 2) for name, size in rows}


def ui_queries(home: Path, repeats: int) -> dict:
    """The 12 UI-critical reads from the audit (§3.6); best of ``repeats`` runs."""
    results = {}
    with readonly_connection(home / "tandem.db") as db:
        count = db.execute("SELECT COUNT(*) FROM session").fetchone()[0]
        sid = db.execute(
            "SELECT session_uid FROM session ORDER BY started_at DESC LIMIT 1 OFFSET ?",
            (min(50, max(count - 1, 0)),),
        ).fetchone()[0]
        pid = db.execute("SELECT project_id FROM session WHERE project_id IS NOT NULL LIMIT 1")
        pid = (pid.fetchone() or [None])[0]
        tool = db.execute(
            "SELECT name FROM tool_call GROUP BY name ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()[0]
        queries = {
            "current_projection": lambda: current_projection(db),
            "session_list_page": lambda: db.execute(
                "SELECT * FROM session s LEFT JOIN project p USING(project_id) "
                "ORDER BY s.started_at DESC LIMIT 50 OFFSET 200"
            ).fetchall(),
            "session_list_by_project": lambda: db.execute(
                "SELECT * FROM session WHERE project_id=? ORDER BY started_at DESC LIMIT 50",
                (pid,),
            ).fetchall(),
            "event_page_100": lambda: event_page(home, sid, limit=100),
            "trajectory_page_100": lambda: trajectory_page(home, sid, limit=100),
            "tool_top_n": lambda: db.execute(
                "SELECT name,COUNT(*),SUM(status='failed') FROM v_analysis_tool_call "
                "GROUP BY name ORDER BY 2 DESC LIMIT 6"
            ).fetchall(),
            "tool_last_5_calls": lambda: db.execute(
                "SELECT * FROM tool_call WHERE name=? ORDER BY started_at DESC LIMIT 5", (tool,)
            ).fetchall(),
            "analysis_event_count": lambda: db.execute(
                "SELECT COUNT(*) FROM v_analysis_event"
            ).fetchone(),
            "human_message_count": lambda: db.execute(
                "SELECT COUNT(*) FROM v_human_message"
            ).fetchone(),
            "fts_match_join": lambda: db.execute(
                "SELECT e.session_uid FROM event_fts f JOIN event e ON e.rowid=f.rowid "
                "WHERE event_fts MATCH 'ok' LIMIT 20"
            ).fetchall(),
            "like_substring": lambda: db.execute(
                "SELECT session_uid FROM event WHERE text LIKE '%问题 7%' LIMIT 20"
            ).fetchall(),
            "source_status": lambda: db.execute(
                "SELECT s.agent,COUNT(DISTINCT x.session_uid),MAX(f.last_scan_at) FROM source s "
                "LEFT JOIN session x USING(source_id) LEFT JOIN source_file f USING(source_id) "
                "GROUP BY s.source_id"
            ).fetchall(),
        }
        for name, query in queries.items():
            best = float("inf")
            for _ in range(repeats):
                started = time.perf_counter()
                query()
                best = min(best, time.perf_counter() - started)
            results[name] = round(best * 1000, 2)
    return results


def append_one_file(store: Store, out: Path, manifest: dict) -> dict:
    """Append one pi entry to one file, rescan pi, then restore the source bytes."""
    root = out / manifest["sources"]["pi"]
    path = sorted(root.rglob("*.jsonl"))[0]
    original = path.read_bytes()
    last = json.loads(original.splitlines()[-1])
    extra = {**last, "id": "bench-append", "parentId": last["id"]}
    try:
        with path.open("ab") as handle:
            handle.write((json.dumps(extra, ensure_ascii=False) + "\n").encode())
        clock = StageClock()
        started = time.perf_counter()
        result = ImportService(store, clock).import_source(ImportRequest("pi", root))
        seconds = time.perf_counter() - started
    finally:
        path.write_bytes(original)
    return {
        "agent": "pi",
        "file": str(path.relative_to(root)),
        "seconds": round(seconds, 3),
        "changed_files": result.get("changed"),
        "stages_seconds": clock.finish(),
    }


def run(args) -> dict:
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    out, manifest, generate_seconds = prepare_sources(work, args.preset, args.seed)
    home = work / f"home-{args.preset}-{args.seed}"
    if home.exists():
        if any(
            p.name not in ("tandem.db", "tandem.db-wal", "tandem.db-shm", "import.lock", "raw")
            for p in home.iterdir()
        ):
            raise SystemExit(f"Refusing to delete unexpected content in {home}")
        shutil.rmtree(home)
    report = {
        "schema": SCHEMA,
        "preset": args.preset,
        "parameters": PRESETS[args.preset].__dict__,
        "seed": args.seed,
        "repeats": args.repeats,
        "environment": environment(),
        "dataset": {
            "generator_version": manifest["generator_version"],
            "generate_seconds": generate_seconds,
            "source_megabytes": round(
                sum(p.stat().st_size for p in (out / "sources").rglob("*") if p.is_file()) / 1e6, 2
            ),
            "totals": manifest["totals"],
            "agents": manifest["agents"],
            "large_outputs": len(manifest["large_outputs"]),
        },
    }
    with Store(home) as store:
        clock = StageClock()
        started = time.perf_counter()
        agents = import_all(store, out, manifest, clock)
        first = time.perf_counter() - started
        stages = clock.finish()
        events = store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        report["first_import"] = {
            "seconds": round(first, 3),
            "stages_seconds": stages,
            "agents": agents,
            "events": events,
            "events_per_second": round(events / first, 1) if first else None,
            "source_megabytes_per_second": round(report["dataset"]["source_megabytes"] / first, 2)
            if first
            else None,
        }
        started = time.perf_counter()
        inventory = manifest["inventory"]
        scanned = scan_inventory(
            store, InventoryRequest(inventory["agent"], out / inventory["root"])
        )
        report["inventory_scan"] = {
            "seconds": round(time.perf_counter() - started, 3),
            "items": scanned["items"],
        }
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        report["size"] = {
            "db_megabytes": round((home / "tandem.db").stat().st_size / 1e6, 2),
            "tables_megabytes": table_sizes(store.db),
            "event_column_megabytes": dict(
                zip(
                    ("text", "attrs", "ext"),
                    (
                        round((value or 0) / 1e6, 2)
                        for value in store.db.execute(
                            "SELECT SUM(LENGTH(CAST(text AS BLOB))),SUM(LENGTH(attrs)),"
                            "SUM(LENGTH(ext)) FROM event"
                        ).fetchone()
                    ),
                    strict=True,
                )
            ),
        }
        report["ui_queries_ms"] = ui_queries(home, args.repeats)
        if args.check:
            from tandem_data.validation.integrity import invariants, logical_digest

            started = time.perf_counter()
            digest = logical_digest(home)
            digest_seconds = time.perf_counter() - started
            checks = invariants(home, verify=not args.skip_verify)
            report["integrity"] = {
                "logical_digest": digest,
                "digest_seconds": round(digest_seconds, 3),
                "problems": checks["problems"],
                "events_match_manifest": checks["events"] == manifest["totals"]["events"],
            }
        started = time.perf_counter()
        import_all(store, out, manifest)
        report["noop_rescan_seconds"] = round(time.perf_counter() - started, 3)
        report["append_one_file"] = (
            None if args.no_append else append_one_file(store, out, manifest)
        )
    baseline = AUDIT_BASELINE.get(args.preset)
    if baseline:
        measured = {
            "first_import_seconds": report["first_import"]["seconds"],
            "db_megabytes": report["size"]["db_megabytes"],
            "append_one_file_seconds": (report["append_one_file"] or {}).get("seconds"),
        }
        report["audit_baseline"] = {
            **baseline,
            "ratio": {
                key: round(measured[key] / baseline[key], 3) if measured[key] else None
                for key in measured
            },
        }
    if not args.keep:
        shutil.rmtree(home)
    return report


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Synthetic data import benchmark")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="small")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=3, help="UI query repetitions (best of)")
    parser.add_argument("--work", type=Path, default=Path(".local/benchmarks/data"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help="also run logical_digest/invariants")
    parser.add_argument("--skip-verify", action="store_true", help="with --check: skip verify()")
    parser.add_argument("--no-append", action="store_true", help="skip the append rescan")
    parser.add_argument("--keep", action="store_true", help="keep the benchmark data home")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    report = run(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
