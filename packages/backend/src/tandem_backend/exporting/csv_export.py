"""CSV export of an allowlisted table (EXP-02): one snapshot read, streamed in 5k-row chunks.

RFC 4180 quoting with CRLF line ends, NULL as an empty cell, an ``*_iso`` UTC column after
each timestamp, and a spreadsheet formula guard: a text cell starting with = + - @ tab or
CR gets a leading single quote.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .tables import ARGS_LIMIT, Table

CHUNK = 5000
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


class ExportError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def guard(value: str) -> str:
    return "'" + value if value.startswith(FORMULA_START) else value


def iso(ms) -> str | None:
    if not isinstance(ms, int) or isinstance(ms, bool):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except (ValueError, OverflowError, OSError):
        return None


def redact_cell(value: str, limit: int | None = None) -> str:
    from ..ai.redact import redact2

    text, _ = redact2(value)
    if limit is not None:
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > limit:
            text = text[:limit - 1] + "…"
    return text


def encode_row(table: Table, row) -> list:
    out = []
    for column, value in zip(table.columns, row, strict=True):
        if value is not None and column.redacted:
            value = redact_cell(str(value), ARGS_LIMIT if column.name == "args_summary" else None)
        if isinstance(value, str):
            value = guard(value)
        out.append("" if value is None else value)
        if column.type == "timestamp":
            out.append(iso(value) or "")
    return out


def lines(rows: list[list]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue()


def query(table: Table, *, project_ids=(), agents=(), from_ts=None, until_ts=None,
          excluded=(), limit: int) -> tuple[str, list]:
    clauses, params = [], []
    if project_ids:
        clauses.append(f"s.project_id IN ({','.join('?' * len(project_ids))})")
        params.extend(project_ids)
    if agents:
        clauses.append(f"src.agent IN ({','.join('?' * len(agents))})")
        params.extend(agents)
    if from_ts is not None:
        clauses.append(f"{table.time_column} >= ?")
        params.append(from_ts)
    if until_ts is not None:
        clauses.append(f"{table.time_column} < ?")
        params.append(until_ts)
    if excluded:
        clauses.append("s.session_uid NOT IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(sorted(excluded)))
    select = ", ".join(c.expr for c in table.columns)
    where = " AND ".join(clauses) or "1"
    return (f"SELECT {select} FROM {table.joins} WHERE {where} ORDER BY {table.order} LIMIT ?",
            [*params, limit])


def open_snapshot(path: Path) -> sqlite3.Connection:
    """Read-only connection holding one read transaction for the whole download: the
    published snapshot, also while newer captures are still being published."""
    from tandem_data.query import published_projection

    if not path.is_file():
        raise ExportError(503, "no_projection", "No canonical database yet; import a source")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,
                                 check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN")
        published_projection(connection)
    except ValueError as error:
        connection.close()
        code = "projection_pending" if "pending" in str(error) else "rebuild_required"
        raise ExportError(503, code, str(error)) from error
    except sqlite3.Error as error:
        connection.close()
        raise ExportError(503, "no_projection", str(error)) from error
    return connection


def stream(connection: sqlite3.Connection, table: Table, sql: str, params: list,
           header: list[str]) -> Iterator[str]:
    """Header first, then one CSV block per CHUNK rows; closes the connection at the end."""
    try:
        yield lines([header])
        cursor = connection.execute(sql, params)
        while rows := cursor.fetchmany(CHUNK):
            yield lines([encode_row(table, row) for row in rows])
    finally:
        connection.close()


def approx_rows(path: Path, table: Table) -> int | None:
    """MAX(rowid) is an index lookup; deleted rows make it an upper bound."""
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            return connection.execute(f"SELECT MAX(rowid) FROM {table.source}").fetchone()[0] or 0
    except sqlite3.Error:
        return None
