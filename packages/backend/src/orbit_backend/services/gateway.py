"""gateway: the UI's only entry point (HTTP + SSE) and the supervisor of both workers.

Own routes are registered first; every other request falls through ``mount("/")`` to the
existing ``api.routes.create_app()`` (unchanged), whose shutdown handlers are forwarded.
Startup prints ``{"port": N}`` as the first stdout line; ``ORBIT_PARENT_PID`` makes the
gateway exit when the native host disappears.
"""

from __future__ import annotations

import asyncio
import json
import logging
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
from ..appdata.wipe import apply_pending
from ..appdb import AppDB
from ..platform import logs
from ..platform.middleware import PlatformMiddleware
from ..platform.runtime import Platform
from .auth import TOKEN_ENV, ApiError, GuardMiddleware, error_body, validate_token
from .events import EventBus
from .jobs import AppState, JobConflict, JobService
from .routes_data import ReadPool
from .sections import HEAVY, LIGHT, rules_digest
from .snapshots import SnapshotKey, SnapshotStore, scope_hash
from .supervisor import Supervisor, SupervisorConfig

log = logging.getLogger(__name__)
PARENT_ENV = "ORBIT_PARENT_PID"
HOURLY_SYNC_S = 3600.0  # sync_mode "hour"
STUCK_AFTER_S = 60.0  # pending with no import running this long: offer the retry
FINISHED = frozenset({"completed", "partial", "cancelled", "failed", "interrupted"})
STATUS_CODES = {400: "invalid_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                405: "method_not_allowed", 409: "conflict", 422: "invalid_request",
                503: "service_unavailable"}


