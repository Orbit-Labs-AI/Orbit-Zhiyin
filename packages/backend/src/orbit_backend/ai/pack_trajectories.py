"""Bounded, scoped procedural evidence; never load native records or reasoning."""

from __future__ import annotations

import json

from orbit_data import payload

MAX_SESSIONS = 8
MAX_EVENTS = 160
SESSION_CHARS = 48000
VISIBLE = ("message.user", "message.assistant", "tool.call", "tool.result")


def _bounded(value, limit):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return value, False
    half = (limit - 40) // 2
    return text[:half] + "\n[... clipped evidence ...]\n" + text[-half:], True


def load(c):
    if c.conn is None:
        return {"sessions": [], "unavailable": True}
    where, args = c.where()
    # Explicit scope remains the authority: caller-supplied slots cannot replace this item.
    rows = c.conn.execute(
        f"SELECT s.session_uid FROM session s WHERE {where} ORDER BY s.started_at, s.session_uid",
        args).fetchall()
    sessions = []
    for selected in rows[:MAX_SESSIONS]:
        uid = selected[0]
        events = c.conn.execute(
            "SELECT * FROM event WHERE session_uid=? AND kind IN (?,?,?,?) ORDER BY seq",
            (uid, *VISIBLE)).fetchall()
        chosen = events if len(events) <= MAX_EVENTS else events[:MAX_EVENTS // 2] + events[-MAX_EVENTS // 2:]
        fragments, cache = [], {}
        for row in chosen:
            restored = payload.restore_row(c.conn, row, cache)
            attrs = json.loads(row["attrs"] or "{}")
            fragment = {"session_uid": uid, "event_uid": row["event_uid"], "seq": row["seq"],
                        "kind": row["kind"], "call_id": row["call_id"]}
            if row["kind"] == "tool.call":
                fragment["tool"] = attrs.get("name") or attrs.get("tool_name")
                fragment["input"], fragment["clipped"] = _bounded(attrs.get("input", {}), 12000)
            else:
                limit = 6000 if row["kind"] == "message.user" else 4000
                fragment["text"], fragment["clipped"] = _bounded(restored.get("text") or "", limit)
                if row["kind"] == "tool.result":
                    fragment["status"] = attrs.get("status", "unknown")
                    fragment["is_error"] = attrs.get("is_error")
            fragments.append(fragment)
        # Reserve the end of each trajectory for verification/corrections. Report all loss.
        retained, used = [], 0
        for fragment in fragments:
            size = len(json.dumps(fragment, ensure_ascii=False))
            if used + size > SESSION_CHARS // 2:
                break
            retained.append(fragment)
            used += size
        first_ids = {e["event_uid"] for e in retained}
        tail, used_tail = [], 0
        for fragment in reversed(fragments):
            if fragment["event_uid"] in first_ids:
                break
            size = len(json.dumps(fragment, ensure_ascii=False))
            if used + used_tail + size > SESSION_CHARS:
                break
            tail.append(fragment)
            used_tail += size
        retained.extend(reversed(tail))
        sessions.append({"session_uid": uid, "events": retained, "visible_events": len(events),
                         "retained_events": len(retained), "omitted_events": len(events) - len(retained),
                         "clipped_events": sum(e["clipped"] for e in retained),
                         "task_outcome": "unknown_without_external_validation"})
    return {"sessions": sessions, "eligible_sessions": len(rows),
            "omitted_sessions": max(0, len(rows) - MAX_SESSIONS),
            "selection": "oldest first within explicit scope; bounded head and tail per session",
            "limits": {"sessions": MAX_SESSIONS, "events_per_session": MAX_EVENTS,
                       "chars_per_session": SESSION_CHARS}}
