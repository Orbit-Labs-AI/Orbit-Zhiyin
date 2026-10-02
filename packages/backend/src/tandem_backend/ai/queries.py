"""Whitelisted read-only queries (AI-09): the only data an ask/plan may request.

Every api takes a small, schema-checked param set and returns ≤20 redacted rows,
the ids they mention (`refs`) and every number in them (`numbers`, the
whitelist answers are checked against).
"""

from __future__ import annotations

import jsonschema

from tandem_backend import privacy

from . import pack as P
from .redact import redact_value

METRICS = ["sessions", "hours", "human_messages", "corrections", "correction_rate", "tool_calls",
           "tool_failures", "tool_failure_rate"]
_FIELDS = {
    "scope": {"type": "object", "additionalProperties": False,
              "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365},
                             "start_ms": {"type": "integer", "minimum": 0},
                             "end_ms": {"type": "integer", "minimum": 0},
                             "project_id": {"type": "string", "minLength": 1, "maxLength": 128},
                             "source_ids": {"type": "array", "maxItems": 50,
                                            "items": {"type": "string", "minLength": 1,
                                                      "maxLength": 128}}}},
    "session_uid": {"type": "string", "minLength": 1, "maxLength": 128},
    "q": {"type": "string", "minLength": 1, "maxLength": 80},
    "metric": {"type": "string", "enum": METRICS},
    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
}
_ALLOWED = {
    "metrics": ["scope", "metric"],
    "sessions": ["scope", "session_uid", "q", "limit"],
    "problems": ["scope", "limit"],
    "candidates": ["scope", "limit"],
    "evidence": ["session_uid", "q", "limit"],
    "search": ["q", "limit"],
    "projects": ["scope", "limit"],
    "tools": ["scope", "limit"],
    "inventory": ["limit"],
    "catalog": ["q", "limit"],
}
_REQUIRED = {"search": ["q"], "catalog": ["q"]}
SCHEMAS = {api: {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                 "additionalProperties": False, "required": _REQUIRED.get(api, []),
                 "properties": {f: _FIELDS[f] for f in fields}} for api, fields in _ALLOWED.items()}
APIS = tuple(SCHEMAS)
_VALIDATORS = {api: jsonschema.Draft202012Validator(s) for api, s in SCHEMAS.items()}


def check(api: str, params: dict | None) -> dict:
    """Validate a planned query; raises ValueError when it leaves the whitelist."""
    if api not in _VALIDATORS:
        raise ValueError(f"unknown api: {api}")
    params = params or {}
    errors = sorted(e.message for e in _VALIDATORS[api].iter_errors(params))
    if errors:
        raise ValueError(f"{api}: " + "; ".join(errors))
    return params


def run(api: str, params: dict | None, *, reads, appdb=None, home=None) -> dict:
    params = check(api, params)
    limit = params.get("limit", 10)
    scope = params.get("scope") or {}
    if api == "candidates":
        rows = P.candidates(scope, limit, appdb)
    elif api == "catalog":
        rows = P.catalog_search(params["q"], limit)
    elif api == "problems" and (problems := P.features_profile(scope).get("problems")):
        rows = [{"problem_id": p.get("problem_id") or p.get("id"), "type": p.get("type"), "key": p.get("key"),
                 "sessions": p.get("sessions"), "weekly_count": p.get("weekly_count")}
                for p in problems[:limit] if isinstance(p, dict)]
    else:
        # Persisted exclusions (AN-16.1) apply to every whitelisted SQL query.
        scope = {**scope, "_exclude": _excluded(appdb)}
        with reads() as conn:
            rows = _SQL[api](conn, params, scope, limit, home, appdb)
    rows, _ = redact_value(list(rows)[:20])
    refs: dict = {k: [] for k in ("session", "event", "problem", "candidate", "metric")}
    numbers: set[float] = set()
    P.collect_refs(rows, refs, numbers, numeric=True)
    if api == "metrics":
        refs["metric"] = [r["metric"] for r in rows]
    return {"api": api, "rows": rows,
            "refs": [{"kind": k, "id": i} for k, ids in refs.items() for i in ids],
            "numbers": sorted(numbers)}


