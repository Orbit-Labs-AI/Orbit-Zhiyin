"""Machine-readable L1/L2/L3 field dictionary generated from the authoritative DDL."""

import json
import sqlite3
from importlib.resources import files


def create_schema(connection, database="canonical"):
    """Apply every migration in order to an empty connection (no rows, no projection run).

    Used for the field dictionary and by the gateway as an empty stand-in for orbit.db
    before the first import, so read routes keep their shape instead of failing.
    """
    folder = "migrations/analysis" if database == "analysis" else "migrations"
    for migration in sorted(files("orbit_data").joinpath(folder).iterdir(), key=lambda p: p.name):
        if migration.name.endswith(".sql"):
            connection.executescript(migration.read_text())
    return connection


def table_schemas(database="canonical"):
    connection = create_schema(sqlite3.connect(":memory:"), database)
    tables = {}
    for name, sql in connection.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'event_fts%' AND name NOT LIKE 'event_search%' ORDER BY name"
    ):
        properties, required = {}, []
        for _, column, sql_type, notnull, default, primary in connection.execute(
            f'PRAGMA table_info("{name}")'
        ):
            typ = {"TEXT": "string", "INTEGER": "integer", "REAL": "number"}.get(sql_type, "string")
            if column in (
                "attrs",
                "ext",
                "attribution",
                "note",
                "watermark",
                "source_stat",
                "request_json",
                "command_spec",
            ):
                typ = "object"
            if column in ("native_key", "locator", "paths", "files"):
                typ = "array"
            # Same column names can have different contracts in different tables.
            # In particular, model-call coverage is TEXT, not inventory JSON.
            typ = {
                ("inventory_item", "locator"): "string",
                ("inventory_item", "config"): "object",
                ("inventory_scan", "coverage"): "object",
                ("inventory_scan", "diagnostics"): "array",
            }.get((name, column), typ)
            properties[column] = {
                "type": typ if notnull or primary else [typ, "null"],
                "x-sql-type": sql_type,
            }
            if default is not None:
                properties[column]["x-sql-default"] = default
            required.append(column)  # Full SELECT rows include nullable fields as NULL.
        foreign = [
            {"table": row[2], "from": row[3], "to": row[4]}
            for row in connection.execute(f'PRAGMA foreign_key_list("{name}")')
        ]
        tables[name] = {
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": properties,
            "x-foreign-keys": foreign,
            "x-ddl": sql,
        }
    connection.close()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Orbit analysis history rows v1"
        if database == "analysis"
        else "Orbit database rows v1",
        "$defs": tables,
        "description": "JSON text columns must be decoded before validating a row. Event semantic validation also uses event-v1.schema.json.",
    }


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", choices=("canonical", "analysis"), default="canonical")
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(table_schemas(args.database), ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
