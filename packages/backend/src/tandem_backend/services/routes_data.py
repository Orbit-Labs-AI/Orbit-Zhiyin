"""Direct reads: status, health, sessions, events, projects, sources, inventory.

``/v1/status`` and ``/health`` answer from memory (no database round trip). Table reads
use one ``mode=ro`` connection per thread. When the projection is pending (an import
captured files but has not rebuilt yet) a previous response for the same request is
returned with ``X-Tandem-Freshness: stale``; without one the answer is 503 + Retry-After.
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

if TYPE_CHECKING:
    from .gateway import Gateway

SESSION_FIELDS = ("id", "title", "project_id", "project", "model", "started_at")


class ReadPool:
    """Per-thread query-only connections; WAL lets them read while the worker writes."""

    def __init__(self, path: Path):
        self.path = path
        self.local = threading.local()
        self.lock = threading.Lock()
        self.connections: list[sqlite3.Connection] = []

    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self.local, "connection", None)
        if connection is None:
            if not self.path.is_file():
                raise ApiError(503, "no_projection", "No canonical database yet; import a source",
                               retryable=True, retry_after=2)
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
    def read(self, check: bool = True):
        from tandem_data.query import current_projection

        connection = self._connection()
        try:
            connection.execute("BEGIN")
            if check:
                current_projection(connection)
            yield connection
        except ValueError as error:
            if "Projection is pending" in str(error):
                raise ApiError(503, "projection_pending", "Import is publishing a new revision",
                               retryable=True, retry_after=1) from error
            raise ApiError(409, "rebuild_required", str(error), retryable=True) from error
        except sqlite3.OperationalError as error:
            raise ApiError(503, "service_unavailable", f"Database busy: {error}",
                           retryable=True, retry_after=1) from error
        finally:
            if connection.in_transaction:
                connection.rollback()

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

    def served(request: Request, produce, headers: dict | None = None):
        key = request.url.path + "?" + request.url.query
        try:
            body = jsonable_encoder(produce())
        except ApiError as error:
            cached = last_good.get(key) if error.code == "projection_pending" else None
            if cached is None:
                raise
            return JSONResponse(cached, headers={"X-Tandem-Freshness": "stale"})
        last_good.remember(key, body)
        return JSONResponse(body, headers={"X-Tandem-Freshness": "fresh", **(headers or {})})

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
        return {
            "state": phase, "version": __version__, "data_rev": revisions["data_rev"],
            "inventory_rev": revisions["inventory_rev"], "projection": revisions["projection"],
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
            "capabilities": {"sse": True, "snapshots": True, "export": False},
            "server_ms": round((time.perf_counter() - started) * 1000, 3)}

    @api.get("/health")
    def health():
        revisions = gw.revisions.snapshot()
        return {"ok": True, "status": "ok", "version": __version__,
                "services": gw.supervisor.services(), "data_rev": revisions["data_rev"],
                "projection": revisions["projection"], "counts": revisions["counts"]}

    @api.get("/v1/sessions")
    def sessions(request: Request, project_id: str | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        from ..data_access.store import report_session

        total_header = {}

        def produce():
            clause, params = (" WHERE s.project_id=?", [project_id]) if project_id else ("", [])
            base = " FROM session s LEFT JOIN project p ON p.project_id=s.project_id" + clause
            with gw.reads.read() as db:
                total_header["X-Total-Count"] = str(db.execute("SELECT count(*)" + base,
                                                               params).fetchone()[0])
                rows = db.execute("SELECT s.*,p.name AS project_name" + base +
                                  " ORDER BY s.started_at DESC,s.session_uid LIMIT ? OFFSET ?",
                                  [*params, limit, offset]).fetchall()
            items = [report_session(dict(r), {"name": r["project_name"]}) for r in rows]
            return [{k: s[k] for k in SESSION_FIELDS} for s in items]

        body = served(request, produce)
        body.headers.update(total_header)
        return body

    @api.get("/v1/sessions/{session_id}/events")
    def events(request: Request, session_id: str, offset: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=500), after_seq: int | None = Query(None, ge=-1)):
        from tandem_data.analysis_input import decoded

        from ..data_access.store import report_event

        def produce():
            with gw.reads.read() as db:
                if not db.execute("SELECT 1 FROM session WHERE session_uid=?",
                                  (session_id,)).fetchone():
                    raise ApiError(404, "not_found", "会话不存在或不在分析范围内")
                total = db.execute("SELECT count(*) FROM event WHERE session_uid=?",
                                   (session_id,)).fetchone()[0]
                rows = [decoded(row) for row in db.execute(
                    "SELECT e.*,c.model_raw FROM event e LEFT JOIN event_context c USING(event_uid)"
                    " WHERE session_uid=? AND seq>? ORDER BY seq LIMIT ? OFFSET ?",
                    (session_id, after_seq if after_seq is not None else -1, limit, offset))]
            return {"total": total, "items": [report_event(e).to_dict() for e in rows],
                    "next_after_seq": rows[-1]["seq"] if rows else None}

        return served(request, produce)

    @api.get("/v1/projects")
    def projects(request: Request):
        def produce():
            with gw.reads.read() as db:
                rows = db.execute(
                    "SELECT p.project_id,p.name,COUNT(s.session_uid) AS sessions,"
                    " MAX(s.started_at) AS last_started_at FROM project p"
                    " LEFT JOIN session s ON s.project_id=p.project_id"
                    " GROUP BY p.project_id ORDER BY sessions DESC, p.project_id").fetchall()
            return [dict(r) for r in rows]

        return served(request, produce)

    @api.get("/v1/sources")
    def sources(request: Request):
        def produce():
            configured = gw.state.snapshot()["sources"]
            with gw.reads.read(check=False) as db:
                rows = db.execute(
                    "SELECT s.source_id,s.agent,s.label,s.enabled,x.selection,x.discovered_files,"
                    "x.indexed_files,x.capture_errors,x.cancelled,"
                    "(SELECT COUNT(*) FROM session t WHERE t.source_id=s.source_id) AS sessions"
                    " FROM source s LEFT JOIN source_scan x USING(source_id)"
                    " ORDER BY s.source_id").fetchall()
            return [{**dict(r), "app_enabled": configured.get(r["source_id"], {}).get("enabled")}
                    for r in rows]

        return served(request, produce)

    @api.get("/v1/inventory")
    def inventory(request: Request):
        from tandem_data.inventory import read_inventory_connection

        def produce():
            with gw.reads.read(check=False) as db:
                return read_inventory_connection(db)

        return served(request, produce)

    return api
