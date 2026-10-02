"""Analysis time budgets scale with the scope's event count (synthetic sizes only)."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from types import SimpleNamespace

from tandem_backend.services.routes_analytics import failure_error
from tandem_backend.services.sections import estimate_events
from tandem_backend.services.snapshots import SnapshotStore
from tandem_backend.services.supervisor import AnalysisQueue, SupervisorConfig

REV = (1, 1)


def _queue(tmp_path, **overrides):
    published = []
    config = SupervisorConfig(**{"light_timeout_s": 20.0, "heavy_timeout_s": 120.0, **overrides})
    queue = AnalysisQueue(tmp_path, config, SnapshotStore(None),
                          lambda *args: published.append(args), lambda *_: None)
    queue.worker.ensure = lambda: True  # No subprocess: drive the queue by messages.
    queue.worker.send = lambda message: True
    return queue, published


def _run(queue, elapsed_s: float, events: int | None):
    task = queue.submit("overview", {}, {}, "h", "interactive", REV, "r")
    assert queue.running is task
    if events is not None:
        queue._message({"t": "sized", "job": task.id, "events": events})
    task.dispatched_at = time.monotonic() - elapsed_s
    queue.check()
    return task


def test_large_scope_gets_a_proportional_budget(tmp_path):
    # ~300 main sessions x 500 events: 25 s in is normal progress, not a stuck worker.
    queue, published = _queue(tmp_path)
    task = _run(queue, 25.0, 150_000)
    assert task.status == "running" and queue.running is task and not published
    assert queue.failure("overview", "h", REV) is None


def test_unsized_task_keeps_the_base_budget(tmp_path):
    queue, _ = _queue(tmp_path)
    task = _run(queue, 25.0, None)
    assert task.status == "failed" and task.error["code"] == "timeout"


def test_capped_budget_reports_scope_too_large(tmp_path):
    queue, published = _queue(tmp_path, max_budget_s=60.0)
    task = _run(queue, 61.0, 5_000_000)
    assert task.status == "failed"
    assert task.error["code"] == "analysis_scope_too_large"
    assert task.error["events"] == 5_000_000 and "narrow" in task.error["message"]
    assert published[-1][2]["code"] == "analysis_scope_too_large"
    error = failure_error(queue.failure("overview", "h", REV)["error"])
    assert error.status == 422 and error.code == "analysis_scope_too_large"


def test_estimate_events_counts_the_scoped_events():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE session (session_uid TEXT, source_id TEXT, project_id TEXT, root_uid TEXT);
        CREATE TABLE event (session_uid TEXT, ts INTEGER);""")
    db.executemany("INSERT INTO session VALUES (?,?,?,?)",
                   [("s1", "a", "p1", "s1"), ("s2", "a", "p2", "s2"), ("s3", "b", "p1", "s3")])
    db.executemany("INSERT INTO event VALUES (?,?)",
                   [(s, ts) for s in ("s1", "s2", "s3") for ts in (100, 200, 300)])

    @contextmanager
    def connect():
        yield db

    store = SimpleNamespace(connect=connect)

    def scope(**kw):
        base = dict(source_ids=None, project_ids=None, root_session_uids=None,
                    from_ts=None, until_ts=None)
        return SimpleNamespace(**{**base, **kw})

    assert estimate_events(store, scope()) == 9
    assert estimate_events(store, scope(source_ids=["a"])) == 6
    assert estimate_events(store, scope(source_ids=["a"], project_ids=["p1"])) == 3
    assert estimate_events(store, scope(from_ts=200, until_ts=300)) == 3
    assert estimate_events(store, scope(project_ids=[])) == 0
    assert estimate_events(SimpleNamespace(), scope()) is None
