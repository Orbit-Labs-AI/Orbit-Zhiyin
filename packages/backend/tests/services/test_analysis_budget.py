"""Analysis time budgets scale with the scope's event count (synthetic sizes only)."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from types import SimpleNamespace

from orbit_backend.services.routes_analytics import failure_error
from orbit_backend.services.sections import estimate_events
from orbit_backend.services.snapshots import SnapshotStore
from orbit_backend.services.supervisor import AnalysisQueue, SupervisorConfig

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
        CREATE TABLE event (session_uid TEXT, kind TEXT, ts INTEGER);""")
    db.executemany("INSERT INTO session VALUES (?,?,?,?)",
                   [("s1", "a", "p1", "s1"), ("s2", "a", "p2", "s2"), ("s3", "b", "p1", "s3")])
    db.executemany("INSERT INTO event VALUES (?,?,?)",
                   [(s, k, ts) for s in ("s1", "s2", "s3") for k, ts in
                    (("message.user", 100), ("tool.call", 200), ("message.user", 300))])

    @contextmanager
    def connect():
        yield db

    store = SimpleNamespace(connect=connect)

    def scope(**kw):
        base = dict(source_ids=None, project_ids=None, root_session_uids=None,
                    from_ts=None, until_ts=None)
        return SimpleNamespace(**{**base, **kw})

    assert estimate_events(store, scope()) == 9
    # Without project/root filters the count is an index-only upper bound (sources ignored).
    assert estimate_events(store, scope(source_ids=["a"])) == 9
    assert estimate_events(store, scope(from_ts=200, until_ts=300)) == 3
    assert estimate_events(store, scope(source_ids=["a"], from_ts=200)) == 6
    assert estimate_events(store, scope(source_ids=["a"], project_ids=["p1"])) == 3
    assert estimate_events(store, scope(project_ids=[])) == 0
    assert estimate_events(SimpleNamespace(), scope()) is None


def test_progress_reports_budget_attempts_and_last_error(tmp_path):
    queue, _ = _queue(tmp_path)
    task = _run(queue, 5.0, 100_000)
    info = queue.progress(task)
    assert info["status"] == "running" and info["attempt"] == 1 and info["events"] == 100_000
    assert info["budget_s"] == 80.0 and 4.5 < info["elapsed_s"] < 10
    assert queue.progress_of(task.id)["attempt"] == 1 and queue.progress_of("nope") is None


def test_timeouts_double_the_sized_budget_then_report_scope_too_large(tmp_path):
    queue, _ = _queue(tmp_path, max_budget_s=200.0)
    first = _run(queue, 81.0, 100_000)  # 20 + 60 s
    assert first.error["code"] == "timeout"
    second = _run(queue, 159.0, 100_000)  # doubled: 160 s
    assert second.status == "running"
    second.dispatched_at = time.monotonic() - 161.0
    queue.check()
    assert second.error["code"] == "timeout"
    third = _run(queue, 201.0, 100_000)  # 320 s wanted, capped at 200 s
    assert third.error["code"] == "analysis_scope_too_large"


def test_live_rss_over_the_kill_limit_fails_the_task(tmp_path):
    queue, published = _queue(tmp_path, rss_kill_bytes=1_000)
    killed = []
    queue.worker.kill = killed.append
    task = queue.submit("overview", {}, {}, "h", "interactive", REV, "r")
    queue._message({"t": "hb", "job": task.id, "rss": 999, "live": True})
    assert task.status == "running" and task.rss == 999
    queue._message({"t": "hb", "job": task.id, "rss": 5_000, "live": False})  # peak only
    assert task.status == "running"
    queue._message({"t": "hb", "job": task.id, "rss": 5_000, "live": True})
    assert task.status == "failed" and task.error["code"] == "analysis_scope_too_large"
    assert killed == ["rss_limit"] and published[-1][2]["code"] == "analysis_scope_too_large"


def test_runs_left_open_by_a_dead_worker_are_failed(tmp_path):
    from orbit_data.analysis_history import AnalysisHistory

    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    run_id = history.start("features", {})
    queue, _ = _queue(tmp_path)
    queue._message({"t": "run", "run_id": run_id, "active": True})
    queue._exit("timeout")
    run = history.get_run(run_id)
    assert run["status"] == "failed" and run["error_type"] == "WorkerTerminated"
    stale = history.start("features", {})
    with history.connect() as db:
        db.execute("UPDATE analysis_run SET started_at=0 WHERE run_id=?", (stale,))
    assert queue.fail_stale_runs() == 1
