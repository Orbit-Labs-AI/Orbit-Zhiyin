"""SQLite storage and immutable, streaming L0 capture. Agent files are read only."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Iterable
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

import zstandard as zstd

from tandem_data import SCHEMA_VERSION, payload
from tandem_data.contract import RawRecord, canonical, now_ms, shape, uid

PAGE_SIZE = 16384
# Bulk imports leave B-tree pages partly empty (random-key indexes, rows that grow when the
# reducer fills turn_uid). ``optimize`` rewrites the file once it has grown by COMPACT_GROWTH
# since it was opened or last compacted (always after the first import into a new store), so
# total compaction work stays within a few file sizes.
COMPACT_GROWTH = 1.5
# Every table and index owns at least one page (~130 objects), so 16 KiB pages cost a small
# store ~2 MB of empty space. Compaction picks the page size by store size: tiny stores use
# 1 KiB pages (the fixed per-object pages dominate; events overflow but stay cheap at this
# scale), small stores 4 KiB, large stores PAGE_SIZE. Each step up triggers at a larger size
# than the step down, so a store near a boundary does not switch back and forth.
TINY_PAGE_SIZE = 1024
SMALL_PAGE_SIZE = 4096
TINY_STORE_MAX_BYTES = 6 << 20
TINY_STORE_GROW_BYTES = 12 << 20
SMALL_STORE_MAX_BYTES = 16 << 20
LARGE_STORE_MIN_BYTES = 32 << 20
# Maintenance VACUUMs when this share of the used pages is slack (dbstat ``unused``); free
# pages alone are returned with ``incremental_vacuum`` instead of a full rewrite.
VACUUM_SLACK = 0.05
# After a check, later maintenance skips the dbstat scan until the store grows by this
# factor or this share of its pages is free (state in ``maintenance.json`` in the home).
MAINTAIN_GROWTH = 1.25
MAINTAIN_FREE_SHARE = 0.05


def target_page_size(size_bytes: int, page_size: int) -> int:
    """Page size a compaction should use for a store of ``size_bytes`` at ``page_size``."""
    if size_bytes >= LARGE_STORE_MIN_BYTES:
        return PAGE_SIZE
    if size_bytes < TINY_STORE_MAX_BYTES:
        return TINY_PAGE_SIZE
    if size_bytes < SMALL_STORE_MAX_BYTES and page_size > SMALL_PAGE_SIZE:
        return SMALL_PAGE_SIZE
    if size_bytes >= TINY_STORE_GROW_BYTES and page_size < SMALL_PAGE_SIZE:
        return SMALL_PAGE_SIZE
    return page_size


SQL_TABLES = {
    "codex": ("threads", "thread_spawn_edges"),
    "hermes": ("sessions", "messages", "session_model_usage", "system_prompts"),
    "opencode": ("session", "message", "part", "session_message"),
}

# Never read account IDs or unrelated state tables from the Codex index.
CODEX_COLUMNS = {
    "id",
    "thread_id",
    "parent_thread_id",
    "child_thread_id",
    "rollout_path",
    "name",
    "title",
    "preview",
    "cwd",
    "source",
    "model",
    "model_provider",
    "reasoning_effort",
    "created_at",
    "updated_at",
    "archived",
    "archived_at",
    "git_sha",
    "git_branch",
    "git_origin_url",
    "agent_path",
    "spawn_call_id",
}


@contextmanager
def readonly_connection(path: str | Path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    _tune(connection)
    try:
        yield connection
    finally:
        connection.close()


def _tune(connection) -> None:
    # Large page cache and mmap for reads; temp B-trees stay in memory.
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA cache_size = -262144")
    connection.execute("PRAGMA mmap_size = 1073741824")


def _fact_migration(connection, sql):
    """The unpublished v7-v9 analytics preview already has some v11-v13 fields."""
    statements = []
    for statement in sql.split(";"):
        added = re.search(r"ALTER TABLE (\w+) ADD COLUMN (\w+) (TEXT|INTEGER)", statement)
        if added:
            table, name, datatype = added.groups()
            column = next(
                (r for r in connection.execute(f"PRAGMA table_info({table})") if r["name"] == name),
                None,
            )
            if column is not None:
                if column["type"] != datatype:
                    raise ValueError("Existing analytics preview field has an incompatible type")
                continue
        if statement.strip():
            statements.append(statement + ";")
    return "\n".join(statements)


def insert(connection, table: str, values: dict) -> None:
    values = payload.pack_row(connection, table, values)
    columns = ",".join(values)
    markers = ",".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({markers})", tuple(values.values())
    )


def insert_rows(connection, table: str, rows: Iterable[dict]) -> int:
    """Batch ``insert`` for rows sharing one column set (executemany)."""
    rows = [payload.pack_row(connection, table, row) for row in rows]
    if not rows:
        return 0
    columns = list(rows[0])
    if any(list(row) != columns for row in rows):
        raise ValueError("insert_rows requires identical columns in every row")
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [tuple(row.values()) for row in rows],
    )
    return len(rows)


def _json_cell(value):
    return {"$binary": base64.b64encode(value).decode()} if isinstance(value, bytes) else value


def sqlite_rows(path: Path, agent: str) -> Iterable[bytes]:
    """One consistent read transaction. Only explicit session tables are exported."""
    with readonly_connection(path) as connection:
        connection.execute("BEGIN")
        available = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in SQL_TABLES[agent]:
            if table not in available:
                continue
            columns = list(connection.execute(f'PRAGMA table_info("{table}")'))
            primary = [r["name"] for r in sorted(columns, key=lambda r: r["pk"]) if r["pk"]]
            if not primary:
                raise ValueError(f"Cannot version {table}: no primary key")
            # Use native chronology, never assume lexicographic PK order is chronology.
            names = {r["name"] for r in columns}
            preferred = {
                "session_message": ["session_id", "seq"],
                "message": ["session_id", "time_created", "id"],
                "part": ["session_id", "message_id", "id"],
                "messages": ["id"],
            }.get(table, [])
            ordering = list(dict.fromkeys([c for c in preferred if c in names] + primary))
            order = ",".join('"' + col.replace('"', '""') + '"' for col in ordering)
            selected = [
                r["name"] for r in columns if agent != "codex" or r["name"] in CODEX_COLUMNS
            ]
            if not set(primary) <= set(selected):
                raise ValueError("Unsupported primary key in session index")
            selection = ",".join('"' + col.replace('"', '""') + '"' for col in selected)
            for row in connection.execute(f'SELECT {selection} FROM "{table}" ORDER BY {order}'):
                data = {key: _json_cell(row[key]) for key in row.keys()}
                yield (
                    canonical(
                        {"table": table, "key": {key: data[key] for key in primary}, "row": data}
                    )
                    + "\n"
                ).encode()


def _record_lines(handle, format_name):
    if format_name == "json":
        # Only small, explicitly allowlisted sidecars use document JSON.
        raw = handle.read()
        if raw:
            yield raw
    else:
        yield from handle


class Store:
    def __init__(self, home: str | Path):
        self.home = Path(home).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.raw_dir = self.home / "raw"
        self.raw_dir.mkdir(exist_ok=True, mode=0o700)
        self.db_path = self.home / "tandem.db"
        descriptor = os.open(self.db_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        self.db = sqlite3.connect(self.db_path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # Only takes effect before the first page is written (a new store). Rows average
        # ~1.5 KB, so 4 KiB pages leave a quarter of each leaf empty; existing stores keep
        # their page size until a VACUUM.
        self.db.execute(f"PRAGMA page_size = {PAGE_SIZE}")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA busy_timeout = 5000")
        # WAL + NORMAL keeps committed data across process crashes; only power loss
        # can drop the last transactions, which a rescan recaptures from source files.
        self.db.execute("PRAGMA synchronous = NORMAL")
        _tune(self.db)
        self._compacted_pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            sql = files("tandem_data").joinpath("migrations/001.sql").read_text()
            self.db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
        elif not 1 <= version <= SCHEMA_VERSION:
            self.db.close()
            raise ValueError(
                f"Unsupported database version {version}; expected 1 through {SCHEMA_VERSION}"
            )
        manifest = self.db.execute(
            "SELECT name FROM sqlite_master WHERE name='schema_manifest'"
        ).fetchone()
        if (
            not manifest
            or self.db.execute("SELECT contract_id FROM schema_manifest").fetchone()[0]
            != "tandem-session-v1"
        ):
            self.db.close()
            raise ValueError(
                "This is a connector staging database, not tandem-session-v1. Use import-connector into a separate home."
            )

        if version < 2:
            sql = files("tandem_data").joinpath("migrations/002.sql").read_text()
            self.db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
        if version < 3:
            sql = files("tandem_data").joinpath("migrations/003.sql").read_text()
            self.db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
        if version < 4:
            # SQLite's table-copy migration procedure: disable FK enforcement only
            # on this connection, preserve IDs, validate all references before commit.
            sql = files("tandem_data").joinpath("migrations/004.sql").read_text()
            try:
                self.db.execute("PRAGMA foreign_keys=OFF")
                try:
                    self.db.executescript("BEGIN IMMEDIATE;\n" + sql)
                    if self.db.execute("PRAGMA foreign_key_check").fetchall():
                        raise ValueError("Project migration would break foreign keys")
                    self.db.execute("COMMIT")
                except BaseException:
                    if self.db.in_transaction:
                        self.db.execute("ROLLBACK")
                    raise
                finally:
                    self.db.execute("PRAGMA foreign_keys=ON")
            except BaseException:
                self.db.close()
                raise
        tables = {
            row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # Main's v5 contains inventory; early PR #35 v5 databases instead contain
        # source references. Upgrade both without dropping observations or indexes.
        if version < 5 or (version == 5 and "inventory_scan" not in tables):
            sql = files("tandem_data").joinpath("migrations/005.sql").read_text()
            self.db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
        if version < 6:
            if "source_reference" in tables:
                self.db.executescript(
                    "BEGIN IMMEDIATE; UPDATE schema_manifest SET schema_version=6; PRAGMA user_version=6; COMMIT;"
                )
            else:
                sql = files("tandem_data").joinpath("migrations/006.sql").read_text()
                self.db.execute("PRAGMA foreign_keys=OFF")
                try:
                    self.db.executescript("BEGIN IMMEDIATE;\n" + sql)
                    if self.db.execute("PRAGMA foreign_key_check").fetchall():
                        raise ValueError("Source reference migration would break foreign keys")
                    self.db.execute("COMMIT")
                except BaseException:
                    if self.db.in_transaction:
                        self.db.execute("ROLLBACK")
                    raise
                finally:
                    self.db.execute("PRAGMA foreign_keys=ON")
        # The unpublished analytics preview used v7-v9 for logical fields, while
        # main uses v8-v10 for physical storage. Converge both without dropping facts.
        if (
            version in (7, 8, 9)
            and "content_blob" not in tables
            and any(
                r["name"] == "request_identity_quality"
                for r in self.db.execute("PRAGMA table_info(model_call)")
            )
        ):
            self.db.executescript(
                "BEGIN IMMEDIATE; UPDATE schema_manifest SET schema_version=6; PRAGMA user_version=6; COMMIT;"
            )
            version = 6
        # 007 remains reserved for feat/data-app-integration. Each step publishes
        # its version atomically so an interrupted physical upgrade can resume.
        for number in range(7, SCHEMA_VERSION + 1):
            migration = files("tandem_data").joinpath(f"migrations/{number:03d}.sql")
            if version < number and migration.is_file():
                sql = migration.read_text()
                if number in (11, 12, 13):
                    sql = _fact_migration(self.db, sql)
                self.db.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + sql
                    + f"\nUPDATE schema_manifest SET schema_version={number}; PRAGMA user_version={number}; COMMIT;"
                )
        os.chmod(self.home, 0o700)
        os.chmod(self.raw_dir, 0o700)
        for path in (
            self.db_path,
            Path(str(self.db_path) + "-wal"),
            Path(str(self.db_path) + "-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute("PRAGMA defer_foreign_keys = ON")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def add_source(self, agent: str, root: str | Path, label: str | None = None) -> str:
        root_path = str(Path(root).expanduser().resolve())
        if self.home.is_relative_to(root_path):
            raise ValueError("The data directory must be outside the Agent source root")
        source_id = uid("source", agent, root_path)
        self.db.execute(
            "INSERT INTO source(source_id,agent,root_path,label,discovered_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(source_id) DO UPDATE SET label=COALESCE(excluded.label,source.label)",
            (source_id, agent, root_path, label, now_ms()),
        )
        return source_id

    def identity(self, source_id: str, native_id: str, file_scope: str | None = None) -> str:
        key = canonical([native_id, file_scope] if file_scope else [native_id])
        session_uid = uid("session", source_id, json.loads(key))
        self.db.execute(
            "INSERT OR IGNORE INTO session_identity VALUES(?,?,?,?)",
            (session_uid, source_id, native_id, key),
        )
        return session_uid

    def issue(
        self,
        source_id: str,
        code: str,
        *,
        stage="l2",
        file_id=None,
        record_uid=None,
        severity="warning",
        detail=None,
    ):
        # A capture can fail before source_file exists; retain each failed path separately.
        location = file_id if file_id is not None else (detail or {}).get("path")
        values = {
            "issue_uid": uid("issue", source_id, stage, code, location, record_uid),
            "source_id": source_id,
            "file_id": file_id,
            "record_uid": record_uid,
            "stage": stage,
            "code": code,
            "severity": severity,
            "detail": canonical(detail or {}),
            "detected_at": now_ms(),
        }
        self.db.execute("DELETE FROM ingest_issue WHERE issue_uid=?", (values["issue_uid"],))
        insert(self.db, "ingest_issue", values)

    def capture_file(self, source_id: str, path: str | Path, role="transcript") -> dict:
        from tandem_data.indexing import index_file

        return index_file(self, source_id, path, role)

    def capture_stream(
        self,
        source_id: str,
        relative_path: str,
        chunks: Iterable[bytes],
        *,
        format_name="jsonl",
        role="transcript",
        source_stat=None,
    ) -> dict:
        """Public L0-L1 boundary for connector-produced bytes (including SQL row exports).

        Source has to be registered. Callers provide bytes, not filesystem write privileges.
        A changed SQL primary-key row gets a monotonically increasing version, even A->B->A.
        """
        if format_name not in ("jsonl", "jsonl_zstd", "sqlite_rows", "json"):
            raise ValueError("Unsupported record encoding")
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Relative source location must stay within its root")
        existing = self.db.execute(
            "SELECT file_id FROM source_file WHERE source_id=? AND relative_path=?",
            (source_id, relative_path),
        ).fetchone()
        file_id = existing["file_id"] if existing else uid("file", source_id, relative_path)
        source_stat = {**(source_stat or {}), "capture_format": format_name}
        digest = hashlib.sha256()
        byte_len = 0
        with tempfile.NamedTemporaryFile(dir=self.raw_dir, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with zstd.ZstdCompressor(level=3).stream_writer(temporary, closefd=False) as writer:
                    for block in chunks:
                        digest.update(block)
                        byte_len += len(block)
                        writer.write(block)
                temporary.flush()
                os.fsync(temporary.fileno())
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
        sha = digest.hexdigest()
        blob_path = self.raw_dir / f"{sha}.zst"
        if blob_path.exists():
            temporary_path.unlink()
        else:
            temporary_path.replace(blob_path)
        captured_at = now_ms()
        # Publish L0 before decoding. A malformed/truncated source cannot erase its archive.
        self.db.execute(
            "INSERT OR IGNORE INTO archive_blob VALUES(?,?,?,?,?,?,?)",
            (
                uid("archive", sha),
                str(blob_path.relative_to(self.home)),
                sha,
                byte_len,
                blob_path.stat().st_size,
                "zstd",
                captured_at,
            ),
        )
        self._remember_archive_formats(file_id)
        self.db.execute(
            "INSERT INTO source_file(file_id,source_id,relative_path,role,format,last_scan_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(file_id) DO UPDATE SET status='active',watermark=CASE WHEN role<>excluded.role OR format<>excluded.format THEN json_remove(watermark,'$.projected_revision') ELSE watermark END,role=excluded.role,format=excluded.format,last_scan_at=excluded.last_scan_at",
            (file_id, source_id, relative_path, role, format_name, captured_at),
        )
        with self._index_transaction(source_id, file_id, uid("archive", sha)):
            latest = self.db.execute(
                "SELECT * FROM source_revision WHERE file_id=? ORDER BY revision DESC LIMIT 1",
                (file_id,),
            ).fetchone()
            if (
                latest
                and latest["archive_uid"] == uid("archive", sha)
                and json.loads(latest["source_stat"]).get("capture_format") == format_name
            ):
                # Cache the latest stat without mutating immutable capture provenance.
                self.db.execute(
                    "UPDATE source_file SET watermark=json_set(watermark,'$.last_source_stat',json(?)) WHERE file_id=?",
                    (canonical(source_stat or {}), file_id),
                )
                self._resolve_capture_issues(source_id, file_id)
                return {"file_id": file_id, "changed": False, "records": latest["record_count"]}
            revision = latest["revision"] + 1 if latest else 1
            revision_uid = uid("revision", file_id, revision)
            self.db.execute(
                "INSERT INTO source_revision VALUES(?,?,?,?,?,?,?)",
                (
                    revision_uid,
                    file_id,
                    revision,
                    uid("archive", sha),
                    captured_at,
                    canonical(source_stat or {}),
                    0,
                ),
            )
            with self._decoded(blob_path, format_name) as handle:
                count, offset, _ = self._index_lines(
                    file_id, revision_uid, _record_lines(handle, format_name), format_name, role
                )
            self.db.execute(
                "UPDATE source_revision SET record_count=? WHERE revision_uid=?",
                (count, revision_uid),
            )
            self.db.execute(
                "UPDATE source_file SET watermark=? WHERE file_id=?",
                (
                    canonical(
                        {
                            "revision": revision,
                            "source_sha256": sha,
                            "decoded_bytes": offset,
                            "records": count,
                            "capture": "immutable_snapshot",
                            "last_source_stat": source_stat or {},
                        }
                    ),
                    file_id,
                ),
            )
        self._resolve_capture_issues(source_id, file_id)
        return {"file_id": file_id, "changed": True, "records": count}

    def _remember_archive_formats(self, file_id):
        # Backfill old revisions before the mutable source_file encoding changes.
        # Future revisions write this provenance at capture time.
        self.db.execute(
            "UPDATE source_revision SET source_stat=json_set(source_stat,'$.capture_format',"
            "(SELECT format FROM source_file f WHERE f.file_id=source_revision.file_id)) "
            "WHERE file_id=? AND archive_uid IS NOT NULL AND json_type(source_stat,'$.capture_format') IS NULL",
            (file_id,),
        )

    def _index_lines(self, file_id, revision_uid, lines, format_name, role, *, reference=False):
        previous = {
            row["locator"]: dict(row)
            for row in self.db.execute(
                "SELECT r.* FROM file_record f JOIN raw_record r USING(record_uid) WHERE f.file_id=?",
                (file_id,),
            )
        }
        self.db.execute("DELETE FROM file_record WHERE file_id=?", (file_id,))
        count, offset = 0, 0
        digest = hashlib.sha256()
        for ordinal, line in enumerate(lines):
            digest.update(line)
            row_sha = hashlib.sha256(line).hexdigest()
            try:
                if format_name in ("jsonl", "jsonl_zstd") and not line.endswith(b"\n"):
                    raise ValueError("pending_tail")
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError("Record must be an object")
                if format_name == "sqlite_rows":
                    locator = canonical(["row", data["table"], data["key"]])
                    native_type = "table:" + data["table"]
                else:
                    locator = canonical(["line", ordinal])
                    native_type = str(
                        data.get("type", role if format_name == "json" else "unknown")
                    )
                native_id = data.get("uuid", data.get("id"))
                shape_hash = uid("shape", shape(data))
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                data, locator, native_type, native_id, shape_hash = (
                    {},
                    canonical(["line", ordinal]),
                    "pending_tail"
                    if format_name in ("jsonl", "jsonl_zstd") and not line.endswith(b"\n")
                    else "invalid",
                    None,
                    None,
                )
            old = previous.get(locator)
            if old and old["sha256"] == row_sha:
                record_uid = old["record_uid"]
            else:
                version = self.db.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM raw_record "
                    "WHERE file_id=? AND locator=?",
                    (file_id, locator),
                ).fetchone()[0]
                record_uid = uid("record", file_id, json.loads(locator), version)
                insert(
                    self.db,
                    "raw_record",
                    {
                        "record_uid": record_uid,
                        "file_id": file_id,
                        "revision_uid": revision_uid,
                        "locator": locator,
                        "version": version,
                        "ordinal": ordinal,
                        "byte_offset": offset,
                        "byte_len": len(line),
                        "sha256": row_sha,
                        "native_type": native_type,
                        "native_id": str(native_id) if native_id is not None else None,
                        "harness_version": str(data.get("version", data.get("cli_version", "")))
                        or None,
                        "shape_hash": shape_hash,
                    },
                )
            if native_type == "pending_tail":
                self.db.execute(
                    "UPDATE raw_record SET disposition='ignored',note=? WHERE record_uid=?",
                    (canonical({"reason": "incomplete_tail_retained_in_L0"}), record_uid),
                )
            self.db.execute("INSERT INTO file_record VALUES(?,?,?)", (file_id, locator, record_uid))
            if reference:
                self.db.execute(
                    "INSERT INTO record_location VALUES(?,?,?,?,?)",
                    (record_uid, revision_uid, ordinal, offset, len(line)),
                )
                if native_type == "table:session_model_usage":
                    fields = {
                        "session_id",
                        "model",
                        "billing_provider",
                        "task",
                        "input_tokens",
                        "output_tokens",
                        "cache_read_tokens",
                        "cache_write_tokens",
                        "reasoning_tokens",
                        "actual_cost_usd",
                        "estimated_cost_usd",
                        "cost_status",
                        "cost_source",
                        "last_seen",
                    }
                    observation = {
                        **data,
                        "row": {k: v for k, v in data["row"].items() if k in fields},
                    }
                    self.db.execute(
                        "INSERT OR IGNORE INTO usage_observation VALUES(?,?)",
                        (record_uid, canonical(observation)),
                    )
            offset += len(line)
            count += 1
        return count, offset, digest.hexdigest()

    def _resolve_capture_issues(self, source_id, file_id):
        self.db.execute(
            "UPDATE ingest_issue SET detail=json_set(detail,'$.status','resolved','$.resolved_at',?) WHERE source_id=? AND stage='l1' AND (file_id=? OR (file_id IS NULL AND code='capture_failed' AND json_extract(detail,'$.path')=(SELECT relative_path FROM source_file WHERE file_id=?)))",
            (now_ms(), source_id, file_id, file_id),
        )

    @contextmanager
    def _index_transaction(self, source_id, file_id, archive_uid):
        try:
            with self.transaction():
                yield
        except (ValueError, zstd.ZstdError) as error:
            self.db.execute("UPDATE source_file SET status='error' WHERE file_id=?", (file_id,))
            self.issue(
                source_id,
                "invalid_source_archive",
                stage="l1",
                file_id=file_id,
                detail={"archive_uid": archive_uid, "exception": type(error).__name__},
            )
            raise

    @contextmanager
    def _decoded(self, blob_path: Path, format_name: str):
        with blob_path.open("rb") as raw:
            with zstd.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as stored:
                if format_name == "jsonl_zstd":
                    # Check EOF for each native frame; stream_reader alone accepts truncated tails.
                    with tempfile.TemporaryFile() as decoded:
                        decompressor = zstd.ZstdDecompressor().decompressobj()
                        had_frame = False
                        while block := stored.read(1024 * 1024):
                            while block:
                                if decompressor.eof:
                                    decompressor = zstd.ZstdDecompressor().decompressobj()
                                decoded.write(decompressor.decompress(block))
                                block = decompressor.unused_data
                                had_frame = had_frame or decompressor.eof
                        if not had_frame or not decompressor.eof:
                            raise ValueError("Incomplete native zstd frame")
                        decoded.seek(0)
                        yield decoded
                else:
                    yield io.BufferedReader(stored)

    def iter_file(self, file_id: str) -> Iterable[RawRecord]:
        from tandem_data.indexing import iter_indexed_file

        if file_id in getattr(self, "_unavailable_files", ()):
            return  # Rebuild retains published facts; never invent missing native records.
        latest = self.db.execute(
            "SELECT archive_uid FROM source_revision WHERE file_id=? ORDER BY revision DESC LIMIT 1",
            (file_id,),
        ).fetchone()
        if latest and latest["archive_uid"] is None:
            yield from iter_indexed_file(self, file_id)
            return
        info = self.db.execute(
            "SELECT f.*,s.agent,r.revision_uid,a.path,COALESCE(json_extract(r.source_stat,'$.capture_format'),f.format) AS archive_format FROM source_file f "
            "JOIN source s USING(source_id) JOIN source_revision r USING(file_id) "
            "JOIN archive_blob a USING(archive_uid) WHERE f.file_id=? "
            "ORDER BY r.revision DESC LIMIT 1",
            (file_id,),
        ).fetchone()
        if not info:
            return
        format_name = info["archive_format"]
        with self._decoded(self.home / info["path"], format_name) as handle:
            for ordinal, line in enumerate(_record_lines(handle, format_name)):
                try:
                    if format_name in ("jsonl", "jsonl_zstd") and not line.endswith(b"\n"):
                        continue
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        continue
                    locator = (
                        canonical(["row", data["table"], data["key"]])
                        if format_name == "sqlite_rows"
                        else canonical(["line", ordinal])
                    )
                except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                    continue
                row = self.db.execute(
                    "SELECT r.*,v.captured_at FROM file_record f JOIN raw_record r USING(record_uid) "
                    "JOIN source_revision v USING(revision_uid) WHERE f.file_id=? AND f.locator=?",
                    (file_id, locator),
                ).fetchone()
                if row:
                    yield RawRecord(
                        row["record_uid"],
                        info["source_id"],
                        info["agent"],
                        file_id,
                        info["relative_path"],
                        ordinal,
                        row["version"],
                        row["native_type"],
                        data,
                        row["captured_at"],
                    )

    def iter_versions(self, file_id: str, native_type: str) -> Iterable[RawRecord]:
        """Read historical SQL row versions with one sequential decode per revision."""
        info = self.db.execute(
            "SELECT f.*,s.agent FROM source_file f JOIN source s USING(source_id) WHERE file_id=?",
            (file_id,),
        ).fetchone()
        for revision in self.db.execute(
            "SELECT v.*,a.path FROM source_revision v LEFT JOIN archive_blob a USING(archive_uid) WHERE file_id=? ORDER BY revision",
            (file_id,),
        ).fetchall():
            if revision["archive_uid"] is None:
                for row in self.db.execute(
                    "SELECT r.*,o.observation FROM raw_record r JOIN usage_observation o USING(record_uid) "
                    "WHERE r.revision_uid=? AND r.native_type=? ORDER BY r.ordinal",
                    (revision["revision_uid"], native_type),
                ):
                    yield RawRecord(
                        row["record_uid"],
                        info["source_id"],
                        info["agent"],
                        file_id,
                        info["relative_path"],
                        row["ordinal"],
                        row["version"],
                        native_type,
                        json.loads(row["observation"]),
                        revision["captured_at"],
                    )
                continue
            targets = self.db.execute(
                "SELECT * FROM raw_record WHERE revision_uid=? AND native_type=? ORDER BY byte_offset",
                (revision["revision_uid"], native_type),
            ).fetchall()
            if not targets:
                continue
            format_name = json.loads(revision["source_stat"]).get("capture_format", info["format"])
            with self._decoded(self.home / revision["path"], format_name) as handle:
                position = 0
                for row in targets:
                    remaining = row["byte_offset"] - position
                    while remaining:
                        part = handle.read(min(remaining, 1024 * 1024))
                        if not part:
                            raise ValueError("Archive shorter than L1 locator")
                        remaining -= len(part)
                    raw = handle.read(row["byte_len"])
                    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                        raise ValueError("L0 record hash mismatch")
                    position = row["byte_offset"] + row["byte_len"]
                    yield RawRecord(
                        row["record_uid"],
                        info["source_id"],
                        info["agent"],
                        file_id,
                        info["relative_path"],
                        row["ordinal"],
                        row["version"],
                        native_type,
                        json.loads(raw),
                        revision["captured_at"],
                    )

    def read_raw(self, record_uid: str) -> bytes:
        from tandem_data.source_reader import read_reference, reference_info

        if reference_info(self.db, record_uid) is not None:
            return read_reference(self.db, record_uid)
        row = self.db.execute(
            "SELECT r.*,a.path,COALESCE(json_extract(v.source_stat,'$.capture_format'),f.format) AS format FROM raw_record r JOIN source_revision v USING(revision_uid) "
            "JOIN archive_blob a USING(archive_uid) JOIN source_file f USING(file_id) WHERE record_uid=?",
            (record_uid,),
        ).fetchone()
        if not row:
            raise KeyError(record_uid)
        with self._decoded(self.home / row["path"], row["format"]) as handle:
            remaining = row["byte_offset"]
            while remaining:
                block = handle.read(min(remaining, 1024 * 1024))
                if not block:
                    raise ValueError("Archive is shorter than its L1 locator")
                remaining -= len(block)
            data = handle.read(row["byte_len"])
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("L0 record hash mismatch")
        return data

    def rebuild(
        self, *, mapper_version=None, source_ids=None, progress=None, optimize=True
    ) -> dict:
        """Rebuild L2; ``optimize=False`` leaves maintenance to the import service."""
        from tandem_data.pipeline import rebuild_retaining

        # A source rewritten or truncated after capture must not block every other file:
        # the failed attempt rolls back and is retried with that file's last facts retained.
        try:
            result = rebuild_retaining(
                self, mapper_version=mapper_version, source_ids=source_ids, progress=progress
            )
        finally:
            self._unavailable_files = set()
        if optimize:
            self.optimize()
        return result

    def optimize(self) -> None:
        """Post-import maintenance: drop unreferenced blobs, refresh planner stats."""
        if self.db.in_transaction:
            return
        payload.collect_garbage(self.db)
        self.db.execute("PRAGMA optimize")
        self.db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
        self.compact()

    def compact(self, *, force: bool = False) -> bool:
        """VACUUM after enough growth since the last compaction; logical contents are unchanged."""
        if self.db.in_transaction:
            return False
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        size = self.db.execute("PRAGMA page_size").fetchone()[0]
        target = target_page_size(pages * size, size)
        if not force and target == size and pages < COMPACT_GROWTH * self._compacted_pages:
            return False
        self._vacuum(size, target)
        return True

    def maintain(self, *, force: bool = False) -> dict:
        """Post-publish maintenance run by the import service, never inside an import.

        Measures where the slack is first: free pages (``freelist_count``) are returned
        with ``incremental_vacuum`` when the store allows it; only slack inside used pages
        (dbstat ``unused``: fragmentation from bulk loads and random-key indexes) or a page
        size change needs a full VACUUM. Logical contents never change.
        """
        if self.db.in_transaction:
            return {"action": "skipped"}
        started = time.perf_counter()
        payload.collect_garbage(self.db)
        self.db.execute("PRAGMA optimize")
        self.db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
        size = self.db.execute("PRAGMA page_size").fetchone()[0]
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        free = self.db.execute("PRAGMA freelist_count").fetchone()[0]
        target = target_page_size(pages * size, size)
        state = self.home / "maintenance.json"
        try:
            checked = json.loads(state.read_text())["pages"]
        except (OSError, ValueError, KeyError, TypeError):
            checked = 0
        if (
            not force
            and target == size
            and checked
            and pages < MAINTAIN_GROWTH * checked
            and free < MAINTAIN_FREE_SHARE * pages
        ):
            # Steady state (watch rescans, appends): skip the full dbstat scan.
            return {
                "action": "none",
                "free_pages": free,
                "page_size": size,
                "bytes": pages * size,
                "seconds": round(time.perf_counter() - started, 4),
            }
        unused = self.db.execute(
            "SELECT COALESCE(SUM(unused),0) FROM dbstat WHERE aggregate=TRUE"
        ).fetchone()[0]
        used_bytes = max(1, (pages - free) * size)
        result = {
            "bytes_before": pages * size,
            "page_size_before": size,
            "free_pages": free,
            "slack": round(unused / used_bytes, 4),
        }
        if force or target != size or unused > VACUUM_SLACK * used_bytes:
            self._vacuum(size, target)
            result["action"] = "vacuum"
        elif free and self.db.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:
            self.db.execute("PRAGMA incremental_vacuum").fetchall()
            self.db.execute("PRAGMA main.wal_checkpoint(TRUNCATE)").fetchall()
            result["action"] = "incremental_vacuum"
        else:
            result["action"] = "none"
        result["page_size"] = self.db.execute("PRAGMA page_size").fetchone()[0]
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        result["bytes"] = result["page_size"] * pages
        state.write_text(json.dumps({"pages": pages, "page_size": result["page_size"]}))
        result["seconds"] = round(time.perf_counter() - started, 4)
        return result

    def _vacuum(self, size: int, target: int) -> None:
        # Incremental auto-vacuum lets later maintenance return free pages without a full
        # rewrite; the mode is only adopted by a VACUUM, so it is set right before one.
        self.db.execute("PRAGMA auto_vacuum = INCREMENTAL")
        if target == size or not self._vacuum_page_size(target):
            self.db.execute("VACUUM")
        self.db.execute("PRAGMA main.wal_checkpoint(TRUNCATE)").fetchall()
        self._compacted_pages = self.db.execute("PRAGMA page_count").fetchone()[0]

    def _vacuum_page_size(self, page_size: int) -> bool:
        """VACUUM into a new page size; WAL stores must briefly leave WAL mode for that.

        Leaving WAL needs the only connection; when a reader is open it is refused and the
        caller falls back to a plain VACUUM with the current page size.
        """
        try:
            mode = self.db.execute("PRAGMA journal_mode = DELETE").fetchall()[0][0]
        except sqlite3.OperationalError:
            return False
        try:
            if str(mode).lower() != "delete":
                return False
            self.db.execute(f"PRAGMA page_size = {page_size}")
            self.db.execute("VACUUM")
            return True
        finally:
            self.db.execute("PRAGMA journal_mode = WAL").fetchall()

    def verify(self) -> dict:
        from tandem_data.contract import validate_event

        checked = 0
        for blob in self.db.execute("SELECT * FROM archive_blob"):
            digest = hashlib.sha256()
            with self._decoded(self.home / blob["path"], "jsonl") as handle:
                while block := handle.read(1024 * 1024):
                    digest.update(block)
            if digest.hexdigest() != blob["sha256"]:
                raise ValueError("L0 archive hash mismatch")
            checked += 1
        # Verify locators and every L1 digest with linear reads, including superseded rows.
        records_verified = 0
        for revision in self.db.execute(
            "SELECT v.revision_uid,a.path,COALESCE(json_extract(v.source_stat,'$.capture_format'),f.format) AS format FROM source_revision v JOIN archive_blob a USING(archive_uid) JOIN source_file f USING(file_id)"
        ).fetchall():
            targets = self.db.execute(
                "SELECT byte_offset,byte_len,sha256 FROM raw_record WHERE revision_uid=? ORDER BY byte_offset",
                (revision["revision_uid"],),
            )
            with self._decoded(self.home / revision["path"], revision["format"]) as handle:
                position = 0
                for target in targets:
                    remaining = target["byte_offset"] - position
                    while remaining:
                        block = handle.read(min(remaining, 1024 * 1024))
                        if not block:
                            raise ValueError("Archive shorter than L1 locator")
                        remaining -= len(block)
                    data = handle.read(target["byte_len"])
                    if hashlib.sha256(data).hexdigest() != target["sha256"]:
                        raise ValueError("L1 record digest mismatch")
                    position = target["byte_offset"] + target["byte_len"]
                    records_verified += 1
        from tandem_data.indexing import iter_indexed_file
        from tandem_data.source_reader import SourceUnavailable

        source_references_verified = 0
        unavailable_sources = []
        for row in self.db.execute(
            "SELECT f.file_id FROM source_file f WHERE (SELECT archive_uid FROM source_revision v "
            "WHERE v.file_id=f.file_id ORDER BY revision DESC LIMIT 1) IS NULL"
        ).fetchall():
            try:
                for _ in iter_indexed_file(self, row["file_id"]):
                    pass  # The stream validates every row and its aggregate digest.
                records_verified += self.db.execute(
                    "SELECT COUNT(*) FROM file_record WHERE file_id=?", (row["file_id"],)
                ).fetchone()[0]
                source_references_verified += 1
            except (SourceUnavailable, OSError, sqlite3.Error, zstd.ZstdError) as error:
                unavailable_sources.append(
                    {"file_id": row["file_id"], "status": getattr(error, "status", "unreadable")}
                )
        inconsistent = self.db.execute(
            "SELECT COUNT(*) FROM v_raw_record_ledger WHERE (disposition IN ('mapped','folded','replayed','duplicate') AND event_count=0) OR (disposition IN ('ignored','unparsed') AND event_count>0)"
        ).fetchone()[0]
        if inconsistent:
            raise ValueError("L1 dispositions disagree with evidence links")
        blobs = payload.verify(self.db)
        cache = {}
        for row in self.db.execute("SELECT * FROM event"):
            envelope = payload.restore_row(self.db, row, cache)
            for name in ("attrs", "ext", "native_key"):
                envelope[name] = json.loads(envelope[name])
            envelope["ext"] = payload.restore(self.db, envelope["ext"], cache)
            if len(cache) > 256:
                cache.clear()
            validate_event(envelope)
        if self.db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Broken foreign keys")
        if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        counts = dict(
            self.db.execute("SELECT disposition,COUNT(*) FROM raw_record GROUP BY disposition")
        )
        total = self.db.execute("SELECT COUNT(*) FROM raw_record").fetchone()[0]
        if sum(counts.values()) != total:
            raise ValueError("Raw record accounting failed")
        return {
            "integrity": "partial" if unavailable_sources else "ok",
            "archives_verified": checked,
            "source_references_verified": source_references_verified,
            "unavailable_sources": unavailable_sources,
            "record_hashes_verified": records_verified,
            "records": total,
            "dispositions": counts,
            "unparsed": counts.get("unparsed", 0),
            "content_blobs": blobs,
        }
