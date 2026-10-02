"""analysis worker: computes one SECTIONS entry at a time over a read-only canonical store.

CPU-bound analysis lives here so the gateway event loop never blocks; the supervisor
enforces timeouts by killing this process. Prewarm jobs lower the OS priority
(``setpriority``); the supervisor recycles a lowered worker before interactive work.
Errors are classified so the gateway can answer 422 / 404 / 503 without guessing.
"""

from __future__ import annotations

import os
import time
import traceback
from pathlib import Path

from .sections import ResultMemo, SectionNotFound, compute_section, estimate_events
from .worker_protocol import WorkerIO, debug_delay, peak_rss_bytes

PREWARM_NICENESS = 10


def classify(error: Exception) -> dict:
    message = str(error)
    if isinstance(error, SectionNotFound):
        return {"code": "not_found", "message": message.strip("'\""), "retryable": False}
    if isinstance(error, ValueError):
        if "Projection is pending" in message:
            return {"code": "projection_pending", "message": message, "retryable": True}
        if "统一数据库不存在" in message:
            return {"code": "no_projection", "message": message, "retryable": True}
        if "limit exceeded" in message or "budget" in message:
            return {"code": "analysis_scope_too_large", "message": message, "retryable": False}
        return {"code": "invalid_request", "message": message, "retryable": False}
    return {"code": "analysis_failed", "message": f"{type(error).__name__}: {message}"[:500],
            "retryable": True}


class AnalysisWorker:
    def __init__(self, home: Path, io: WorkerIO, max_events: int | None = None):
        self.home = home
        self.io = io
        self.memo = ResultMemo()
        self.max_events = max_events
        self.niced = False

    def serve(self) -> None:
        self.io.start_heartbeat()
        self.io.send("ready", role="analysis", pid=os.getpid())
        for message in self.io.ops():
            if message.get("op") == "run":
                self.run(message["job"])
            elif message.get("op") == "shutdown":
                break

    def run(self, job: dict) -> None:
        from ..analytics.inputs import Scope
        from ..data_access.store import CanonicalStore

        self.io.current_job = job["id"]
        if job.get("priority") == "prewarm" and not self.niced:
            try:
                os.setpriority(os.PRIO_PROCESS, 0, PREWARM_NICENESS)
                self.niced = True
            except OSError:
                pass
        debug_delay()
        self.io.send("started", job=job["id"])
        started = time.perf_counter()
        try:
            scope = Scope(**job["scope"])
            store = CanonicalStore(self.home, max_events=self.max_events)
            # Size report first: the supervisor scales this task's time budget from it.
            self.io.send("sized", job=job["id"], events=estimate_events(store, scope))
            params = {**job.get("params", {}), "_rev": job.get("rev")}
            body = compute_section(job["section"], store, scope, params, self.memo)
            self.io.send("done", job=job["id"], status="completed", body=body,
                         duration_ms=round((time.perf_counter() - started) * 1000),
                         rss=peak_rss_bytes(), niced=self.niced)
        except Exception as error:
            if not isinstance(error, (ValueError, SectionNotFound)):
                traceback.print_exc()
            self.io.send("done", job=job["id"], status="failed", error=classify(error),
                         duration_ms=round((time.perf_counter() - started) * 1000),
                         rss=peak_rss_bytes(), niced=self.niced)
        finally:
            self.io.current_job = None


def main(home: Path) -> int:
    budget = os.environ.get("TANDEM_ANALYSIS_MAX_EVENTS")
    AnalysisWorker(home, WorkerIO("analysis"), int(budget) if budget else None).serve()
    return 0