def _excluded(appdb) -> list[str]:
    from ..sessionops import exclusion

    if appdb is None:
        return exclusion.merged(None)
    try:
        return exclusion.excluded_uids(appdb)
    except Exception:  # noqa: BLE001 - app.db without the table: nothing excluded.
        return []


def _filters(scope: dict) -> dict:
    return {"source_ids": scope.get("source_ids") or None, "exclude": scope.get("_exclude") or None}


def _metrics(conn, params, scope, limit, home, appdb):
    start, end, pid = P.window(scope)
    cur = P.metrics(conn, start, end, pid, home, **_filters(scope))
    prev = P.metrics(conn, start - (end - start), start, pid, home, **_filters(scope))
    names = [params["metric"]] if params.get("metric") else METRICS
    return [{"metric": m, "value": cur[m], "prev": prev[m] if prev["sessions"] else None} for m in names]


def _sessions(conn, params, scope, limit, home, appdb):
    start, end, pid = P.window(scope)
    where, args = P.window_sql(start, end, pid, home, **_filters(scope))
    if params.get("session_uid"):
        where, args = "s.session_uid=?", [params["session_uid"]]
    if params.get("q"):
        where += " AND s.title LIKE ?"
        args.append(f"%{params['q']}%")
    rows = conn.execute(
        f"SELECT s.session_uid, s.title, p.name, s.started_at,"
        f" MAX(COALESCE(s.ended_at,s.started_at)-s.started_at,0),"
        f" (SELECT COUNT(*) FROM tool_call t WHERE t.session_uid=s.session_uid),"
        f" (SELECT COUNT(*) FROM tool_call t WHERE t.session_uid=s.session_uid AND t.status IN ('failed','error')),"
        f" (SELECT COUNT(*) FROM v_human_message h WHERE h.session_uid=s.session_uid AND {P._correction_sql()})"
        f" FROM session s LEFT JOIN project p ON p.project_id=s.project_id WHERE {where}"
        f" ORDER BY s.started_at DESC LIMIT ?", [*args, limit]).fetchall()
    return [{"session_uid": r[0], "title": r[1] or "", "project": r[2], "started_at": r[3],
             "minutes": round((r[4] or 0) / 60000, 1), "tools": r[5], "errors": r[6], "corrections": r[7]}
            for r in rows]


def _problems(conn, params, scope, limit, home, appdb):
    """Fallback when features is not wired: error classes as problem-like rows."""
    start, end, pid = P.window(scope)
    where, args = P.window_sql(start, end, pid, home, **_filters(scope))
    rows = conn.execute(
        f"SELECT error_class, COUNT(*) n, COUNT(DISTINCT session_uid) FROM tool_call WHERE session_uid IN"
        f" (SELECT s.session_uid FROM session s WHERE {where}) AND error_class IS NOT NULL"
        f" GROUP BY error_class ORDER BY n DESC, error_class LIMIT ?", [*args, limit]).fetchall()
    return [{"type": "tool_failure", "key": r[0], "count": r[1], "sessions": r[2]} for r in rows]


def _evidence(conn, params, scope, limit, home, appdb):
    if params.get("session_uid"):
        rows = conn.execute("SELECT event_uid, session_uid, text FROM v_human_message WHERE session_uid=?"
                            " ORDER BY seq LIMIT ?", (params["session_uid"], limit)).fetchall()
        out = [{"event_uid": r[0], "session_uid": r[1], "kind": "human",
                "text": privacy.direct_user_text(r[2] or "")[:300]} for r in rows]
        if params.get("q"):
            out = [o for o in out if params["q"].lower() in o["text"].lower()]
        return out
    if params.get("q"):
        return _search(conn, params, scope, limit, home, appdb)
    return []


