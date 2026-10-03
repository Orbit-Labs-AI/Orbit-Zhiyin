"""A3 session detail: header, seven stats, swim-lane trajectory, phases, key moments, ctx.

Reads only one session's L1 rows (``session, source, event, tool_call, model_call``, child
sessions) so switching sessions stays in milliseconds; never touches analytics snapshots.
Text other than the first 120 chars of human messages is left to ``/v1/sessions/{id}/events``.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime, tzinfo

from ..analytics.products.journey import EXPLORE
from ..realtime import context_windows
from ..sessionops import resume
from . import metrics
from . import moments as rules
from .sessions import (
    HUMAN_WHERE,
    agent_name,
    errors_of,
    estimate_outcome,
    is_correction,
    is_failed,
    scrub,
    title_from,
)

LANES = ["user", "agent", "sub", "read", "edit", "bash", "web"]
TOOL_LANE = {"file.read": "read", "search": "read", "file.search": "read",
             "file.edit": "edit", "file.write": "edit",
             "shell": "bash", "web.search": "web", "web.fetch": "web", "mcp": "web",
             "subagent": "sub"}
PHASE_LABEL = {"request": "需求", "explore": "探索", "execute": "实施", "respond": "回复",
               "deliver": "交付", "verify": "验证"}
MIN_PHASE_SHARE = 0.03
MIN_T = 0.1

SESSION_SQL = """
SELECT s.session_uid, s.native_id, s.kind, s.title, s.title_source, s.project_id, s.cwd,
       s.started_at, s.ended_at, s.status, src.agent
FROM session s LEFT JOIN source src ON src.source_id = s.source_id WHERE s.session_uid = ?
"""
EVENTS_SQL = f"""
SELECT e.event_uid, e.seq, e.ts, e.kind, e.actor, e.turn_uid,
       CASE WHEN {HUMAN_WHERE} THEN e.text END AS text,
       CASE WHEN {HUMAN_WHERE} THEN 1 ELSE 0 END AS human,
       CASE WHEN e.kind = 'message.assistant' THEN json_extract(e.attrs, '$.phase') END AS phase
FROM event e WHERE e.session_uid = ? ORDER BY e.seq
"""
CALLS_SQL = """
SELECT call_uid, call_event_uid, name_raw, name, kind, command_head, status, exit_code,
       error_class, started_at, duration_ms, subagent_session_uid
FROM tool_call WHERE session_uid = ?
"""
CHILDREN_SQL = """
SELECT s.session_uid, s.kind, s.started_at, s.ended_at, s.title,
       (SELECT MIN(ts) FROM event WHERE session_uid = s.session_uid),
       (SELECT MAX(ts) FROM event WHERE session_uid = s.session_uid),
       (SELECT event_uid FROM event WHERE session_uid = s.session_uid ORDER BY seq LIMIT 1),
       (SELECT COUNT(*) FROM tool_call WHERE session_uid = s.session_uid)
FROM session s WHERE s.root_uid = ? AND s.session_uid <> ?
"""
MODEL_SQL = """
SELECT COALESCE(model_id, model_raw), effort_raw, input_tokens, cache_read_tokens,
       cache_write_tokens, output_tokens, ts
FROM model_call WHERE session_uid = ? ORDER BY ts, call_uid
"""
TREE_TOKENS_SQL = """
SELECT COUNT(*),
       SUM(CASE WHEN m.input_tokens IS NULL AND m.output_tokens IS NULL THEN 1 ELSE 0 END),
       SUM(COALESCE(m.input_tokens, 0) + COALESCE(m.cache_read_tokens, 0)
           + COALESCE(m.cache_write_tokens, 0) + COALESCE(m.output_tokens, 0))
