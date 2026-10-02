"""Tool-call drilldown (AN-01.2): one keyset-paginated SQL over tandem.db, newest first.

``query`` is pure given a connection. ``args_summary`` comes from the call event's
``attrs.input`` (or its text), redacted with ``tandem_data.privacy``; results are never read.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shlex

from tandem_data.privacy import redact, sanitize

# Raw tool_call.status values behind the UI's ok/failed (see analytics/respond/rules.py).
STATUS = {"ok": ("success", "completed"), "failed": ("failed",)}
EXACT = ("kind", "command_head", "mcp_server", "skill", "error_class", "session_uid")
SUMMARY_KEYS = ("command", "cmd", "file_path", "path", "pattern", "url", "query", "prompt")
MAX_SUMMARY = 200

SQL = """
SELECT tc.call_uid, tc.session_uid, tc.call_event_uid, tc.result_event_uid, tc.name, tc.kind,
       tc.command_head, tc.mcp_server, tc.mcp_tool, tc.skill, tc.status, tc.exit_code,
       tc.error_class, tc.duration_ms, tc.duration_quality, tc.started_at, tc.approval,
       tc.approval_wait_ms, tc.is_wrapper, tc.subagent_session_uid, tc.files,
       COALESCE(tc.project_id, s.project_id) AS project_id, src.agent, s.title, s.cwd,
       e.attrs AS call_attrs, e.text AS call_text, COALESCE(tc.started_at, 0) AS sort_key
FROM tool_call tc
JOIN session s ON s.session_uid = tc.session_uid
LEFT JOIN source src ON src.source_id = s.source_id
LEFT JOIN event e ON e.event_uid = tc.call_event_uid
WHERE {where}
ORDER BY COALESCE(tc.started_at, 0) DESC, tc.call_uid DESC
LIMIT ?
"""


def encode_cursor(sort_key: int, call_uid: str) -> str:
    return base64.urlsafe_b64encode(f"{sort_key},{call_uid}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        key, call_uid = base64.urlsafe_b64decode(cursor.encode()).decode().split(",", 1)
        return int(key), call_uid
    except (ValueError, binascii.Error, UnicodeError) as error:
        raise ValueError("invalid cursor") from error


def _where(filters: dict, cursor: str | None, excluded: list[str]) -> tuple[str, list]:
    clauses, params = ["1"], []
    if filters.get("name"):
        clauses.append("(tc.name = ? OR tc.name_raw = ?)")
        params += [filters["name"]] * 2
    for key in EXACT:
        if filters.get(key):
            clauses.append(f"tc.{key} = ?")
            params.append(filters[key])
    status = filters.get("status") or "all"
    if status != "all":
        if status not in STATUS:
            raise ValueError("status must be ok, failed or all")
        clauses.append(f"tc.status IN ({','.join('?' * len(STATUS[status]))})")
        params += STATUS[status]
    if filters.get("project_id"):
        clauses.append("COALESCE(tc.project_id, s.project_id) IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(list(filters["project_id"])))
    if filters.get("agent"):
        clauses.append("src.agent IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(list(filters["agent"])))
    if filters.get("from_ts") is not None:
        clauses.append("tc.started_at >= ?")
        params.append(filters["from_ts"])
    if filters.get("until_ts") is not None:
        clauses.append("tc.started_at < ?")
        params.append(filters["until_ts"])
    if excluded:
        clauses.append("tc.session_uid NOT IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(list(excluded)))
    if cursor:
        key, call_uid = decode_cursor(cursor)
        clauses.append("(COALESCE(tc.started_at, 0), tc.call_uid) < (?, ?)")
        params += [key, call_uid]
    return " AND ".join(clauses), params


def query(conn, filters: dict, limit: int = 50, cursor: str | None = None,
          excluded: list[str] | None = None) -> dict:
    """Raises ValueError on a bad cursor, status or limit (routes map it to 422)."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    where, params = _where(filters, cursor, excluded or [])
    rows = conn.execute(SQL.format(where=where), [*params, limit + 1]).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [_item(dict(r)) for r in rows]
    last = rows[-1] if has_more else None
    return {"items": items, "has_more": has_more,
            "next_cursor": encode_cursor(last["sort_key"], last["call_uid"]) if last else None}


def _item(row: dict) -> dict:
    cwd = row.pop("cwd")
    attrs, text = row.pop("call_attrs"), row.pop("call_text")
    row.pop("sort_key")
    row["is_wrapper"] = bool(row["is_wrapper"])
    row["files"] = [_shorten(p, cwd) for p in _json(row["files"], [])[:5] if isinstance(p, str)]
    row["args_summary"] = args_summary(_json(attrs, {}), text)
    return row


def _json(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _shorten(path: str, cwd: str | None) -> str:
    if cwd and os.path.isabs(path):
        root = cwd.rstrip("/") + "/"
        if path.startswith(root):
            return path[len(root):]
    return path


def args_summary(attrs: dict, text: str | None = None) -> str | None:
    """One redacted line (<= 200 chars) describing the call's arguments."""
    value = attrs.get("input") if isinstance(attrs, dict) else None
    value = sanitize(value) if value is not None else None
    if isinstance(value, dict):
        picked = next((value[k] for k in SUMMARY_KEYS if value.get(k)), None)
        if isinstance(picked, list) and all(isinstance(a, str) for a in picked):
            line = shlex.join(picked)
        elif isinstance(picked, str):
            line = picked
        else:
            line = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(value, str):
        line = value
    elif value is not None:
        line = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        line = text
    if not line:
        return None
    line = re.sub(r"\s+", " ", redact(line)).strip()
    return line if len(line) <= MAX_SUMMARY else line[:MAX_SUMMARY - 1] + "…"
