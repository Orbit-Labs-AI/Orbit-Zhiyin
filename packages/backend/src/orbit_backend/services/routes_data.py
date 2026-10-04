"""Direct reads: status, health, sessions, events, projects, sources, inventory.

``/v1/status`` and ``/health`` answer from memory (no database round trip). Table reads
use one ``mode=ro`` connection per thread. When the projection is pending (an import
captured files but has not published them yet) the published snapshot is still one
committed, consistent state: it is served with ``X-Orbit-Freshness: stale`` and
``X-Orbit-Projection: pending`` instead of failing (docs/development/import-pipeline.md,
RC-4). Only while nothing is published yet (the first import) a previous response for
the same request is returned stale, and without one the answer is 503 + Retry-After.

Before the first import there is no orbit.db at all. That is an empty state, not a
transient one: routes that read with ``ReadPool.read(empty=True)`` run against an empty
in-memory copy of the canonical schema, so lists and summaries answer 200 with their
usual shape (``X-Orbit-Freshness: none``; dict bodies also get ``meta.freshness =
"none"`` and ``meta.reason = "no_projection"``) and a lookup by id answers 404.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .. import __version__, privacy_rules
from .auth import ApiError
from .text_cap import EVIDENCE_MAX_CHARS, LIST_MAX_CHARS, RANGE_MAX_CHARS, cap_event

if TYPE_CHECKING:
    from .gateway import Gateway

SESSION_FIELDS = ("id", "title", "project_id", "project", "model", "started_at", "kind", "agent")
NO_DATABASE = {"freshness": "none", "reason": "no_projection"}


def disambiguate_names(items: list[dict]) -> list[dict]:
    """Suffix names used by several projects with the parent folder (or Git owner).
    ``key``/``key_type`` are dropped: paths stay in the local ledger."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item["name"]] = counts.get(item["name"], 0) + 1
    for item in items:
        key, key_type = item.pop("key"), item.pop("key_type")
        if counts[item["name"]] > 1 and key_type != "bucket":
            parts = [p for p in key.replace("\\", "/").split("/") if p]
            if len(parts) >= 2:
                item["name"] = f"{item['name']} ({parts[-2]})"
    return items


class NoDatabase(ApiError):
    """orbit.db does not exist yet (nothing imported). Routes that do not read with
    ``empty=True`` keep answering 503 ``no_projection``."""

    def __init__(self):
        super().__init__(503, "no_projection", "No canonical database yet; import a source",
                         retryable=True, retry_after=2)


def mark_empty(body):
    """Tag a body read from the empty schema; lists keep their shape (header only)."""
    if isinstance(body, dict):
        body["meta"] = {**(body.get("meta") or {}), **NO_DATABASE}
    return body


class ReadPool:
    """Per-thread query-only connections; WAL lets them read while the worker writes."""

    def __init__(self, path: Path):
        self.path = path
        self.local = threading.local()
        self.lock = threading.Lock()
        self.connections: list[sqlite3.Connection] = []

    def _placeholder(self) -> sqlite3.Connection:
        """Empty canonical schema in memory: the same tables and views, no rows."""
        connection = getattr(self.local, "empty", None)
        if connection is None:
            from orbit_data.schema_export import create_schema

            connection = sqlite3.connect(":memory:", check_same_thread=False,
                                         isolation_level=None)
            connection.row_factory = sqlite3.Row
            create_schema(connection)
            connection.execute("PRAGMA query_only = ON")
            self.local.empty = connection
            with self.lock:
                self.connections.append(connection)
        return connection

    def is_empty(self, connection) -> bool:
        """True when ``connection`` is the stand-in yielded before the first import."""
        return connection is not None and connection is getattr(self.local, "empty", None)

    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self.local, "connection", None)
        if connection is None:
            if not self.path.is_file():
                raise NoDatabase()
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True,
                                         check_same_thread=False, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            self.local.connection = connection
            with self.lock:
                self.connections.append(connection)
        return connection

    @contextmanager
    def read(self, check: bool = True, empty: bool = False):
        """``empty=True``: with no orbit.db yet, yield the empty schema (``is_empty``)
        instead of raising 503. While newer captures are still being published, the
        published snapshot is read as usual and ``pending()`` is True for this thread's
        read (callers mark the answer stale); only "nothing published yet" answers 503
        ``projection_pending`` and an obsolete projection 409 ``rebuild_required``."""
        from orbit_data.query import published_projection

        try:
            connection = self._connection()
        except NoDatabase:
            if not empty:
                raise
            connection = self._placeholder()
        self.local.pending = False
        try:
            connection.execute("BEGIN")
            if check and not self.is_empty(connection):
                self.local.pending = published_projection(connection)[2]["pending"]
            yield connection
        except ValueError as error:
            if "Projection is pending" in str(error):
                raise ApiError(503, "projection_pending", "The first import has not published yet",
                               retryable=True, retry_after=1) from error
            raise ApiError(409, "rebuild_required", str(error), retryable=True) from error
        except sqlite3.OperationalError as error:
            raise ApiError(503, "service_unavailable", f"Database busy: {error}",
                           retryable=True, retry_after=1) from error
        finally:
            if connection.in_transaction:
                connection.rollback()

    def pending(self) -> bool:
        """Whether this thread's last checked read served a snapshot behind newer captures."""
        return bool(getattr(self.local, "pending", False))

    def close(self) -> None:
        with self.lock:
            for connection in self.connections:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
            self.connections.clear()


