"""gateway: the UI's only entry point (HTTP + SSE) and the supervisor of both workers.

Own routes are registered first; every other request falls through ``mount("/")`` to the
existing ``api.routes.create_app()`` (unchanged), whose shutdown handlers are forwarded.
Startup prints ``{"port": N}`` as the first stdout line; ``TANDEM_PARENT_PID`` makes the
gateway exit when the native host disappears.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from .. import __version__
from .auth import TOKEN_ENV, ApiError, GuardMiddleware, error_body, validate_token
from .events import EventBus
from .jobs import AppState, JobConflict, JobService
from .routes_data import ReadPool
from .sections import HEAVY, LIGHT, rules_digest
from .snapshots import SnapshotKey, SnapshotStore, scope_hash
from .supervisor import Supervisor, SupervisorConfig

PARENT_ENV = "TANDEM_PARENT_PID"
STATUS_CODES = {400: "invalid_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                405: "method_not_allowed", 409: "conflict", 422: "invalid_request",
                503: "service_unavailable"}


class Revisions:
    """Published data_rev / inventory_rev kept in memory; updated by worker events only."""

    def __init__(self):
        self.lock = threading.Lock()
        self.value = {"data_rev": None, "inventory_rev": 0, "projection": "absent",
                      "counts": None, "published_at": None}

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.value)

    def update(self, **values) -> tuple[dict, dict]:
        with self.lock:
            before = dict(self.value)
            self.value.update(values)
            return before, dict(self.value)

    def load(self, home: Path) -> None:
        """One read at startup (off the request path); absent database stays absent."""
        path = home / "tandem.db"
        if not path.is_file():
            return
        from tandem_data.query import current_projection
        from tandem_data.store import readonly_connection

        from .worker_ingest import revision

        try:
            info = revision(home)
            with readonly_connection(path) as db:
                db.execute("BEGIN")
                try:
                    current_projection(db)
                    projection = "ready"
                except ValueError:
                    projection = "pending"
        except (sqlite3.Error, OSError):
            return
        self.update(projection=projection if info["data_rev"] is not None else "absent", **info)


class LegacyApp:
    """Lazy ASGI fallback to ``create_app()``; it needs tandem.db, so build on first use."""

    def __init__(self, factory: Callable[[], FastAPI]):
        self.factory = factory
        self.app: FastAPI | None = None
        self.lock = threading.Lock()

    def _build(self) -> FastAPI | None:
        with self.lock:
            if self.app is None:
                try:
                    app = self.factory()
                except ValueError:
                    return None  # No canonical database yet; retry on a later request.
                install_error_handlers(app)
                self.app = app
            return self.app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            return  # Startup/shutdown are forwarded by the gateway lifespan.
        app = self.app or await asyncio.to_thread(self._build)
        if app is None:
            body = error_body("no_projection", "No canonical database yet; import a source", True)
            await send({"type": "http.response.start", "status": 503, "headers": [
                (b"content-type", b"application/json"), (b"retry-after", b"2"),
                (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await app(scope, receive, send)

    async def shutdown(self) -> None:
        if self.app is not None:
            await self.app.router.shutdown()


def install_error_handlers(app: FastAPI) -> None:
    """Uniform ``{"error": {code, message, retryable}}`` bodies for gateway and legacy."""

    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError):
        return JSONResponse(error.payload(), status_code=error.status, headers=error.headers())

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException):
        message = error.detail if isinstance(error.detail, str) else json.dumps(
            error.detail, ensure_ascii=False)
        code = STATUS_CODES.get(error.status_code, "error")
        if error.status_code == 422 and "limit exceeded" in message:
            code = "analysis_scope_too_large"
        return JSONResponse({"error": {"code": code, "message": message,
                                       "retryable": error.status_code >= 500}},
                            status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        message = "; ".join(f"{'.'.join(map(str, e.get('loc', ())))}: {e.get('msg')}"
                            for e in error.errors())
        return JSONResponse({"error": {"code": "invalid_request", "message": message,
                                       "retryable": False}}, status_code=422)


def default_scope(days: int, now: datetime | None = None) -> dict:
    """Last ``days`` UTC days from the start of a day, so one day maps to one scope hash."""
    now = now or datetime.now(UTC)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    from dataclasses import asdict

    from ..analytics.inputs import Scope

    return asdict(Scope(from_ts=int(start.timestamp() * 1000)))


class Gateway:
    def __init__(self, home: Path, *, config: SupervisorConfig | None = None,
                 discovery: Callable[[], list[dict]] | None = None,
                 prewarm_debounce_s: float = 30.0, prewarm_mru: int = 5,
                 sync_interval_s: tuple[float, float] = (2.0, 30.0),
                 heartbeat_s: float = 15.0):
        from tandem_data.discovery import candidates

        self.home = home.expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config = config or SupervisorConfig()
        self.discovery = discovery or candidates
        self.bus = EventBus(heartbeat_s=heartbeat_s)
        self.state = AppState(self.home / "app-state.json")
        self.revisions = Revisions()
        self.snapshots = SnapshotStore(self.home / "cache" / "ui.sqlite")
        self.reads = ReadPool(self.home / "tandem.db")
        self.supervisor = Supervisor(self.home, self.config, self.snapshots, self.bus.publish,
                                     self._published)
        self.jobs = JobService(self.state, self.supervisor.ingest, self.bus.publish)
        self.supervisor.ingest.jobs = self.jobs
        self.prewarm_debounce_s, self.prewarm_mru = prewarm_debounce_s, prewarm_mru
        self.sync_interval_s = sync_interval_s
        self.prewarm_timer: threading.Timer | None = None
        self.prewarm_heavy = False
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.legacy = LegacyApp(self._legacy_factory)

    def _legacy_factory(self) -> FastAPI:
        from ..api.routes import create_app

        return create_app(home=self.home)

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        self.revisions.load(self.home)
        self.supervisor.start()
        threading.Thread(target=self._sync_loop, daemon=True, name="tandem-sync").start()

    def close(self) -> None:
        self.stopping.set()
        with self.lock:
            if self.prewarm_timer is not None:
                self.prewarm_timer.cancel()
        self.bus.close()
        self.supervisor.stop()
        self.state.save()  # Persist the scope MRU used for prewarm.
        self.reads.close()
        self.snapshots.close()

    # -- worker events -------------------------------------------------------------------
    def _published(self, entry: dict) -> None:
        before, after = self.revisions.update(
            data_rev=entry.get("data_rev"), inventory_rev=entry.get("inventory_rev") or 0,
            counts=entry.get("counts"), projection="ready",
            published_at=int(time.time() * 1000))
        if (before["data_rev"], before["inventory_rev"]) == (after["data_rev"],
                                                             after["inventory_rev"]):
            return  # Nothing new was published (for example a cancelled batch).
        self.bus.publish("data", "data.published", {
            "data_rev": after["data_rev"], "inventory_rev": after["inventory_rev"],
            "phase": entry.get("phase"), "counts": after["counts"],
            "sources": [entry.get("source_id")] if entry.get("source_id") else []})
        self.schedule_prewarm(heavy=entry.get("phase") not in ("head", "window"))

    def schedule_prewarm(self, heavy: bool) -> None:
        """Debounced: consecutive batches trigger one prewarm after the last publish."""
        with self.lock:
            if self.stopping.is_set():
                return
            if self.prewarm_timer is not None:
                self.prewarm_timer.cancel()
            self.prewarm_heavy = heavy
            self.prewarm_timer = threading.Timer(self.prewarm_debounce_s, self.prewarm)
            self.prewarm_timer.daemon = True
            self.prewarm_timer.start()

    def prewarm(self) -> list[str]:
        rev = self.revisions.snapshot()
        if rev["data_rev"] is None or self.stopping.is_set():
            return []
        state = self.state.snapshot()
        scopes = [default_scope(state["settings"].get("default_range_days", 30))]
        scopes += [s for s in state["mru_scopes"][: self.prewarm_mru] if s not in scopes]
        sections = LIGHT + (HEAVY if self.prewarm_heavy else ())
        rules = rules_digest()
        queued = []
        for name in sections:  # Light sections of every scope first, then heavy ones.
            for scope in scopes:
                h = scope_hash(scope, {})
                key = SnapshotKey(name, h, rev["data_rev"], rev["inventory_rev"], rules)
                if self.snapshots.get(key) is not None:
                    continue
                task = self.supervisor.analysis.submit(
                    name, scope, {}, h, "prewarm", (rev["data_rev"], rev["inventory_rev"]), rules)
                if task is not None:
                    queued.append(task.id)
        return queued

    def _sync_loop(self) -> None:
        """Continuous sync (opt-in): adaptive polling 2 s → 30 s while nothing changes."""
        low, high = self.sync_interval_s
        interval = low
        while not self.stopping.wait(interval):
            state = self.state.snapshot()
            enabled = [k for k, s in state["sources"].items() if s.get("enabled")]
            if state["settings"].get("sync_mode") != "live" or not enabled:
                interval = high
                continue
            last = next((j for j in self.state.jobs() if j.get("origin") == "sync"), None)
            changed = bool(last and any(r.get("changed") for r in last.get("results") or []))
            interval = low if changed else min(high, interval * 2)
            try:
                self.jobs.submit("import", enabled, phase="full", origin="sync")
            except (JobConflict, ValueError):
                interval = low  # A user job is running; check again soon.

    # -- application ---------------------------------------------------------------------
    def app(self, *, token: str, port: int | None, hosts=None) -> FastAPI:
        from . import routes_analytics, routes_app, routes_data

        @asynccontextmanager
        async def lifespan(_: FastAPI):
            self.start()
            try:
                yield
            finally:
                await self.legacy.shutdown()
                await asyncio.to_thread(self.close)

        app = FastAPI(title="Tandem gateway", version=__version__, lifespan=lifespan,
                      docs_url=None, redoc_url=None, openapi_url="/v1/openapi.json")
        install_error_handlers(app)
        app.include_router(routes_data.router(self))
        app.include_router(routes_app.router(self))
        app.include_router(routes_analytics.router(self))
        app.mount("/", self.legacy)  # Registered last: every other path reaches create_app().
        app.state.gateway = self
        guard_kwargs = {"hosts": hosts} if hosts else {}
        app.add_middleware(GuardMiddleware, token=token, port=port, **guard_kwargs)
        return app


def create_gateway(home: Path, token: str, *, port: int | None = None, **options) -> FastAPI:
    return Gateway(home, **options).app(token=validate_token(token), port=port)


def parent_alive(parent: int) -> bool:
    if os.getppid() == 1:
        return False  # Re-parented to launchd/init: the host is gone.
    try:
        os.kill(parent, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watch_parent(parent: int, server) -> None:
    while not server.should_exit:
        if not parent_alive(parent):
            server.handle_exit(None, None)
            return
        time.sleep(1)


def run_gateway(home: Path, *, port: int = 0, host: str = "127.0.0.1") -> int:
    import uvicorn

    try:
        token = validate_token(os.environ.get(TOKEN_ENV))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    bound = sock.getsockname()[1]
    gateway = Gateway(home)
    app = gateway.app(token=token, port=bound)
    config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="on",
                            timeout_graceful_shutdown=3)

    class Server(uvicorn.Server):
        def handle_exit(self, sig, frame):
            gateway.bus.close()  # End SSE streams so graceful shutdown does not wait on them.
            super().handle_exit(sig, frame)

    server = Server(config)
    parent = os.environ.get(PARENT_ENV)
    if parent:
        threading.Thread(target=_watch_parent, args=(int(parent), server), daemon=True,
                         name="parent-watch").start()
    print(json.dumps({"port": bound}), flush=True)  # First stdout line: the host's handshake.
    server.run(sockets=[sock])
    return 0
