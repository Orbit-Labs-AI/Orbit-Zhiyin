"""`/v1/eval` routes: suites, runs (EV-12) and the label precision summary (EV-02).

Runs execute on a single-worker executor owned by this router (never ``gw.jobs``), one
at a time; history lives in app.db (``evalrun.store``).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..evalrun import registry, runner
from ..evalrun import store as eval_store
from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway


class RunInProgress(ApiError):
    def __init__(self, run_id: str):
        super().__init__(409, "run_in_progress", "An evaluation run is already in progress")
        self.run_id = run_id

    def payload(self) -> dict:
        body = super().payload()
        body["error"]["run_id"] = self.run_id
        return body


class RunBody(BaseModel):
    suites: list[str] | Literal["all"] = "all"
    fail_under: float | None = Field(None, ge=0, le=1)
    params: dict = Field(default_factory=dict)


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tandem-eval")
    lock = threading.Lock()
    active: dict[str, str | None] = {"run_id": None}

    def work(run_id: str, body: RunBody, suites: list[str]) -> None:
        try:
            runner.run(suites, fail_under=body.fail_under, params=body.params, home=gw.home,
                       store=gw.appdb, run_id=run_id)
        except Exception as exc:  # The runner already marked the row failed when it could.
            eval_store.fail(gw.appdb, run_id, f"{type(exc).__name__}: {exc}",
                            int(time.time() * 1000))
        finally:
            with lock:
                active["run_id"] = None

    @api.get("/v1/eval/suites")
    def suites():
        return {"suites": registry.list_suites()}

    @api.post("/v1/eval/runs", status_code=202)
    def start(body: RunBody):
        try:
            selected = runner.resolve(body.suites)
        except ValueError as exc:
            raise ApiError(422, "unknown_suite", str(exc)) from None
        with lock:
            current = active["run_id"]
            # The worker clears ``active`` just after writing the final status; a client that
            # polled "done" and posts again at once must not see a stale 409.
            if current and (eval_store.get_run(gw.appdb, current) or {}).get("status") not in (
                    "done", "failed", "cancelled"):
                raise RunInProgress(current)
            run_id = runner.new_run_id()
            eval_store.queue(gw.appdb, run_id, selected, body.fail_under, body.params,
                             int(time.time() * 1000))
            active["run_id"] = run_id
        executor.submit(work, run_id, body, selected)
        return {"run_id": run_id, "status": "queued"}

    @api.get("/v1/eval/runs")
    def runs(limit: int = Query(20, ge=1, le=200)):
        return {"runs": eval_store.list_runs(gw.appdb, limit)}

    @api.get("/v1/eval/runs/{run_id}")
    def run_report(run_id: str):
        report = eval_store.get_run(gw.appdb, run_id)
        if report is None:
            raise ApiError(404, "not_found", f"Unknown eval run {run_id}")
        return report

    return api