def _search(conn, params, scope, limit, home, appdb):
    return [{**h, "text": h["text"][:300]} for h in P.fts_human(conn, params.get("q") or "", limit)]


def _projects(conn, params, scope, limit, home, appdb):
    start, end, _ = P.window(scope)
    where, args = P.window_sql(start, end, None, home, **_filters(scope))
    rows = conn.execute(
        f"SELECT p.project_id, p.name, COUNT(*) n,"
        f" ROUND(SUM(MAX(COALESCE(s.ended_at,s.started_at)-s.started_at,0))/3600000.0,1),"
        f" (SELECT COUNT(*) FROM tool_call t WHERE t.project_id=p.project_id),"
        f" (SELECT COUNT(*) FROM tool_call t WHERE t.project_id=p.project_id AND t.status IN ('failed','error'))"
        f" FROM session s JOIN project p ON p.project_id=s.project_id WHERE {where}"
        f" GROUP BY p.project_id ORDER BY n DESC LIMIT ?", [*args, limit]).fetchall()
    return [{"project_id": r[0], "name": r[1], "sessions": r[2], "hours": r[3], "tool_calls": r[4],
             "tool_failures": r[5]} for r in rows]


def _tools(conn, params, scope, limit, home, appdb):
    start, end, pid = P.window(scope)
    where, args = P.window_sql(start, end, pid, home, **_filters(scope))
    rows = conn.execute(
        f"SELECT name, COUNT(*) n, SUM(status IN ({P.FAILED_SQL})), SUM(approval IS NOT NULL),"
        f" (SELECT error_class FROM tool_call x WHERE x.name=t.name AND x.error_class IS NOT NULL"
        f"  GROUP BY error_class ORDER BY COUNT(*) DESC LIMIT 1), MAX(mcp_server),"
        f" SUM(status IN ({P.KNOWN_SQL})), SUM(status IN ('declined','denied'))"
        f" FROM tool_call t WHERE session_uid IN (SELECT s.session_uid FROM session s WHERE {where})"
        f" GROUP BY name ORDER BY SUM(status IN ({P.FAILED_SQL})) DESC, n DESC LIMIT ?", [*args, limit]).fetchall()
    # Failure rate over known outcomes only; unknown results must not inflate it to 100%.
    return [{"tool": r[0], "calls": r[1], "failures": int(r[2] or 0), "known": int(r[6] or 0),
             "failure_rate": round((r[2] or 0) / r[6], 3) if r[6] else None,
             "unknown_share": round((r[1] - (r[6] or 0)) / r[1], 3) if r[1] else None,
             "rejected": int(r[7] or 0), "approvals": int(r[3] or 0),
             "top_error_class": r[4], "mcp_server": r[5]} for r in rows]


def _inventory(conn, params, scope, limit, home, appdb):
    start, end, _ = P.window({"days": 30})
    where, args = P.window_sql(start, end, None, home)
    try:
        rows = conn.execute(
            f"SELECT i.type, i.name, i.enabled, (SELECT COUNT(*) FROM tool_call t WHERE"
            f" (t.mcp_server=i.name OR t.skill=i.name) AND t.session_uid IN"
            f" (SELECT s.session_uid FROM session s WHERE {where}))"
            f" FROM inventory_item i WHERE i.scan_id IN ({P.latest_scans_sql()})"
            f" GROUP BY i.type, i.name ORDER BY i.type, i.name LIMIT ?", [*args, limit]).fetchall()
    except Exception:  # noqa: BLE001 - inventory tables may be absent
        return []
    return [{"type": r[0], "name": r[1], "enabled": None if r[2] is None else bool(r[2]), "calls_30d": r[3]}
            for r in rows]


_SQL = {"metrics": _metrics, "sessions": _sessions, "problems": _problems, "evidence": _evidence,
        "search": _search, "projects": _projects, "tools": _tools, "inventory": _inventory}