class Revisions:
    """Published data_rev / inventory_rev and the freshness of that publication, in memory.

    Updated from worker events (``published`` carries the freshness read right after the
    publication) and re-read from the database after every import ends and at start, so
    ``projection`` never claims ``ready`` while captured files wait (v0.0.2 RC-4).
    ``pending_since`` is when the published snapshot first fell behind.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.value = {"data_rev": None, "inventory_rev": 0, "projection": "absent",
                      "counts": None, "published_at": None, "pending_files": None,
                      "retained_files": None, "pending_since": None}

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.value)

    def update(self, **values) -> tuple[dict, dict]:
        with self.lock:
            before = dict(self.value)
            freshness = values.pop("freshness", None)
            self.value.update(values)
            if freshness:
                self._fresh(freshness)
            return before, dict(self.value)

    def _fresh(self, freshness: dict) -> None:
        state = freshness.get("projection") or "ready"
        if self.value["data_rev"] is None and state != "invalid":
            state = "absent"
        behind = state in ("pending", "invalid")
        self.value.update(
            projection=state, pending_files=freshness.get("pending_files"),
            retained_files=freshness.get("retained_files"),
            pending_since=(self.value.get("pending_since") or int(time.time() * 1000))
            if behind else None)

    def load(self, home: Path) -> None:
        """Read the published revision and its freshness (startup, after an import ends)."""
        if not (home / "orbit.db").is_file():
            return
        from .worker_ingest import revision

        try:
            info = revision(home)
        except (sqlite3.Error, OSError):
            return
        with self.lock:
            current = self.value["data_rev"]
            if current is not None and (info["data_rev"] is None or info["data_rev"] < current):
                return  # Read before a newer publication landed: never move backwards.
            freshness = info.pop("freshness", None)
            self.value.update(info)
            if freshness:
                self._fresh(freshness)


class LegacyApp:
    """Lazy ASGI fallback to ``create_app()``; it needs orbit.db, so build on first use."""

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


def default_scope(days: int | None, now: datetime | None = None) -> dict:
    """Last ``days`` UTC days from the start of a day, so one day maps to one scope hash
    (``None``: all time, the default of scope-less routes such as recommendations)."""
    from dataclasses import asdict

    from ..analytics.inputs import Scope

    if days is None:
        return asdict(Scope())
    now = now or datetime.now(UTC)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return asdict(Scope(from_ts=int(start.timestamp() * 1000)))


def next_sync_interval(mode: str | None, interval: float, changed: bool,
                       bounds: tuple[float, float], hourly: float = 3600.0) -> float:
    """``hour``: a fixed hourly import; ``live``: adaptive 2 s → 30 s backoff."""
    low, high = bounds
    if mode == "hour":
        return hourly
    return low if changed else min(high, interval * 2)


SYNC_FAILED = frozenset({"failed", "interrupted", "cancelled"})


def sync_wait(mode: str | None, last: dict | None, now_ms: int, idle: float,
              bounds: tuple[float, float], hourly: float = 3600.0) -> float:
    """Seconds until the next sync import may start, measured from the end of the last one.

    ``live`` used to start the next full import 2 s after any import that saw a change; an
    agent in use changes something every round, so imports ran back to back (v0.0.2
    RC-1). Now the pause after a sync import is at least as long as that import took, so
    continuous sync spends at most half the time importing; ``idle`` (2 s → 30 s while
    rounds find nothing) applies when nothing changed, and a failed, interrupted or
    cancelled sync import waits the long bound before the next attempt.
    """
    low, high = bounds
    if last is None or last.get("finished_at") is None:
        return 0.0
    elapsed = (now_ms - last["finished_at"]) / 1000
    if mode == "hour":
        return max(0.0, hourly - elapsed)
    if last.get("status") in SYNC_FAILED:
        wanted = high
    else:
        changed = any(r.get("changed") for r in last.get("results") or [])
        wanted = low if changed else idle
    started = last.get("started_at") or last["finished_at"]
    took = max(0.0, (last["finished_at"] - started) / 1000)
    return max(0.0, max(wanted, took) - elapsed)


class Gateway:
    def __init__(self, home: Path, *, config: SupervisorConfig | None = None,
                 discovery: Callable[[], list[dict]] | None = None,
                 prewarm_debounce_s: float = 30.0, prewarm_mru: int = 5,
                 sync_interval_s: tuple[float, float] = (2.0, 30.0),
                 heartbeat_s: float = 15.0):
        from orbit_data.discovery import candidates

        self.home = home.expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cleared = apply_pending(self.home)  # A pending "clear all data" runs first.
        self.config = config or SupervisorConfig()
        self.discovery = discovery or candidates
        self.bus = EventBus(heartbeat_s=heartbeat_s)
        self.state = AppState(self.home / "app-state.json")
        self.revisions = Revisions()
        self.snapshots = SnapshotStore(self.home / "cache" / "ui.sqlite")
        self.reads = ReadPool(self.home / "orbit.db")
        self.appdb = AppDB(self.home / "app.db")
        self.platform = Platform(self)
        self.supervisor = Supervisor(self.home, self.config, self.snapshots, self._emit,
                                     self._published)
        self.jobs = JobService(self.state, self.supervisor.ingest, self._emit)
        self.supervisor.ingest.jobs = self.jobs
        self.jobs.on_import_done = self._after_import
        self._bind_insight()
        self.prewarm_debounce_s, self.prewarm_mru = prewarm_debounce_s, prewarm_mru
        self.sync_interval_s = sync_interval_s
        self.hourly_sync_s = HOURLY_SYNC_S
        self.stuck_after_s = STUCK_AFTER_S
        self.prewarm_timer: threading.Timer | None = None
        self.prewarm_heavy = False
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.legacy = LegacyApp(self._legacy_factory)
        self.sync_thread: threading.Thread | None = None

    def _legacy_factory(self) -> FastAPI:
        from ..api.routes import create_app

        return create_app(home=self.home)

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        self.revisions.load(self.home)
        self.supervisor.start()
        if self.revisions.snapshot()["data_rev"] is not None:
            self.schedule_prewarm(heavy=False)  # Cold caches after a restart or an upgrade.
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True,
                                            name="orbit-sync")
        self.sync_thread.start()
        self.platform.start()

    def close(self) -> None:
        self.stopping.set()
        self.platform.close()
        self._close_services()
        with self.lock:
            if self.prewarm_timer is not None:
                self.prewarm_timer.cancel()
        realtime = getattr(self, "realtime", None)
        if realtime is not None and not realtime.close():  # its reads must end before reads close
            log.warning("realtime thread still reading after the join timeout; "
                        "closing the read pool anyway")
        self.bus.close()
        self.supervisor.stop()
        self.state.save()  # Persist the scope MRU used for prewarm.
        self.reads.close()
        self.snapshots.close()
        self.appdb.close()

    def _close_services(self) -> None:
        """Area services created by their routers (features hub, lazy AI service)."""
        from .. import features, privacy_rules
        from ..appdata import sources_scope
        from ..sessionops import exclusion
        from ..uiview import insight

        privacy_rules.bind(None)
        sources_scope.set_provider(None)
        insight.set_ai_provider(None)
        # The exclusion provider reads this gateway's app.db and fails closed once it is
        # closed; unbind it so later readers (CLI, the next gateway) are not refused.
        exclusion.set_provider(None)
        # bind(None) closes the bound hub; module helpers then fall back to "unbound".
        features.bind(None)
        ai = getattr(self, "_ai", None)
        if ai is not None:
            ai.close()

    @property
    def rec_settings(self) -> dict:
        """Recommend memory settings (ai_generate, level), edited via /v1/platform/recommend."""
        return self.platform.settings.get("recommend")

    # -- worker events -------------------------------------------------------------------
    def _emit(self, topic: str, event: str, data: dict) -> int:
        """Publish to SSE and let the platform observe (metrics, notifications)."""
        frame_id = self.bus.publish(topic, event, data)
        self.platform.observe(topic, event, data)
        if (topic == "job" and data.get("kind") in ("import", "rebuild")
                and data.get("status") in FINISHED):
            # Cancelled, failed or interrupted imports can leave captured files unpublished;
            # the freshness is read again instead of trusting the last ``published``.
            threading.Thread(target=self.revisions.load, args=(self.home,), daemon=True,
                             name="orbit-freshness").start()
        return frame_id

    def projection_info(self, revisions: dict, importing: bool) -> dict:
        """Freshness for ``/v1/status``: a published snapshot that stays behind with no
        import running for ``stuck_after_s`` is ``stuck`` and offers the retry request."""
        state = revisions.get("projection")
        since = revisions.get("pending_since")
        stuck = bool(state in ("pending", "invalid") and since and not importing
                     and time.time() * 1000 - since > self.stuck_after_s * 1000)
        info = {"state": state, "pending_files": revisions.get("pending_files"),
                "retained_files": revisions.get("retained_files"), "pending_since": since,
                "stuck": stuck}
        if stuck:
            info["retry"] = {"method": "POST", "path": "/v1/app/jobs", "body": {"kind": "import"}}
        return info

    def _published(self, entry: dict) -> None:
        before, after = self.revisions.update(
            data_rev=entry.get("data_rev"), inventory_rev=entry.get("inventory_rev") or 0,
            counts=entry.get("counts"), published_at=int(time.time() * 1000),
            freshness=entry.get("freshness") or {"projection": "ready"})
        if (before["data_rev"], before["inventory_rev"]) == (after["data_rev"],
                                                             after["inventory_rev"]):
            return  # Nothing new was published (for example a cancelled batch).
        self._emit("data", "data.published", {
            "data_rev": after["data_rev"], "inventory_rev": after["inventory_rev"],
            "phase": entry.get("phase"), "counts": after["counts"],
            "sources": [entry.get("source_id")] if entry.get("source_id") else []})
        self.schedule_prewarm(heavy=entry.get("phase") not in ("head", "window"))

    def _bind_insight(self) -> None:
        """A1 insight shows a model-written overview only for this gateway's app.db."""
        from ..ai.narratives import latest_overview
        from ..uiview import insight

        appdb = self.appdb
        insight.set_ai_provider(lambda scope, data_rev: latest_overview(appdb, scope, data_rev))

    def _after_import(self, job: dict) -> None:
        """Import finished with new data: queue AI facets for new sessions when the user turned
        on ``settings.auto_facet_new`` (``ai.auto_facet_new`` checks the setting itself). Runs
        off the ingest reader thread so the worker's next messages are not held up."""
        if self.stopping.is_set():
            return
        threading.Thread(target=self.auto_facet, daemon=True, name="ai-auto-facet").start()

    def auto_facet(self) -> dict | None:
        from .. import ai

        try:
            return ai.auto_facet_new(self)
        except Exception:  # noqa: BLE001 - optional background work; the import already succeeded
            log.warning("auto facet after import failed", exc_info=True)
            return None

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
        """Warm the first screens after an import or a cold start, most likely first.

        1. ``uiview_facts`` then the light sections for the last 7 days, 30 days and all
           time (the first-open fast path's windows): the facts pass computes the whole
           analysis of a window, so the light sections after it are cache reads;
        2. the default range setting when it is another window, then recent MRU scopes;
        3. heavy sections and recommendations after an import's full phase.
        Scopes are built like the routes build them (client timezone from the MRU, default
        sources, persistent session exclusions) so the snapshot keys match.
        """
        from dataclasses import asdict

        from ..uiview.fetch import SECTION as FACTS
        from . import fastpath
        from .routes_analytics import analytics_scope

        rev = self.revisions.snapshot()
        if rev["data_rev"] is None or self.stopping.is_set():
            return []
        state = self.state.snapshot()
        mru = state["mru_scopes"]
        tz = next((s.get("display_timezone") for s in mru if s.get("display_timezone")), "UTC")
        try:
            base = asdict(analytics_scope(display_timezone=tz))
        except Exception:  # noqa: BLE001  an invalid stored timezone falls back to UTC
            base = asdict(analytics_scope())
        work: list[tuple[str, dict]] = []
        # Light sections the window's full pass already caches (preferences differs with
        # text, so it is left to the MRU pass and on-demand requests).
        cached = [name for name in LIGHT if name != "preferences"]
        for days in fastpath.LADDER:
            scope = fastpath.windowed(base, days)
            work += [(FACTS, scope), *((name, scope) for name in cached)]
        # default_range_days 0 means "all time" (the scope-less default).
        configured = state["settings"].get("default_range_days", 30) or 0
        if configured not in fastpath.LADDER:
            work += [(name, fastpath.windowed(base, configured)) for name in LIGHT]
        scopes = [s for s in mru[: self.prewarm_mru]]
        work += [(name, scope) for name in LIGHT for scope in scopes]
        if self.prewarm_heavy:
            from ..recommend.inputs import SECTION

            windows = [fastpath.windowed(base, d) for d in fastpath.LADDER]
            work += [(name, scope) for name in HEAVY for scope in [*windows, *scopes]]
            # /v1/recommendations without parameters: all time, default sources and the
            # persistent exclusions (the key must match the route's analytics_scope()).
            work.append((SECTION, asdict(analytics_scope())))
        rules = rules_digest()
        queued, seen = [], set()
        for name, scope in work:
            h = scope_hash(scope, {})
            if (name, h) in seen:
                continue
            seen.add((name, h))
            key = SnapshotKey(name, h, rev["data_rev"], rev["inventory_rev"], rules)
            if self.snapshots.get(key) is not None:
                continue
            task = self.supervisor.analysis.submit(
                name, scope, {}, h, "prewarm", (rev["data_rev"], rev["inventory_rev"]), rules)
            if task is not None:
                queued.append(task.id)
        return queued

    def _sync_loop(self) -> None:
        """Continuous sync (opt-in), one ``_sync_round`` at a time: ``live`` polls 2 s → 30 s
        while nothing changes and waits after each sync import at least as long as it took
        (``sync_wait``); ``hour`` imports hourly. A bad round is logged, never fatal."""
        low, high = self.sync_interval_s
        interval = low
        collection = self.platform.collection
        while not self.stopping.wait(interval):
            try:
                interval = _sync_round(self, collection, interval)
            except Exception as error:  # noqa: BLE001 - one bad round must not end continuous sync
                logs.log_event("sync_loop_error", logging.ERROR,
                               error=f"{type(error).__name__}: {error}"[:300])
                interval = high

    # -- application ---------------------------------------------------------------------
    def app(self, *, token: str, port: int | None, hosts=None) -> FastAPI:
        from . import (
            pages,
            routes_ai,
            routes_analytics,
            routes_app,
            routes_catalog,
            routes_data,
            routes_eval,
            routes_export,
            routes_features,
            routes_install,
            routes_platform,
            routes_quota,
            routes_realtime,
            routes_recommend,
            routes_sessionops,
            routes_settings,
            routes_shell,
            routes_uiview,
            routes_uiview_a4a6,
        )

        @asynccontextmanager
        async def lifespan(_: FastAPI):
            self.start()
            try:
                yield
            finally:
                await self.legacy.shutdown()
                await asyncio.to_thread(self.close)

        app = FastAPI(title="Orbit gateway", version=__version__, lifespan=lifespan,
                      docs_url=None, redoc_url=None, openapi_url="/v1/openapi.json")
        install_error_handlers(app)
        app.include_router(routes_data.router(self))
        app.include_router(routes_app.router(self))
        app.include_router(routes_analytics.router(self))
        for module in (
            routes_catalog,
            routes_features,
            routes_recommend,
            routes_ai,
            routes_install,
            routes_platform,
            routes_eval,
            routes_realtime,
            routes_sessionops,
            routes_quota,
            routes_export,
            routes_settings,
            routes_shell,
            routes_uiview,
            routes_uiview_a4a6,
        ):
            app.include_router(module.router(self))
        app.include_router(pages.router())  # /app, /lite, / (token-free, see PAGE_PATHS).
        app.mount("/", self.legacy)  # Registered last: every other path reaches create_app().
        app.state.gateway = self
        guard_kwargs = {"hosts": hosts} if hosts else {}
        guard_kwargs["public_paths"] = pages.PAGE_PATHS
        app.add_middleware(PlatformMiddleware, platform=self.platform)  # Inside the guard.
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