class LastGood:
    """Last successful body per request, used only while the projection is pending."""

    def __init__(self, entries: int = 256):
        self.entries = entries
        self.items: OrderedDict[str, object] = OrderedDict()
        self.lock = threading.Lock()

    def remember(self, key: str, body) -> None:
        with self.lock:
            self.items[key] = body
            self.items.move_to_end(key)
            while len(self.items) > self.entries:
                self.items.popitem(last=False)

    def get(self, key: str):
        with self.lock:
            return self.items.get(key)


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    last_good = LastGood()

    def served(request: Request, build, *, check: bool = True):
        """``build(db)`` inside one read. No orbit.db yet → the empty schema, tagged with
        ``X-Orbit-Freshness: none`` and never remembered, so the first import's
        ``projection_pending`` stays a retryable 503 instead of a stale empty list."""
        key = request.url.path + "?" + request.url.query
        try:
            with gw.reads.read(check=check, empty=True) as db:
                empty = gw.reads.is_empty(db)
                body = jsonable_encoder(build(db))
                pending = gw.reads.pending()
        except ApiError as error:
            cached = last_good.get(key) if error.code == "projection_pending" else None
            if cached is None:
                raise
            return JSONResponse(cached, headers={"X-Orbit-Freshness": "stale"})
        if empty:
            return JSONResponse(mark_empty(body), headers={"X-Orbit-Freshness": "none"})
        last_good.remember(key, body)
        if pending:  # The published snapshot; newer captures are still being published.
            return JSONResponse(body, headers={"X-Orbit-Freshness": "stale",
                                               "X-Orbit-Projection": "pending"})
        return JSONResponse(body, headers={"X-Orbit-Freshness": "fresh"})

    @api.get("/v1/status")
    def status():
        started = time.perf_counter()
        revisions = gw.revisions.snapshot()
        state = gw.state.snapshot()
        active = [j for j in state["jobs"].values() if j["status"] in ("queued", "running")]
        enabled = [s for s in state["sources"].values() if s.get("enabled")]
        if revisions["data_rev"] is None:
            phase = "importing" if active else "onboarding"
        else:
            phase = "importing" if any(j["kind"] == "import" for j in active) else "ready"
        # A running rebuild publishes the projection too: never offer 重新导入 beside it.
        importing = any(j["kind"] in ("import", "rebuild") for j in active)
        return {
            "state": phase, "version": __version__, "data_rev": revisions["data_rev"],
            "inventory_rev": revisions["inventory_rev"], "projection": revisions["projection"],
            "projection_info": gw.projection_info(revisions, importing),
            "counts": revisions["counts"],
            "sources": [{k: s.get(k) for k in ("id", "agent", "enabled", "last_import_at")}
                        for s in state["sources"].values()],
            "sources_enabled": len(enabled), "jobs_active": [
                {k: j.get(k) for k in ("id", "kind", "status", "progress", "phase")}
                for j in active],
            "services": gw.supervisor.services(), "settings": state["settings"],
            "collection": {"paused": gw.platform.collection.paused},
            "privacy": {"active_rules": privacy_rules.active_count()},
            "badge": gw.platform.notifier.summary()["active"],
            "capabilities": {"sse": True, "snapshots": True, "export": True},
            "server_ms": round((time.perf_counter() - started) * 1000, 3)}

    @api.get("/health")
    def health():
        revisions = gw.revisions.snapshot()
        return {"ok": True, "status": "ok", "version": __version__,
                "services": gw.supervisor.services(), "data_rev": revisions["data_rev"],
                "projection": revisions["projection"], "counts": revisions["counts"]}

    @api.get("/v1/sessions")
    def sessions(request: Request, project_id: str | None = None, kind: str | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        """Newest first. ``kind`` defaults to ``main`` (user sessions); ``all`` lists every
        kind, or pass a comma list such as ``main,review``. ``model`` is the session's most
        used model (``unknown`` when it reported none)."""
        from ..data_access.store import (
            SESSION_MODEL_SQL,
            report_session,
            session_filter,
            session_kinds,
        )

        try:
            kinds = session_kinds(kind)
        except ValueError as error:
            raise ApiError(422, "invalid_kind", str(error)) from error
        total_header = {}

        def produce(db):
            clause, params = session_filter(project_id or None, kinds)
            base = (" FROM session s LEFT JOIN source src ON src.source_id=s.source_id"
                    " LEFT JOIN project p ON p.project_id=s.project_id" + clause)
            total_header["X-Total-Count"] = str(db.execute("SELECT count(*)" + base,
                                                           params).fetchone()[0])
            rows = db.execute("SELECT s.*,src.agent,p.name AS project_name," + SESSION_MODEL_SQL + base +
                              " ORDER BY s.started_at DESC,s.session_uid LIMIT ? OFFSET ?",
                              [*params, limit, offset]).fetchall()
            items = [report_session(dict(r), {"name": r["project_name"]}) for r in rows]
            return [{k: s[k] for k in SESSION_FIELDS} for s in items]

        body = served(request, produce)
        body.headers.update(total_header)
        return body

    @api.get("/v1/sessions/{session_id}/events")
    def events(request: Request, session_id: str, offset: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=500), after_seq: int | None = Query(None, ge=-1),
               max_chars: int = Query(LIST_MAX_CHARS, ge=1, le=RANGE_MAX_CHARS)):
        """Event texts are capped at ``max_chars`` (``truncated`` / ``text_range`` say so);
        the full text is read by range from ``/v1/evidence/{event_id}``."""
        from orbit_data.analysis_input import decoded

        from ..data_access.store import report_event

        def produce(db):
            if not db.execute("SELECT 1 FROM session WHERE session_uid=?",
                              (session_id,)).fetchone():
                raise ApiError(404, "not_found", "会话不存在或不在分析范围内")
            total = db.execute("SELECT count(*) FROM event WHERE session_uid=?",
                               (session_id,)).fetchone()[0]
            rows = [decoded(row) for row in db.execute(
                "SELECT e.*,c.model_raw FROM event e LEFT JOIN event_context c USING(event_uid)"
                " WHERE session_uid=? AND seq>? ORDER BY seq LIMIT ? OFFSET ?",
                (session_id, after_seq if after_seq is not None else -1, limit, offset))]
            return {"total": total,
                    "items": [cap_event(report_event(e).to_dict(), max_chars) for e in rows],
                    "next_after_seq": rows[-1]["seq"] if rows else None}

        return served(request, produce)

    @api.get("/v1/evidence/{event_id}")
    def evidence(request: Request, event_id: str, text_offset: int = Query(0, ge=0),
                 max_chars: int = Query(EVIDENCE_MAX_CHARS, ge=1, le=RANGE_MAX_CHARS)):
        """One event; ``text`` is the range ``[text_offset, text_offset + max_chars)`` and
        ``text_range.total`` the full length, so a client pages through huge outputs."""
        from orbit_data.analysis_input import decoded

        from ..data_access.store import report_event

        def produce(db):
            row = db.execute("SELECT e.*,c.model_raw FROM event e LEFT JOIN event_context c"
                             " USING(event_uid) WHERE e.event_uid=?", (event_id,)).fetchone()
            if row is None:
                raise ApiError(404, "not_found", "证据不存在或不在分析范围内")
            return cap_event(report_event(decoded(row)).to_dict(), max_chars, text_offset)

        return served(request, produce)

    @api.get("/v1/projects")
    def projects(request: Request, include_empty: bool = False):
        """Projects by session attribution. ``sessions`` counts main sessions, the same set
        ``/v1/sessions?project_id=`` lists by default; ``sessions_all`` counts every kind.
        Projects without any session (only event-level attribution) are hidden unless
        ``include_empty``. Names shared by several projects get their parent folder."""

        def produce(db):
            rows = db.execute(
                "SELECT p.project_id,p.name,p.key_type,p.key,"
                " COUNT(s.session_uid) FILTER (WHERE s.kind='main') AS sessions,"
                " COUNT(s.session_uid) AS sessions_all,"
                " MAX(s.started_at) AS last_started_at FROM project p"
                " LEFT JOIN session s ON s.project_id=p.project_id"
                " GROUP BY p.project_id ORDER BY sessions DESC, sessions_all DESC, p.project_id"
            ).fetchall()
            items = [dict(r) for r in rows if include_empty or r["sessions_all"]]
            return disambiguate_names(items)

        return served(request, produce)

    @api.get("/v1/sources")
    def sources(request: Request):
        def produce(db):
            configured = gw.state.snapshot()["sources"]
            rows = db.execute(
                "SELECT s.source_id,s.agent,s.label,s.enabled,x.selection,x.discovered_files,"
                "x.indexed_files,x.capture_errors,x.cancelled,"
                "(SELECT COUNT(*) FROM session t WHERE t.source_id=s.source_id) AS sessions"
                " FROM source s LEFT JOIN source_scan x USING(source_id)"
                " ORDER BY s.source_id").fetchall()
            return [{**dict(r), "app_enabled": configured.get(r["source_id"], {}).get("enabled")}
                    for r in rows]

        return served(request, produce, check=False)

    @api.get("/v1/inventory")
    def inventory(request: Request):
        from orbit_data.inventory import read_inventory_connection

        return served(request, read_inventory_connection, check=False)

    return api
