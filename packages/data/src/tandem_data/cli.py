from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from tandem_data.contract import canonical
from tandem_data.discovery import candidates
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
            result = {
                "db": str(store.db_path),
                "schema_version": store.db.execute("PRAGMA user_version").fetchone()[0],
            }
        elif args.command in ("scan", "ingest"):
            from tandem_data.service import ImportRequest, ImportService

            result = ImportService(store).import_source(
                ImportRequest(
                    agent=args.agent,
                    root=args.root,
                    files=(args.file,) if args.command == "ingest" else None,
                    limit=args.limit if args.command == "scan" else None,
                    rebuild=not args.no_rebuild,
                )
            )
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
            target = args.output.expanduser().resolve()
            for source in store.db.execute("SELECT root_path FROM source"):
                if target.is_relative_to(Path(source[0])):
                    raise ValueError("Export must not write into an Agent source directory")
            if target == store.db_path or target.is_relative_to(store.raw_dir):
                raise ValueError("Export must not overwrite the database or raw archive")
            from contextlib import closing

            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with (
                closing(readonly_connection(store.db_path)) as connection,
                os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle,
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
        if result.get("capture_errors") or result.get("current_unparsed"):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