def _sync_round(self, collection, interval: float) -> float:
    """One continuous-sync round for gateway ``self``; returns the wait before the next.

    v0.0.2 submitted the next full import 2 s after any sync import that saw a change; an
    agent in use changes something every round, so imports ran back to back (RC-1). Now a
    round waits ``sync_wait`` after the last sync import ended: at least as long as it took,
    2 s → 30 s (``self._sync_idle``) while rounds find nothing, 30 s after a failed,
    interrupted or cancelled one. While any job is active it only looks again soon; a
    collection catch-up runs as soon as nothing else is active; never while stopping.
    """
    low, high = self.sync_interval_s
    if collection.paused:
        return high  # Collection paused (DT-02.1); explicit re-index still works.
    state = self.state.snapshot()
    enabled = [k for k, s in state["sources"].items() if s.get("enabled")]
    mode = state["settings"].get("sync_mode")
    if (mode not in ("live", "hour") and not collection.catch_up_pending) or not enabled:
        return high
    if self.state.active_job() is not None:
        return low  # Another job is active; look again soon.
    last = self.state.latest_job("sync")
    idle = getattr(self, "_sync_idle", low)
    if last is not None and last["id"] != getattr(self, "_sync_seen", None):
        self._sync_seen = last["id"]
        changed = any(r.get("changed") for r in last.get("results") or [])
        idle = self._sync_idle = low if changed else min(high, idle * 2)
    failed_catch_up = collection.catch_up_pending and last is not None and last.get("status") in SYNC_FAILED
    if not collection.catch_up_pending or failed_catch_up:
        # A failed resume dispatch retains its intent, but observes the normal
        # failure backoff even when periodic sync is off (or hourly).
        wait = sync_wait("live" if failed_catch_up else mode, last, int(time.time() * 1000),
                         idle, self.sync_interval_s, getattr(self, "hourly_sync_s", HOURLY_SYNC_S))
        if wait > 0:
            return min(wait, high) if mode == "live" else wait
    if self.stopping.is_set():
        return high  # Shutting down: never start an import on the way out.
    catch_up = collection.consume_catch_up()
    try:
        job = self.jobs.submit("import", enabled, phase="full", origin="sync")
        if catch_up and isinstance(job, dict) and job.get("status") in SYNC_FAILED:
            collection.catch_up_pending = True
    except (JobConflict, ValueError):
        collection.catch_up_pending |= catch_up  # Retry the catch-up next round.
    return low
