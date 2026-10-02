from __future__ import annotations

import argparse
import json
import resource
import time
import uuid
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from tandem_data.contract import canonical
from tandem_data.discovery import candidates, inputs
from tandem_data.service import ImportRequest, ImportService, event_page
from tandem_data.store import Store
from tandem_data.validation.fixtures import AGENTS, ISO, create_sources
from tandem_data.validation.report import write_report


def _inspect(store, agent, mode):
    sessions = []
    for session in store.db.execute("SELECT * FROM session ORDER BY started_at DESC LIMIT 8"):
        uid = session["session_uid"]
        events = event_page(store.home, uid, limit=60)
        # Report stays small; full envelopes are available through event_page and raw evidence.
        for event in events:
            event["ext"] = {"available_in_database": True}
            if event["text"] is not None:
                event["text"] = event["text"][:1000]
        derived = {
            table: [
                dict(r)
                for r in store.db.execute(
                    f"SELECT * FROM {table} WHERE session_uid=? LIMIT 10", (uid,)
                )
            ]
            for table in ("turn", "tool_call", "model_call", "usage_snapshot")
        }
        sessions.append(
            {
                "agent": agent,
                "mode": mode,
                "title": session["title"],
                "native_id": session["native_id"],
                "events": events,
                "derived": derived,
            }
        )
    return sessions


def _run(folder, agent, root, mode, selected=None):
    with Store(folder) as store:
        service = ImportService(store)
        request = ImportRequest(agent, root, files=selected)
        cold = service.import_source(request)
        verification = store.verify()
        before = store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        warm = service.import_source(request)
        after = store.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        if warm["changed"] or before != after:
            raise AssertionError("Repeated import changed an unchanged source")
        issues = [
            dict(r)
            for r in store.db.execute("SELECT code,COUNT(*) n FROM ingest_issue GROUP BY code")
        ]
        failed = cold["capture_errors"] or verification["unparsed"]
        status = "coverage_gap" if failed else "passed_with_diagnostics" if issues else "passed"
        result = {
            "agent": agent,
            "label": root.name,
            "mode": mode,
            "status": status,
            "files": cold["files"],
            "records": verification["records"],
            "events": before,
            "cold_seconds": cold["elapsed_seconds"],
            "warm_seconds": warm["elapsed_seconds"],
            "verification": verification,
            "issues": issues,
            "idempotent": True,
        }
        return result, _inspect(store, agent, mode)


def benchmark(folder, count=1000):
    root = folder / "source"
    path = root / "sessions/bench.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w") as file:
        file.write(canonical({"type": "session", "id": "bench", "timestamp": ISO}) + "\n")
        for index in range(count):
            file.write(
                canonical(
                    {
                        "type": "message",
                        "id": str(index),
                        "timestamp": ISO,
                        "message": {
                            "role": "user" if index % 2 == 0 else "assistant",
                            "content": "benchmark fixture",
                        },
                    }
                )
                + "\n"
            )
    with Store(folder / "data") as store:
        service = ImportService(store)
        cold = service.import_source(ImportRequest("pi", root))
        warm = service.import_source(ImportRequest("pi", root))
        return {
            "records": count + 1,
            "bytes": path.stat().st_size,
            "cold_seconds": cold["elapsed_seconds"],
            "warm_seconds": warm["elapsed_seconds"],
            "records_per_second": round((count + 1) / max(cold["elapsed_seconds"], 0.0001)),
            "warm_changed": warm["changed"],
            "peak_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "note": "Local elapsed times; RSS includes the validation process, not an isolated memory benchmark.",
        }


def run(output: Path, *, real=False, full=False, limit=2, open_report=False, agent_filter=None):
    if limit < 1:
        raise ValueError("limit must be positive")
    output = output.expanduser().resolve()
    for source in candidates():
        if output.is_relative_to(Path(source["root"])):
            raise ValueError("Validation output must be outside all discovered Agent roots")
    folder = output / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, mode=0o700)
    data = {
        "boundary": "构造样本覆盖六家；真实数据仅在显式 --real 时只读导入。未安装来源标记 unavailable。真实样本有数量和大小上限，--full 才导入所选来源的全量历史。",
        "results": [],
        "sessions": [],
    }
    for agent, root in create_sources(folder / "fixtures").items():
        result, sessions = _run(folder / "synthetic" / agent, agent, root, "synthetic")
        data["results"].append(result)
        data["sessions"].extend(sessions)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    if real:
        discovered = candidates()
        for agent in agent_filter or AGENTS:
            sources = [s for s in discovered if s["agent"] == agent]
            if not sources:
                data["results"].append({"agent": agent, "mode": "real", "status": "unavailable"})
            for index, source in enumerate(sources):
                root = Path(source["root"])
                selected = None
                if not full:
                    files = [
                        item
                        for item in inputs(agent, root)
                        if item.role == "transcript"
                        and item.path.stat().st_size <= 16 * 1024 * 1024
                        and item.path.stat().st_mtime < time.time() - 120
                    ]
                    files.sort(key=lambda item: item.path.stat().st_mtime, reverse=True)
                    selected = tuple(item.path for item in files[:limit])
                    if not selected:
                        data["results"].append(
                            {
                                "agent": agent,
                                "label": root.name,
                                "mode": "real",
                                "status": "no_eligible_sample",
                            }
                        )
                        continue
                try:
                    result, sessions = _run(
                        folder / "real" / f"{agent}-{index}",
                        agent,
                        root,
                        "real_full" if full else "real_sample",
                        selected,
                    )
                    data["results"].append(result)
                    data["sessions"].extend(sessions)
                except Exception as error:
                    result = {
                        "agent": agent,
                        "mode": "real",
                        "status": "error",
                        "error_type": type(error).__name__,
                    }
                    data["results"].append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    data["benchmark"] = benchmark(folder / "benchmark")
    report = folder / "report.html"
    write_report(report, data)
    summary = folder / "results.json"
    summary.write_text(
        json.dumps(
            {key: value for key, value in data.items() if key != "sessions"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    summary.chmod(0o600)
    print(f"Report: {report}\nSummary: {summary}", flush=True)
    if open_report:
        webbrowser.open(report.as_uri())
    return data, report


def main():
    parser = argparse.ArgumentParser(
        description="Tandem offline connector acceptance and local preview"
    )
    parser.add_argument("--output", type=Path, default=Path(".local/connector-checks"))
    parser.add_argument(
        "--real",
        action="store_true",
        help="Explicitly enable bounded, read-only local session samples",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="With --real: import all discovered sessions instead of samples",
    )
    parser.add_argument("--agent", action="append", choices=AGENTS)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if args.full and not args.real:
        parser.error("--full requires --real")
    data, _ = run(
        args.output,
        real=args.real,
        full=args.full,
        limit=args.limit,
        open_report=args.open,
        agent_filter=args.agent,
    )
    if any(r["status"] in ("error", "coverage_gap") for r in data["results"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
