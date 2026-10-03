"""Shared helpers for the A4–A6 presentation adapters (``/v1/uiview/*``).

The adapters read tandem.db (``gw.reads.read()``) and return page-shaped JSON: counts and
rates with their denominators, never a guessed value. Unknown stays unknown: a status the
log did not report is ``unknown`` and never counted as success.

``register_all`` imports each ``a4a6_*`` adapter that exists and lets it add its routes,
so a later package only drops a module next to this one.
"""

from __future__ import annotations

import importlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, is_dataclass
from typing import Annotated

from fastapi import Query

from ..analytics.common import quantile as _quantile
from ..recommend.outcomes import newcombe as _newcombe
from ..recommend.outcomes import wilson as _wilson
from ..services.snapshots import scope_hash as _scope_hash

CONTRACT = "tandem-uiview-a4a6-v1"
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
ADAPTERS = ("a4a6_tools", "a4a6_projects", "a4a6_sentiment")

# Repeated query parameter (``?agent=a&agent=b``). Kept at module level and imported by
# name: the adapters use ``from __future__ import annotations``, so FastAPI resolves route
# annotations against module globals and a function-local alias stays ForwardRef('many'),
# which makes ``/v1/openapi.json`` fail with a 500.
ManyQuery = Annotated[list[str] | None, Query()]


# -- event seq ---------------------------------------------------------------------------

# ``event`` rows are wide (text + attrs JSON), so ``LEFT JOIN event e ON e.event_uid = …``
# just to read ``e.seq`` fetches one table page per tool call: 145k calls on a 7 GB store
# took 10 s warm / 40 s cold. Both lookups below are covering-index reads instead: the
# primary-key index maps event_uid → rowid, UNIQUE(session_uid, seq) maps rowid → seq.
CALL_EVENT_ROWID_SQL = "(SELECT rowid FROM event WHERE event_uid = {col})"


def attach_event_seq(conn, rows: list[dict], *, rowid_key: str = "call_event_rowid",
                     session_key: str = "session_uid") -> list[dict]:
    """Replace ``row[rowid_key]`` (from ``CALL_EVENT_ROWID_SQL``) with ``row["seq"]``.

    Call inside the read transaction that produced ``rows`` so rowids are stable. A call
    whose event sits in another session falls back to a direct rowid read, never to None.
    """
    wanted = {r[rowid_key] for r in rows if r.get(rowid_key) is not None}
    sessions = sorted({r[session_key] for r in rows if r.get(rowid_key) is not None})
    seq_of: dict[int, int] = {}
    if sessions:
        seq_of = {rid: seq for rid, seq in conn.execute(
            "SELECT rowid, seq FROM event WHERE session_uid IN (SELECT value FROM json_each(?))",
            (json.dumps(sessions),)) if rid in wanted}
    missing = sorted(wanted - seq_of.keys())
    if missing:
        seq_of.update((rid, seq) for rid, seq in conn.execute(
            "SELECT rowid, seq FROM event WHERE rowid IN (SELECT value FROM json_each(?))",
            (json.dumps(missing),)))
    for r in rows:
        rid = r.pop(rowid_key, None)
        r["seq"] = None if rid is None else seq_of.get(rid)
    return rows


# -- scope -------------------------------------------------------------------------------

def scope_dict(scope) -> dict:
    if scope is None:
        return {}
    return asdict(scope) if is_dataclass(scope) else dict(scope)


def _in(column: str, values) -> tuple[str, list]:
    return f"{column} IN (SELECT value FROM json_each(?))", [json.dumps(list(values))]


def scope_where(scope, alias: str = "s", *, agents=None, time_col: str | None = None,
                from_ts: int | None = None, until_ts: int | None = None,
                use_scope_time: bool = False) -> tuple[str, list]:
    """Session filter for ``analytics.inputs.Scope`` (a dataclass or its dict).

    An explicit empty list matches nothing. Agents filter on ``source.agent`` (scope
    ``agent_ids`` plus ``agents``). ``excluded_session_uids`` drops the session and, for a
    root, its children. Time applies to ``time_col`` only when given.
    """
    s = scope_dict(scope)
    clauses: list[str] = []
    params: list = []

    def add(sql_params):
        clauses.append(sql_params[0])
        params.extend(sql_params[1])

    if s.get("project_ids") is not None:
        add(_in(f"{alias}.project_id", s["project_ids"]))
    if s.get("source_ids") is not None:
        add(_in(f"{alias}.source_id", s["source_ids"]))
    wanted = [*(s.get("agent_ids") or []), *(agents or [])]
    if wanted:
        sql, p = _in("agent", wanted)
        add((f"{alias}.source_id IN (SELECT source_id FROM source WHERE {sql})", p))
    roots = s.get("root_session_uids")
    if roots is not None:
        column = "root_uid" if s.get("include_children", True) else "session_uid"
        add(_in(f"{alias}.{column}", roots))
    excluded = s.get("excluded_session_uids") or []
    if excluded:
        sql, p = _in(f"{alias}.session_uid", excluded)
        add((f"NOT {sql}", p))
        sql, p = _in(f"{alias}.root_uid", excluded)
        add((f"NOT {sql}", p))
    if time_col:
        lo = s.get("from_ts") if use_scope_time else from_ts
        hi = s.get("until_ts") if use_scope_time else until_ts
        if lo is not None:
            clauses.append(f"{time_col} >= ?")
            params.append(lo)
        if hi is not None:
            clauses.append(f"{time_col} < ?")
            params.append(hi)
    return (" AND ".join(clauses) or "1"), params