FROM model_call m JOIN session s ON s.session_uid = m.session_uid WHERE s.root_uid = ?
"""
TREE_CALLS_SQL = """
SELECT t.status FROM tool_call t JOIN session s ON s.session_uid = t.session_uid
WHERE s.root_uid = ? ORDER BY t.started_at, t.call_uid
"""
CONTEXT_SQL = "SELECT model_raw, effort_raw FROM event_context WHERE event_uid = ?"
LAST_TURN_SQL = "SELECT status FROM turn WHERE session_uid = ? ORDER BY idx DESC LIMIT 1"


class NotFound(LookupError):
    pass


def _mins(ts: int | None, t0: int) -> float | None:
    return None if ts is None else round(max(ts - t0, 0) / 60_000, 3)


def _active_ms(stamps: list[int]) -> int | None:
    return metrics.active_ms(stamps)


def _phases(stream: list[tuple[float, str]], T: float) -> list[dict]:
    """Merge adjacent same-phase events into bands covering [0, T] without overlap."""
    bands: list[list] = []
    for t, phase in sorted(stream, key=lambda x: x[0]):
        if bands and bands[-1][1] == phase:
            continue
        bands.append([t, phase])
    if not bands:
        return []
    bands[0][0] = 0.0
    spans = [[b[0], (bands[i + 1][0] if i + 1 < len(bands) else T), b[1]]
             for i, b in enumerate(bands)]
    smooth: list[list] = []
    for span in spans:  # Tiny bands fold into the previous one; coverage is preserved.
        if smooth and (span[1] - span[0] < MIN_PHASE_SHARE * T or smooth[-1][2] == span[2]):
            smooth[-1][1] = span[1]
        else:
            smooth.append(span)
    return [{"t": round(a, 3), "t2": round(b, 3), "phase": p, "label": PHASE_LABEL[p],
             "inferred": True} for a, b, p in smooth]


def _res(exit_code, error_class, status) -> str | None:
    parts = [f"exit {exit_code}"] if exit_code is not None else []
    parts += [error_class] if error_class else []
    if not parts and status:
        parts.append(status)
    return " · ".join(parts) or None


def _ctx(model_rows, agent, overrides, t0, comps_at):
    """Per-request prompt size / model window (estimate); None without a window table hit."""
    points = []
    for model, _, inp, cread, cwrite, _, ts in model_rows:
        window = context_windows.lookup(agent, model, overrides)
        if window is None or inp is None or ts is None:
            continue
        used = inp + (cread or 0) + (cwrite or 0)
        points.append([_mins(ts, t0), round(min(used / window["window_tokens"] * 100, 100), 1)])
    if not points:
        return None, []
    comps = set()
    for i in range(1, len(points)):
        if points[i][1] < points[i - 1][1] - 20:
            comps.add(i)
    for t in comps_at:
        after = next((i for i, p in enumerate(points) if p[0] >= t), None)
        if after:
            comps.add(after)
    return points, sorted(comps)


def lite_nodes(moments: list[dict], phases: list[dict], T: float) -> list[dict]:
    """<= 4 nodes for Lite: goal, up to two alerts, then verification or the final phase."""
    goal = [m for m in moments if m["rule"] == "goal"][:1]
    alerts = [m for m in moments if m["alert"]][:2]
    tail = [m for m in moments if m["rule"] == "validation_command"][-1:]
    nodes = [{"t": m["t"], "label": m["label"], "detail": m["detail"], "alert": m["alert"],
              "event_uid": m["event_uid"], "rule": m["rule"]} for m in goal + alerts + tail]
    if not tail and phases:
        last = phases[-1]
        nodes.append({"t": T, "label": last["label"] + "结束", "detail": "阶段带（推断）",
                      "alert": False, "event_uid": None, "rule": "phase_end"})
    nodes.sort(key=lambda n: n["t"])
    return nodes[:4]


def build_detail(conn: sqlite3.Connection, session_uid: str, *, overrides: dict | None = None,
                 live: bool = False, excluded: bool = False, now_ms: int | None = None,
                 facts: dict | None = None, tz: tzinfo = UTC) -> dict:
    """The full ``GET /v1/uiview/sessions/{id}`` payload (minus the L0 insight)."""
    s = conn.execute(SESSION_SQL, (session_uid,)).fetchone()
    if s is None:
        raise NotFound(session_uid)
    (uid, native_id, _kind, title, title_source, project_id, cwd, started_at, ended_at,
     status, agent) = s
    events = conn.execute(EVENTS_SQL, (uid,)).fetchall()
    calls = conn.execute(CALLS_SQL, (uid,)).fetchall()
    children = conn.execute(CHILDREN_SQL, (uid, uid)).fetchall()
    model_rows = conn.execute(MODEL_SQL, (uid,)).fetchall()
    ev_ts = {e[0]: e[2] for e in events}
    call_start = [c[9] if c[9] is not None else ev_ts.get(c[1]) for c in calls]
    stamps = [e[2] for e in events if e[2] is not None] + [t for t in call_start if t]
    for child in children:
        stamps += [x for x in (child[5], child[6]) if x is not None]
    t0 = min([x for x in (started_at, *stamps) if x is not None], default=0)
    out_events: list[dict] = []
    users: list[dict] = []
    stream: list[tuple[float, str]] = []
    compactions: list[dict] = []
    last_t = 0.0
    span: dict | None = None

    def close_span():
        nonlocal span
        if span is not None:
            span["w"] = round(span.pop("_end") - span["t"], 3)
            out_events.append(span)
            span = None

    for event_uid, seq, ts, kind, _actor, _turn, text, human, phase in events:
        t = _mins(ts, t0)
        t = last_t if t is None else t
        last_t = t
        if human:
            close_span()
            corr = is_correction(text)
            item = {"id": f"u{len(users) + 1}", "lane": "user", "t": t, "w": 0, "err": False,
                    "corr": corr, "cmd": None, "res": None, "txt": scrub(text), "seq": seq,
                    "event_uid": event_uid}
            users.append(item)
            out_events.append(item)
            stream.append((t, "request"))
        elif kind == "message.assistant":
            if span is None:
                span = {"id": f"r{seq}", "lane": "agent", "t": t, "_end": t, "err": False,
                        "corr": False, "cmd": None, "res": None, "txt": None, "seq": seq,
                        "event_uid": event_uid, "n": 0}
            span["_end"], span["n"] = t, span["n"] + 1
            stream.append((t, "deliver" if phase in ("final", "final_answer") else "respond"))
        elif kind == "context.compaction":
            close_span()
            compactions.append({"t": t, "event_uid": event_uid, "seq": seq})
        elif kind in ("tool.call", "tool.result"):
            close_span()
    close_span()
    tool_events = []
    for call, start in zip(calls, call_start, strict=True):
        (call_uid, call_event_uid, name_raw, name, tkind, head, cstatus, exit_code, error_class,
         _s, duration_ms, _sub) = call
        t = _mins(start, t0)
        t = 0.0 if t is None else t
        item = {"id": call_uid, "lane": TOOL_LANE.get(tkind, "bash"), "t": t,
                "w": round(duration_ms / 60_000, 3) if duration_ms else 0,
                "err": is_failed(cstatus), "corr": False, "cmd": scrub(head or name_raw, 80),
                "res": _res(exit_code, error_class, cstatus),
                "txt": None, "seq": None, "event_uid": call_event_uid or call_uid,
                "call_uid": call_uid, "name": name, "tool_kind": tkind, "status": cstatus}
        tool_events.append(item)
    tool_events.sort(key=lambda c: (c["t"], c["id"]))
    seq_of = {e[0]: e[1] for e in events}
    for item in tool_events:
        item["seq"] = seq_of.get(item["event_uid"])
        verify = rules.is_validation(item)
        stream.append((item["t"], "verify" if verify else
                       "explore" if item["tool_kind"] in EXPLORE else "execute"))
    out_events += tool_events
    for child in children:
        cs, ce = child[5] if child[5] is not None else child[2], child[6] or child[3]
        t, t2 = _mins(cs, t0) or 0.0, _mins(ce, t0)
        out_events.append({"id": child[0], "lane": "sub", "t": t,
                           "w": round(max((t2 or t) - t, 0), 3), "err": False, "corr": False,
                           "cmd": scrub(child[4], 80), "res": child[1], "txt": None,
                           "seq": None, "event_uid": child[7], "child_session_uid": child[0],
                           "child_tools": child[8]})
    out_events.sort(key=lambda e: (e["t"], e["seq"] if e["seq"] is not None else 1 << 62))
    T = max([e["t"] + (e["w"] or 0) for e in out_events] + [c["t"] for c in compactions]
            + [_mins(ended_at, t0) or 0.0, MIN_T])
    T = round(T, 3)
    phases = _phases(stream, T)
    found = rules.detect(users, tool_events, compactions)
    ctx, comps = _ctx(model_rows, agent, overrides, t0, [c["t"] for c in compactions])
    models = Counter(r[0] for r in model_rows if r[0])
    efforts = Counter(r[1] for r in model_rows if r[1])
    if not models and events:
        row = conn.execute(CONTEXT_SQL, (events[-1][0],)).fetchone()
        if row:
            models.update([row[0]] if row[0] else [])
            efforts.update([row[1]] if row[1] else [])
    tree_statuses = [r[0] for r in conn.execute(TREE_CALLS_SQL, (uid,))]
    n_tok = conn.execute(TREE_TOKENS_SQL, (uid,)).fetchone()
    tok = None if not n_tok[0] or n_tok[0] == n_tok[1] else n_tok[2]
    last_turn = conn.execute(LAST_TURN_SQL, (uid,)).fetchone()
    active = _active_ms(stamps)
    msgs = len(users)
    corr = sum(u["corr"] for u in users) if users else None
    replies = sum(1 for e in out_events if e["lane"] == "agent")
    facts = facts or {}
    header_title = title if (title or "").strip() else title_from(users[0]["txt"]) if users else None
    resume_row = {"session_uid": uid, "agent": agent, "native_id": native_id, "cwd": cwd,
                  "status": status, "ended_at": ended_at,
                  "last_event_ts": max(stamps) if stamps else None}
    cmd = resume.build(resume_row, now_ms if now_ms is not None else int(time.time() * 1000))
    first = (cmd["commands"] or [{}])[0]
    out = estimate_outcome(live, status, last_turn[0] if last_turn else None, tree_statuses,
                           corr, msgs)
    header = {
        "id": uid, "a": agent, "agent_name": agent_name(agent),
        "model": models.most_common(1)[0][0] if models else None,
        "effort": efforts.most_common(1)[0][0] if efforts else None,
        "cwd": scrub(cwd, 300), "project_id": project_id,
        "title": facts.get("title") or header_title,
        "title_source": facts.get("title_source") or (
            (title_source or "native") if (title or "").strip() else
            "first_message" if header_title else None),
        "started_at": started_at if started_at is not None else (t0 or None),
        "dur": facts.get("dur", round(active / 60_000, 1) if active is not None else None),
        "dur_basis": "active_estimate",
        # Liveness beats the facts snapshot (taken before or after the session ran).
        "out": "live" if live else (out if facts.get("out", out) == "live"
                                    else facts.get("out", out)),
        "out_basis": "realtime" if live else "estimate",
        "corr": facts.get("corr", corr), "corr_basis": "lexical_candidate",
        "live": live, "excluded": excluded,
        "resume": {"shell": first.get("shell"), "verified": first.get("verified", False),
                   "available": cmd["available"], "disabled_reason": cmd["disabled_reason"]},
    }
    peak = max((p[1] for p in ctx), default=None) if ctx else None
    stats7 = {"msgs": msgs, "steps": len(tool_events) + replies,
              "steps_basis": "tool_calls_plus_reply_spans", "tools": len(tree_statuses),
              # Same corr as the header (facts when present): one number per page.
              "errors": errors_of(tree_statuses), "corr": header["corr"], "ctx_peak": peak,
              "ctx_basis": "estimate" if ctx else None, "tok": tok,
              "tok_basis": "l1_model_call" if tok is not None else None}
    trajectory = {
        "T": T, "unit": "min", "start_min": None, "t0": t0, "lanes": LANES,
        "events": out_events, "phases": phases,
        "moments": [{k: m[k] for k in ("t", "n", "label", "detail", "alert", "event_uid",
                                       "rule")} for m in found],
        "marks": [{"t": c["t"], "kind": "compaction", "event_uid": c["event_uid"]}
                  for c in compactions],
        "ctx": ctx, "comps": comps,
        "steps_axis": [e["seq"] for e in out_events],
    }
    if header["started_at"] is not None:
        at = datetime.fromtimestamp(header["started_at"] / 1000, tz)
        trajectory["start_min"] = at.hour * 60 + at.minute
    return {"header": header, "stats7": stats7, "trajectory": trajectory,
            "lite_nodes": lite_nodes(found, phases, T),
            "_facts": {"steps": stats7["steps"], "msgs": msgs, "tools": stats7["tools"],
                       "errors": stats7["errors"], "corr": corr, "dur": header["dur"],
                       "out": header["out"], "live": live, "verify": any(
                           m["rule"] == "validation_command" for m in found),
                       "streak": any(m["rule"] == "failure_streak" for m in found)}}
