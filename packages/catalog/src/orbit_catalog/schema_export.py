"""Export catalog row contracts from the DDL owned by the shared data package."""

import argparse
import json
import sqlite3
from importlib.resources import files
from pathlib import Path


def table_schemas():
    objects = {"spec", "checkpoint", "metadata", "descriptor", "specification", "result"}
    arrays = {"agents", "risk", "aliases"}
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(files("orbit_data").joinpath("migrations/catalog/schema.sql").read_text())
        definitions = {}
        for table, ddl in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'chunk_fts%' ORDER BY name"):
            properties = {}
            for _, name, sql_type, not_null, default, primary in conn.execute(f'PRAGMA table_info("{table}")'):
                typ = {"INTEGER": "integer", "REAL": "number"}.get(sql_type, "string")
                if name in objects:
                    typ = "object"
                elif name in arrays:
                    typ = "array"
                properties[name] = {"type": typ if not_null or primary else [typ, "null"], "x-sql-type": sql_type}
                if sql_type == "BLOB":
                    properties[name]["contentEncoding"] = "base64"
                if default is not None:
                    properties[name]["x-sql-default"] = default
            definitions[table] = {"type": "object", "additionalProperties": False, "properties": properties,
                                  "required": list(properties), "x-ddl": ddl,
                                  "x-foreign-keys": [{"table": r[2], "from": r[3], "to": r[4]}
                                                     for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')]}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Orbit catalog rows v1",
            "x-database-schema-version": 3, "$defs": definitions,
            "description": ("Separate catalog.db. Decode JSON text columns; blob.data is zlib (codec 1) or raw (codec 0); "
                            "embedding_cache.vector is little-endian float16; encode BLOBs as base64 for JSON transport.")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(table_schemas(), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