# -- statistics --------------------------------------------------------------------------

def wilson(k: int, n: int) -> tuple[float | None, float | None]:
    """95% Wilson interval; (None, None) without a denominator."""
    if n <= 0:
        return None, None
    return _wilson(k, n)


def newcombe(k_after: int, n_after: int, k_before: int, n_before: int):
    if n_after <= 0 or n_before <= 0:
        return None
    return _newcombe(k_after, n_after, k_before, n_before)


def quantile(values, q):
    """Linear interpolation, same as analytics.common.quantile (p50/p90/p95 alike)."""
    return _quantile([v for v in values if v is not None], q)


def rate(k: int, n: int) -> float | None:
    return k / n if n else None


def delta(value, prev):
    return None if value is None or prev is None else value - prev


# -- time windows ------------------------------------------------------------------------

def week_buckets(until_ms: int, n: int = 12) -> list[tuple[int, int]]:
    """``n`` consecutive 7-day windows ending at ``until_ms``, oldest first."""
    return [(until_ms - (n - i) * WEEK_MS, until_ms - (n - i - 1) * WEEK_MS) for i in range(n)]


def prev_window(from_ms: int | None, until_ms: int | None) -> tuple[int, int] | None:
    """The window of equal length right before ``[from_ms, until_ms)``."""
    if from_ms is None or until_ms is None or until_ms <= from_ms:
        return None
    return from_ms - (until_ms - from_ms), from_ms


# -- cache -------------------------------------------------------------------------------

class LRU:
    """Small thread-safe LRU; keys carry data_rev/inventory_rev so stale entries never hit."""

    def __init__(self, maxsize: int = 32):
        self.maxsize = maxsize
        self.items: OrderedDict = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key not in self.items:
                return None
            self.items.move_to_end(key)
            return self.items[key]

    def put(self, key, value) -> None:
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.maxsize:
                self.items.popitem(last=False)


CACHE = LRU(32)


def params_hash(params: dict) -> str:
    return _scope_hash({}, params)


def cache_key(name: str, scope, params: dict, rev: dict) -> tuple:
    return (name, scope_hash(scope), rev.get("data_rev"), rev.get("inventory_rev"),
            params_hash(params))


def scope_hash(scope, params: dict | None = None) -> str:
    return _scope_hash(scope_dict(scope), params or {})


# -- meta --------------------------------------------------------------------------------

def ui_meta(scope, rev: dict, coverage: dict, *, params: dict | None = None, **extra) -> dict:
    return {"contract": CONTRACT, "scope_hash": scope_hash(scope, params),
            "data_rev": rev.get("data_rev"), "inventory_rev": rev.get("inventory_rev"),
            "generated_at": int(time.time() * 1000), "coverage": coverage, **extra}


# -- shared filters (same names as /v1/uiview/overview) ---------------------------------

FACETS = ("topic", "outcome", "fric", "hour")


def agent_list(agent: list[str] | None, agents: str | None) -> list[str] | None:
    """``agents=a,b`` (overview style) merged with the older repeated ``agent=`` alias."""
    out = [*(agent or []), *(a.strip() for a in (agents or "").split(","))]
    out = sorted({a for a in out if a})
    return out or None


def facet_sessions(gw, facets: dict, tz: str | None = None, wait_ms: int = 0):
    """Main-session ids whose ``uiview_facts`` row matches topic / outcome / fric / hour.

    Returns ``(None, None)`` without a facet, ``(ids, None)`` when matched, and
    ``(None, response)`` with a 202 while the fact rows are still computing.
    """
    from fastapi.responses import JSONResponse

    from . import derive, fetch

    f = {k: facets.get(k) for k in FACETS if facets.get(k) not in (None, "")}
    if not f:
        return None, None
    from ..services import fastpath

    # Same window the overview serves (first-open fast path), not a separate all-time run.
    scope, _ = fastpath.choose(gw, fetch.SECTION, fetch.default_scope(tz), None)
    body, freshness, job_id = fetch.fetch(gw, scope, wait_ms=wait_ms)
    if body is None:
        if freshness == "none":
            return [], None
        return None, JSONResponse({"meta": {"contract": CONTRACT, "freshness": "computing",
                                            "job_id": job_id}}, status_code=202)
    return sorted(r["id"] for r in body.get("rows") or []
                  if not r.get("excluded") and derive.passes(r, f)), None


# -- routes ------------------------------------------------------------------------------

def register_all(api, gw) -> list[str]:
    """Let every present adapter module add its routes; a missing module is skipped."""
    loaded = []
    for name in ADAPTERS:
        full = f"{__package__}.{name}"
        try:
            module = importlib.import_module(full)
        except ModuleNotFoundError as error:
            if error.name == full:
                continue
            raise
        module.register(api, gw)
        loaded.append(name)
    return loaded
