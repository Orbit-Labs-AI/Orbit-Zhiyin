"""Bounded reads of recent session activity from tandem.db (read only)."""

from __future__ import annotations

from .model import SessionTail, TailCall, TailEvent

MAX_SESSIONS = 200
CALLS_PER_SESSION = 50

# event has no plain ts index; event_by_kind_time(kind, ts) is used through a loose index
# scan over the few distinct kinds, so the horizon filter is an index range, not a scan.
ACTIVE_SQL = """
WITH RECURSIVE kinds(kind) AS (
  SELECT MIN(kind) FROM event
  UNION ALL
  SELECT (SELECT MIN(e.kind) FROM event e WHERE e.kind > kinds.kind) FROM kinds
  WHERE kinds.kind IS NOT NULL
), recent AS MATERIALIZED (
  SELECT session_uid, ts FROM event
  WHERE kind IN (SELECT kind FROM kinds WHERE kind IS NOT NULL) AND ts >= ?
), active AS (
  SELECT session_uid, MAX(ts) AS last_ts FROM recent GROUP BY session_uid
)
SELECT a.session_uid, a.last_ts, s.native_id, s.project_id, p.name AS project, s.title, s.status,
       s.started_at, s.ended_at, src.agent
FROM active a JOIN session s ON s.session_uid = a.session_uid
LEFT JOIN source src ON src.source_id = s.source_id
LEFT JOIN project p ON p.project_id = s.project_id
ORDER BY a.last_ts DESC LIMIT ?
"""
EVENTS_SQL = """
SELECT ts, kind, actor, call_id,
       CASE WHEN kind = 'permission.request' THEN COALESCE(
         json_extract(attrs, '$.command'), json_extract(attrs, '$.tool_input.command'),
         json_extract(attrs, '$.input.command'), substr(text, 1, 400)) END AS command
FROM event WHERE session_uid = ? ORDER BY seq DESC LIMIT ?
"""
CALLS_SQL = """
SELECT call_uid, name, command_head, argument_digest, status, error_class, exit_code,
       started_at, ended_at
FROM tool_call WHERE session_uid = ? ORDER BY started_at DESC LIMIT ?
"""
# Codex turn.start payloads carry the effective model_context_window (kept in event.ext).
WINDOW_SQL = """
SELECT CAST(json_extract(ext, '$.model_context_window') AS INTEGER) AS window
FROM event WHERE session_uid = ? AND kind = 'turn.start'
  AND json_extract(ext, '$.model_context_window') IS NOT NULL
ORDER BY seq DESC LIMIT 1
"""
# Older than this, no rule can make a session live (approval waits expire after an hour, the
# finished state after minutes), so only the cheap session row is read for it.
DETAIL_HORIZON_S = 3_600
USAGE_SQL = """
SELECT input_tokens, cache_read_tokens, cache_write_tokens, COALESCE(model_id, model_raw) AS model
FROM model_call WHERE session_uid = ? ORDER BY ts DESC LIMIT 1
"""


def context_tokens(usage) -> int | None:
    """Prompt size of the last model call = fresh input + cache read + cache write.

    The canonical ``model_call.input_tokens`` is *fresh* input for every agent: Anthropic's
    usage reports ``input_tokens`` without ``cache_read_input_tokens`` and
    ``cache_creation_input_tokens``, and the connector turns Codex's total ``input_tokens``
    into fresh by subtracting ``cached_input_tokens`` and ``cache_write_input_tokens``
    (connectors/src/normalize.ts usageAttrs). The whole prompt is therefore the sum of the
    three. Unknown fresh input stays unknown; a missing cache bucket counts as 0.
    """
    if usage["input_tokens"] is None:
        return None
    return usage["input_tokens"] + (usage["cache_read_tokens"] or 0) + (usage["cache_write_tokens"] or 0)


def active_sessions(db, since_ms: int, limit: int = MAX_SESSIONS):
    return db.execute(ACTIVE_SQL, (since_ms, limit)).fetchall()


def load_tails(reads, now_ms: int, horizon_s: int = 86_400,
               per_session_events: int = 200,
               detail_horizon_s: int = DETAIL_HORIZON_S) -> list[SessionTail]:
    """Sessions with an event in the horizon; those active within ``detail_horizon_s`` also
    carry their newest events, calls and usage (older ones can only classify as idle)."""
    with reads.read(check=False) as db:
        tails = []
        detail_from = now_ms - detail_horizon_s * 1000
        for row in active_sessions(db, now_ms - horizon_s * 1000):
            uid = row["session_uid"]
            if row["last_ts"] is not None and row["last_ts"] < detail_from:
                tails.append(SessionTail(
                    session_uid=uid, agent=row["agent"], native_id=row["native_id"],
                    project_id=row["project_id"], project=row["project"], title=row["title"],
                    status=row["status"], started_at=row["started_at"],
                    ended_at=row["ended_at"], last_event_ts=row["last_ts"]))
                continue
            events = db.execute(EVENTS_SQL, (uid, per_session_events)).fetchall()
            calls = db.execute(CALLS_SQL, (uid, CALLS_PER_SESSION)).fetchall()
            usage = db.execute(USAGE_SQL, (uid,)).fetchone()
            window = db.execute(WINDOW_SQL, (uid,)).fetchone()
            newest = events[0] if events else None
            pending = None
            if newest is not None and newest["kind"] == "permission.request":
                pending = {"ts": newest["ts"], "command": newest["command"]}
            tails.append(SessionTail(
                session_uid=uid, agent=row["agent"], native_id=row["native_id"], project_id=row["project_id"],
                project=row["project"], title=row["title"], status=row["status"],
                started_at=row["started_at"], ended_at=row["ended_at"],
                last_event_ts=row["last_ts"], last_actor=newest and newest["actor"],
                events=[TailEvent(e["ts"], e["kind"], e["actor"], e["call_id"])
                        for e in reversed(events)],
                calls=[TailCall(**dict(c)) for c in reversed(calls)],
                pending_permission=pending,
                usage=None if usage is None else {
                    "used_tokens": context_tokens(usage),
                    "model": usage["model"],
                    "window_tokens": window["window"] if window and window["window"] and
                    window["window"] > 0 else None}))
        return tails
