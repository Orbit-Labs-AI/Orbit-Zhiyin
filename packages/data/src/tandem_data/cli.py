from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from tandem_data.contract import canonical, now_ms
from tandem_data.discovery import candidates, inputs
from tandem_data.store import Store, readonly_connection

EXPORT_TABLES = (
    "session",
    "turn",
    "tool_call",
    "model_call",
    "usage_snapshot",
    "session_feature",
    "v_analysis_event",
    "v_human_message",
    "v_analysis_tool_call",
    "v_analysis_model_call",
    "v_latest_usage_snapshot",
)


def statistics(store):
    return {
        "db": str(store.db_path),
        "schema_version": store.db.execute("PRAGMA user_version").fetchone()[0],
        "tables": {
            name: store.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in (
                "source",
                "source_file",
                "source_revision",
                "raw_record",
                "event",
                "session",
                "turn",
                "tool_call",
                "model_call",
                "usage_snapshot",
            )
        },
        "dispositions": dict(
            store.db.execute("SELECT disposition,COUNT(*) FROM raw_record GROUP BY disposition")
        ),
        "issues": [
            dict(row)
            for row in store.db.execute(
                "SELECT stage,code,COUNT(*) AS n FROM ingest_issue GROUP BY stage,code"
            )
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tandem local session data contract v1")
    parser.add_argument(
        "--home",
        default=os.getenv("TANDEM_HOME", str(Path.home() / "Library/Application Support/Tandem")),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("discover")
    scan = commands.add_parser("scan")
    scan.add_argument("--agent", required=True)
    scan.add_argument("--root", type=Path, required=True)
    scan.add_argument("--limit", type=int)
    scan.add_argument("--no-rebuild", action="store_true")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--agent", required=True)
    ingest.add_argument("--root", type=Path, required=True)
    ingest.add_argument("--file", type=Path, required=True)
    ingest.add_argument("--no-rebuild", action="store_true")
    commands.add_parser("rebuild")
    bridge = commands.add_parser("import-connector")
    bridge.add_argument("--connector-home", type=Path, required=True)
    commands.add_parser("stats")
    commands.add_parser("verify")
    export = commands.add_parser("export")
    export.add_argument("--table", choices=EXPORT_TABLES, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    args = parser.parse_args(argv)
    if args.command == "discover":
        print(canonical(candidates()))
        return
    if args.command in ("scan", "ingest") and Path(args.home).expanduser().resolve().is_relative_to(
        args.root.expanduser().resolve()
    ):
        parser.error("--home must be outside the Agent source root")
    with Store(args.home) as store:
        if args.command == "init":
            result = {"db": str(store.db_path), "schema_version": 1}
        elif args.command in ("scan", "ingest"):
            root = args.root.expanduser().resolve()
            source_id = store.add_source(args.agent, root)
            discovered = list(inputs(args.agent, root)) if args.command == "scan" else []
            selected = (
                discovered[: args.limit]
                if args.command == "scan" and args.limit is not None
                else discovered
            )
            captured = []
            errors = 0
            targets = (
                [(item.path, item.role) for item in selected]
                if args.command == "scan"
                else [(args.file, "transcript")]
            )
            for path, role in targets:
                try:
                    captured.append(store.capture_file(source_id, path, role))
                except (OSError, RuntimeError, ValueError) as error:
                    errors += 1
                    store.issue(
                        source_id,
                        "capture_failed",
                        stage="l1",
                        detail={"exception": type(error).__name__},
                    )
            if args.command == "scan" and args.limit is None:
                discovered_paths = {str(item.path.relative_to(root)) for item in discovered}
                for row in store.db.execute(
                    "SELECT * FROM source_file WHERE source_id=?", (source_id,)
                ).fetchall():
                    if row["relative_path"] not in discovered_paths:
                        store.db.execute(
                            "UPDATE source_file SET status='gone_upstream',last_scan_at=? WHERE file_id=?",
                            (now_ms(), row["file_id"]),
                        )
            result = {
                "source_id": source_id,
                "files": len(captured),
                "changed": sum(row["changed"] for row in captured),
                "capture_errors": errors,
            }
            if not args.no_rebuild:
                result["projection"] = store.rebuild()
        elif args.command == "rebuild":
            result = store.rebuild()
        elif args.command == "import-connector":
            from tandem_data.bridge import import_connector

            result = import_connector(store, args.connector_home)
            result["projection"] = store.rebuild()
        elif args.command == "stats":
            result = statistics(store)
        elif args.command == "verify":
            result = store.verify()
        else:
            with (
                readonly_connection(store.db_path) as connection,
                args.output.open("w", encoding="utf-8", newline="") as handle,
            ):
                rows = connection.execute(f"SELECT * FROM {args.table}")
                if args.format == "csv":
                    writer = csv.writer(handle)
                    writer.writerow([col[0] for col in rows.description])
                    writer.writerows(rows)
                else:
                    for row in rows:
                        data = dict(row)
                        for key in ("attrs", "ext", "native_key", "files", "attribution"):
                            if isinstance(data.get(key), str):
                                data[key] = json.loads(data[key])
                        handle.write(canonical(data) + "\n")
                result = {"export": str(args.output), "table": args.table}
        print(canonical(result))


if __name__ == "__main__":
    main()
