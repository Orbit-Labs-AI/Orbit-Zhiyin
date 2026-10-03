from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from orbit_data.contract import canonical
from orbit_data.discovery import candidates
from orbit_data.paths import default_home
from orbit_data.payload import restore, restore_json, restore_row
from orbit_data.query import current_projection
from orbit_data.store import Store, readonly_connection

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


def _csv_cell(value):
    """Prevent spreadsheet evaluation; typed numeric cells remain numeric."""
    if isinstance(value, str):
        candidate = value.lstrip()
        if candidate.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
    return value


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


DATA_SERVICE_COMMANDS = (
    "search",
    "resume",
    "capabilities",
    "storage",
    "purge",
    "privacy-rules",
    "privacy-preview",
    "insights",
)


def _data_service(args) -> dict:
    """Read-only services (and the confirmed purge) never open a writable Store."""
    home = Path(args.home).expanduser()
    if args.command == "search":
        from orbit_data.search import SearchScope, search

        scope = SearchScope(
            source_ids=tuple(args.source_ids) if args.source_ids else None,
            from_ts=args.from_ts,
            until_ts=args.until_ts,
        )
        return search(home, args.query, scope, limit=args.limit, offset=args.offset)
    if args.command == "resume":
        from orbit_data.resume import session_resume

        return session_resume(home, args.session)
    if args.command == "capabilities":
        from orbit_data.capabilities import capabilities

        return capabilities(home, refresh=args.refresh)
    if args.command == "storage":
        from orbit_data.maintenance import storage_usage

        return storage_usage(home)
    if args.command == "purge":
        from orbit_data.maintenance import purge_all

        return purge_all(home, args.confirm)
    if args.command == "privacy-rules":
        from orbit_data.privacy_rules import rules

        return rules()
    if args.command == "privacy-preview":
        import sys

        from orbit_data.privacy_rules import preview

        return preview(args.text if args.text is not None else sys.stdin.read())
    from orbit_data.insights import match_sessions, read_usage_data

    report = read_usage_data(args.path)
    if args.match:
        report["matches"] = match_sessions(home, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Orbit local session data contract v1")
    parser.add_argument(
        "--home",
        default=default_home(),
    )
    parser.add_argument("--no-progress", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("discover")
    scan = commands.add_parser("scan")
    scan.add_argument("--agent", required=True)
    scan.add_argument("--root", type=Path, required=True)
    scan.add_argument("--limit", type=int)
    scan.add_argument("--no-rebuild", action="store_true")
    scan.add_argument(
        "--maintenance",
        choices=("wait", "background", "off"),
        default="wait",
        help="Post-import compaction: wait for it (default), run it in the background, or skip it",
    )
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--agent", required=True)
    ingest.add_argument("--root", type=Path, required=True)
    ingest.add_argument("--file", type=Path, required=True)
    ingest.add_argument("--no-rebuild", action="store_true")
    ingest.add_argument(
        "--maintenance",
        choices=("wait", "background", "off"),
        default="wait",
        help="Post-import compaction: wait for it (default), run it in the background, or skip it",
    )
    inventory = commands.add_parser(
        "scan-inventory", help="Read explicitly enabled configuration roots"
    )
    from orbit_data.inventory.adapters import SUPPORTED

    inventory.add_argument("--agent", choices=SUPPORTED, required=True)
    inventory.add_argument("--root", type=Path, required=True)
    inventory.add_argument("--project-id")
    inventory.add_argument("--allow-root", action="append", type=Path, default=[])
    inventory.add_argument("--claude-config", type=Path)
    inventory.add_argument("--skill-root", action="append", type=Path, default=[])
    commands.add_parser("inventory", help="Read latest installation observations")
    commands.add_parser("rebuild")
    bridge = commands.add_parser("import-connector")
    bridge.add_argument("--connector-home", type=Path, required=True)
    commands.add_parser("stats")
    commands.add_parser("verify")
    export = commands.add_parser("export")
    export.add_argument("--table", choices=EXPORT_TABLES, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    search = commands.add_parser(
        "search", help="Search messages, titles, projects, commands, files"
    )
    search.add_argument("query")
    search.add_argument("--source-id", action="append", dest="source_ids")
    search.add_argument("--from-ts", type=int)
    search.add_argument("--until-ts", type=int)
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    resume = commands.add_parser("resume", help="Print (never run) the resume command")
    resume.add_argument("--session", required=True)
    capabilities = commands.add_parser("capabilities", help="Source versions and capabilities")
    capabilities.add_argument("--refresh", action="store_true")
    commands.add_parser("storage", help="Bytes per storage layer")
    purge = commands.add_parser("purge", help="Delete orbit.db, WAL and raw archive")
    purge.add_argument("--confirm", required=True)
    commands.add_parser("privacy-rules", help="List redaction rules")
    privacy_preview = commands.add_parser("privacy-preview", help="Redact sample text (stdin)")
    privacy_preview.add_argument("--text")
    usage = commands.add_parser("insights", help="Read Claude Code usage-data at an explicit path")
    usage.add_argument("--path", type=Path, required=True)
    usage.add_argument("--match", action="store_true", help="Compare with Orbit sessions")
    args = parser.parse_args(argv)
    if args.command in DATA_SERVICE_COMMANDS:
        print(canonical(_data_service(args)))
        return
    from orbit_data.progress import TerminalProgress

    progress = TerminalProgress(enabled=not args.no_progress)
    if args.command == "discover":
        print(canonical(candidates()))
        return
    if args.command in ("scan", "ingest", "scan-inventory") and Path(
        args.home
    ).expanduser().resolve().is_relative_to(args.root.expanduser().resolve()):
        parser.error("--home must be outside the Agent source root")
    if args.command == "scan-inventory" and any(
        Path(args.home).expanduser().resolve().is_relative_to(path.expanduser().resolve())
        for path in (*args.allow_root, *args.skill_root)
    ):
        parser.error("--home must be outside every --allow-root")
    with Store(args.home) as store:
        if args.command == "init":
            result = {
                "db": str(store.db_path),
                "schema_version": store.db.execute("PRAGMA user_version").fetchone()[0],
            }
        elif args.command in ("scan", "ingest"):
            from orbit_data.service import ImportRequest, ImportService

            result = ImportService(
                store, progress=progress, maintenance=args.maintenance
            ).import_source(
                ImportRequest(
                    agent=args.agent,
                    root=args.root,
                    files=(args.file,) if args.command == "ingest" else None,
                    limit=args.limit if args.command == "scan" else None,
                    rebuild=not args.no_rebuild,
                )
            )
        elif args.command == "scan-inventory":
            from orbit_data.inventory import InventoryRequest, scan_inventory

            result = scan_inventory(
                store,
                InventoryRequest(
                    agent=args.agent,
                    root=args.root,
                    project_id=args.project_id,
                    allowed_roots=tuple(args.allow_root),
                    claude_config=args.claude_config,
                    skill_roots=tuple(args.skill_root),
                ),
            )
        elif args.command == "inventory":
            from orbit_data.inventory import read_inventory

            result = read_inventory(store.home)
        elif args.command == "rebuild":
            from orbit_data.service import ImportService

            with ImportService(store).writer():
                result = store.rebuild(progress=progress)
        elif args.command == "import-connector":
            from orbit_data.bridge import import_connector
            from orbit_data.service import ImportService

            with ImportService(store).writer():
                result = import_connector(store, args.connector_home)
                result["projection"] = store.rebuild(progress=progress)
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
            from contextlib import ExitStack

            with ExitStack() as stack:
                connection = stack.enter_context(readonly_connection(store.db_path))
                connection.execute("BEGIN")
                current_projection(connection)
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                handle = stack.enter_context(
                    os.fdopen(descriptor, "w", encoding="utf-8", newline="")
                )
                rows = connection.execute(f"SELECT * FROM {args.table}")
                if args.format == "csv":
                    writer = csv.writer(handle)
                    writer.writerow([col[0] for col in rows.description])
                    ext = (
                        [col[0] for col in rows.description].index("ext")
                        if args.table == "event"
                        else -1
                    )
                    texts: dict = {}

                    def logical(row):
                        if ext < 0:
                            return list(row)
                        event = restore_row(connection, row, texts)
                        event["ext"] = canonical(restore_json(connection, event["ext"]))
                        return list(event.values())

                    writer.writerows([_csv_cell(value) for value in logical(row)] for row in rows)
                else:
                    for row in rows:
                        data = restore_row(connection, row) if args.table == "event" else dict(row)
                        for key in ("attrs", "ext", "native_key", "files", "attribution"):
                            if isinstance(data.get(key), str):
                                data[key] = json.loads(data[key])
                        if args.table == "event":
                            data["ext"] = restore(connection, data["ext"])
                        handle.write(canonical(data) + "\n")
                result = {"export": str(args.output), "table": args.table}
        print(canonical(result))
        if (
            result.get("capture_errors")
            or result.get("current_unparsed")
            or result.get("skipped_files")
            or (args.command == "scan-inventory" and result["status"] == "partial")
        ):
            raise SystemExit(2)


if __name__ == "__main__":
    main()
