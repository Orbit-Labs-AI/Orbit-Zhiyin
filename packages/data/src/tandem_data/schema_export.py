"""Machine-readable L1/L2/L3 field dictionary generated from the authoritative DDL."""

import json
import sqlite3
from importlib.resources import files


def table_schemas():
    connection = sqlite3.connect(":memory:")
    connection.executescript(files("tandem_data").joinpath("migrations/001.sql").read_text())
    tables = {}
    for name, sql in connection.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'event_fts%' ORDER BY name"
    ):
        properties, required = {}, []
        for _, column, sql_type, notnull, default, primary in connection.execute(
            f'PRAGMA table_info("{name}")'
        ):
            typ = {"TEXT": "string", "INTEGER": "integer", "REAL": "number"}.get(sql_type, "string")
            if column in ("attrs", "ext", "attribution", "note", "watermark", "source_stat"):
                typ = "object"
            if column in ("native_key", "locator", "paths", "files"):
                typ = "array"
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
        "title": "Tandem database rows v1",
        "$defs": tables,
        "description": "JSON text columns must be decoded before validating a row. Event semantic validation also uses event-v1.schema.json.",
    }


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(table_schemas(), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
