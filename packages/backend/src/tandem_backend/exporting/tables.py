"""Exportable detail tables (EXP-02 / MB-06): the only columns a CSV may contain.

Each column names its origin (``table.column`` in tandem.db) so tests can check it against
the migrations. No raw event text, file contents or arguments leave the app, except the
redacted ``args_summary`` (≤ 120 characters) of a tool call. Timestamp columns also get
a ``<name>_iso`` UTC column in the CSV.
"""

from __future__ import annotations

from dataclasses import dataclass

ARGS_LIMIT = 120
# args_summary is redacted *before* it is cut to ARGS_LIMIT: SQL hands over this much text
# so a secret is never split by the read boundary (a cut token no longer matches the
# redaction patterns, and a long secret earlier in the text shrinks to a short placeholder,
# pulling later text into the first 120 characters). 4 000 chars bounds memory per row
# while staying far beyond any token pattern length.
ARGS_SOURCE_CHARS = 4_000


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # text | integer | real | timestamp
    expr: str  # SQL over the table's FROM clause
    origin: str  # tandem.db table.column it is read from
    redacted: bool = False


@dataclass(frozen=True)
class Table:
    id: str
    title: str
    source: str  # tandem.db table whose MAX(rowid) approximates the row count
    joins: str  # FROM … with alias s = session, src = source
    time_column: str
    order: str
    columns: tuple[Column, ...]


ALIASES = {"t": "tool_call", "s": "session", "m": "model_call", "src": "source", "e": "event"}


def _c(name, type_, expr, origin=None, redacted=False):
    if origin is None:  # plain "alias.column"
        alias, column = expr.split(".")
        origin = f"{ALIASES[alias]}.{column}"
    return Column(name, type_, expr, origin, redacted)


TABLES: dict[str, Table] = {t.id: t for t in (
    Table("tool_calls", "工具调用", "tool_call",
          "tool_call t JOIN session s ON s.session_uid = t.session_uid "
          "JOIN source src ON src.source_id = s.source_id "
          "LEFT JOIN event e ON e.event_uid = t.call_event_uid",
          "t.started_at", "t.started_at, t.call_uid", (
              _c("call_uid", "text", "t.call_uid"),
              _c("session_uid", "text", "t.session_uid"),
              _c("project_id", "text", "t.project_id"),
              _c("agent", "text", "src.agent", "source.agent"),
              _c("name", "text", "t.name"),
              _c("kind", "text", "t.kind"),
              _c("command_head", "text", "t.command_head", redacted=True),
              _c("mcp_server", "text", "t.mcp_server"),
              _c("skill", "text", "t.skill"),
              _c("status", "text", "t.status"),
              _c("exit_code", "integer", "t.exit_code"),
              _c("error_class", "text", "t.error_class"),
              _c("duration_ms", "integer", "t.duration_ms"),
              _c("started_at", "timestamp", "t.started_at"),
              _c("approval_wait_ms", "integer", "t.approval_wait_ms"),
              # Only the first 400 characters are read; the cell is redacted and clipped.
              _c("args_summary", "text", f"substr(e.text, 1, {ARGS_SOURCE_CHARS})", "event.text", True),
          )),
    Table("sessions", "会话", "session",
          "session s JOIN source src ON src.source_id = s.source_id",
          "s.started_at", "s.started_at, s.session_uid", (
              _c("session_uid", "text", "s.session_uid"),
              _c("agent", "text", "src.agent", "source.agent"),
              _c("project_id", "text", "s.project_id"),
              _c("title", "text", "s.title", redacted=True),
              _c("kind", "text", "s.kind"),
              _c("started_at", "timestamp", "s.started_at"),
              _c("ended_at", "timestamp", "s.ended_at"),
              _c("status", "text", "s.status"),
              _c("model", "text", "(SELECT m.model_id FROM model_call m WHERE m.session_uid = "
                 "s.session_uid AND m.model_id IS NOT NULL GROUP BY m.model_id "
                 "ORDER BY COUNT(*) DESC, m.model_id LIMIT 1)", "model_call.model_id"),
          )),
    Table("model_calls", "模型调用用量", "model_call",
          "model_call m JOIN session s ON s.session_uid = m.session_uid "
          "JOIN source src ON src.source_id = s.source_id",
          "m.ts", "m.ts, m.call_uid", (
              _c("session_uid", "text", "m.session_uid"),
              _c("model_id", "text", "m.model_id"),
              _c("ts", "timestamp", "m.ts"),
              *(_c(name, "integer", f"m.{name}") for name in (
                  "input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
                  "reasoning_tokens")),
              _c("cost_usd", "real", "m.cost_usd"),
              _c("latency_ms", "integer", "m.latency_ms"),
              _c("ttft_ms", "integer", "m.ttft_ms"),
          )),
)}

SCOPE_FILTERS = ("project_id", "agent", "from_ts", "until_ts", "limit", "include_excluded")


def describe(table: Table, approx_rows: int | None) -> dict:
    return {"id": table.id, "title": table.title,
            "columns": [{"name": c.name, "type": c.type, "redacted": c.redacted}
                        for c in table.columns],
            "scope_filters": list(SCOPE_FILTERS), "approx_rows": approx_rows}


def header(table: Table) -> list[str]:
    out = []
    for column in table.columns:
        out.append(column.name)
        if column.type == "timestamp":
            out.append(f"{column.name}_iso")
    return out
