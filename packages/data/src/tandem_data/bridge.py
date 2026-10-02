"""Import the TypeScript connector's immutable archive chunks into the canonical DB.

The staging database is read-only. Its L2/L3 schema and IDs are intentionally not copied.
No upstream agent files are reread; the original bytes and record crosswalk are sufficient.
"""

import hashlib
from pathlib import Path

import zstandard

from tandem_data.contract import canonical, uid
from tandem_data.store import readonly_connection


def import_connector(store, connector_home: str | Path) -> dict:
    home = Path(connector_home).expanduser().resolve()
    if home == store.home:
        raise ValueError("Staging and canonical database directories must differ")
    imported = skipped = 0
    with readonly_connection(home / "tandem.db") as connection:
        connection.execute("BEGIN")
        required = {"archive_chunk", "raw_record", "source_file", "source"}
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not required <= tables:
            raise ValueError("Unsupported connector staging schema")
        for source in connection.execute("SELECT * FROM source ORDER BY source_id"):
            source_id = store.add_source(source["agent"], source["root_path"], source["label"])
            for file in connection.execute(
                "SELECT * FROM source_file WHERE source_id=? ORDER BY path", (source["source_id"],)
            ):
                source_path = Path(file["path"])
                source_root = Path(source["root_path"])
                relative = (
                    str(source_path.relative_to(source_root))
                    if source_path.is_absolute() and source_path.is_relative_to(source_root)
                    else file["file_id"] + ".jsonl"
                )
                generations = [
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT generation FROM archive_chunk WHERE file_id=? AND generation>=0 ORDER BY generation",
                        (file["file_id"],),
                    )
                ]
                for generation in generations:
                    chunks = list(
                        connection.execute(
                            "SELECT * FROM archive_chunk WHERE file_id=? AND generation=? ORDER BY offset",
                            (file["file_id"], generation),
                        )
                    )
                    fingerprint = uid(
                        "connector_manifest",
                        [[row["offset"], row["byte_len"], row["sha256"]] for row in chunks],
                    )
                    checkpoint = store.db.execute(
                        "SELECT fingerprint FROM connector_checkpoint WHERE connector_db=? AND external_file_id=? AND generation=?",
                        (str(home), file["file_id"], generation),
                    ).fetchone()
                    if checkpoint and checkpoint[0] == fingerprint:
                        skipped += 1
                        continue

                    def stream(manifest=chunks):
                        offset = 0
                        for chunk in manifest:
                            if chunk["offset"] != offset:
                                raise ValueError("Connector archive contains a gap")
                            path = Path(chunk["path"])
                            path = (
                                (home / path).resolve()
                                if not path.is_absolute()
                                else path.resolve()
                            )
                            if not path.is_relative_to(home / "raw"):
                                raise ValueError("Connector archive path escapes its raw directory")
                            digest, size = hashlib.sha256(), 0
                            with (
                                path.open("rb") as raw,
                                zstandard.ZstdDecompressor().stream_reader(
                                    raw, read_across_frames=True
                                ) as decoded,
                            ):
                                while block := decoded.read(1024 * 1024):
                                    size += len(block)
                                    digest.update(block)
                                    yield block
                            if size != chunk["byte_len"] or digest.hexdigest() != chunk["sha256"]:
                                raise ValueError("Connector chunk checksum mismatch")
                            offset += size

                    captured = store.capture_stream(
                        source_id,
                        relative,
                        stream(),
                        format_name="jsonl_zstd" if file["format"] == "jsonl_zstd" else "jsonl",
                        role=file["role"],
                        source_stat={"connector_generation": generation, "connector_db": str(home)},
                    )
                    file_id = captured["file_id"]
                    with store.transaction():
                        store.db.execute(
                            "INSERT INTO connector_checkpoint VALUES(?,?,?,?,?) ON CONFLICT(connector_db,external_file_id,generation) DO UPDATE SET fingerprint=excluded.fingerprint",
                            (str(home), file["file_id"], generation, fingerprint, file_id),
                        )
                        for raw in connection.execute(
                            "SELECT record_uid,line_no,sha256 FROM raw_record WHERE file_id=? AND generation=?",
                            (file["file_id"], generation),
                        ):
                            target = store.db.execute(
                                "SELECT r.record_uid,r.sha256 FROM file_record f JOIN raw_record r USING(record_uid) WHERE f.file_id=? AND f.locator=?",
                                (file_id, canonical(["line", raw["line_no"] - 1])),
                            ).fetchone()
                            if not target or target["sha256"] != raw["sha256"]:
                                raise ValueError("Connector record crosswalk checksum mismatch")
                            store.db.execute(
                                "INSERT OR REPLACE INTO connector_record_link VALUES(?,?,?)",
                                (str(home), raw["record_uid"], target["record_uid"]),
                            )
                    imported += 1
                store.db.execute(
                    "UPDATE source_file SET status=? WHERE file_id=?",
                    (file["status"], uid("file", source_id, relative)),
                )
    return {"imported_revisions": imported, "unchanged_manifests": skipped}
