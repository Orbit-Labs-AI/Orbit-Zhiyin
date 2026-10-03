"""Analysis queue under frequent publishes and transient failures (v0.0.2 real-home storms).

- Live sync published a new data_rev every few minutes; every publish queued another
  generation of every prewarm task, and old generations still ran (the worker reads the
  current database, so they recomputed the new data under an old key).
- ``projection_pending`` was not a strike and the route answered ``Retry-After: 1``: each
  client retry started a new analysis run (849 failed runs in analysis.sqlite).
"""

from __future__ import annotations

from orbit_backend.services.routes_analytics import failure_error
from orbit_backend.services.snapshots import SnapshotStore
from orbit_backend.services.supervisor import AnalysisQueue, SupervisorConfig


def _queue(tmp_path, **overrides):
    published, sent = [], []
    queue = AnalysisQueue(tmp_path, SupervisorConfig(**overrides), SnapshotStore(None),
                          lambda *args: published.append(args), lambda *_: None)
    queue.worker.ensure = lambda: True  # No subprocess: drive the queue by messages.
    queue.worker.send = lambda message: sent.append(message) or True
    queue.worker.kill = lambda reason: None
    return queue, published, sent


def _busy(queue):
    """Occupy the worker so later submissions stay queued."""
    return queue.submit("tasks", {"busy": 1}, {}, "busy", "prewarm", (1, 0), "r")


def test_a_newer_revision_retargets_the_queued_task_instead_of_queueing_another(tmp_path):
    queue, _, sent = _queue(tmp_path)
    running = _busy(queue)
    first = queue.submit("uiview_facts", {"w": 7}, {}, "h7", "prewarm", (5, 0), "r")
    for rev in ((6, 0), (7, 0), (8, 1)):  # three more publishes while the worker is busy
        again = queue.submit("uiview_facts", {"w": 7}, {}, "h7", "prewarm", rev, "r")
        assert again is first
    assert [t.id for t in queue.pending] == [first.id]
    assert (first.data_rev, first.inventory_rev) == (8, 1)
    assert queue.tasks == {running.merge_key: running, first.merge_key: first}
    # An interactive request of the newest revision promotes the same task.
    assert queue.submit("uiview_facts", {"w": 7}, {}, "h7", "interactive", (8, 1), "r") is first
    assert first.priority == "interactive"
    queue._message({"t": "done", "job": running.id, "status": "completed", "body": {}})
    assert sent[-1]["job"]["id"] == first.id and sent[-1]["job"]["rev"] == 8
    assert len(sent) == 2  # one computation for four publishes


def test_a_running_older_revision_finishes_and_the_new_revision_queues_once(tmp_path):
    queue, _, _ = _queue(tmp_path)
    running = queue.submit("uiview_facts", {}, {}, "h", "prewarm", (5, 0), "r")
    assert queue.running is running
    newer = queue.submit("uiview_facts", {}, {}, "h", "prewarm", (6, 0), "r")
    assert newer is not running and queue.pending == [newer]
    assert queue.submit("uiview_facts", {}, {}, "h", "prewarm", (7, 0), "r") is newer
    assert queue.running is running and running.data_rev == 5 and newer.data_rev == 7


def test_other_scopes_and_sections_are_not_merged(tmp_path):
    queue, _, _ = _queue(tmp_path)
    _busy(queue)
    a = queue.submit("uiview_facts", {}, {}, "h7", "prewarm", (5, 0), "r")
    b = queue.submit("uiview_facts", {}, {}, "h30", "prewarm", (6, 0), "r")
    c = queue.submit("overview", {}, {}, "h7", "prewarm", (6, 0), "r")
    d = queue.submit("uiview_facts", {}, {}, "h7", "prewarm", (6, 0), "rules-2")
    assert len({a.id, b.id, c.id, d.id}) == 4 and a.data_rev == 5


def test_projection_pending_waits_before_running_the_same_key_again(tmp_path):
    queue, published, sent = _queue(tmp_path, transient_retry_s=30.0)
    task = queue.submit("uiview_facts", {}, {}, "h", "interactive", (5, 0), "r")
    queue._message({"t": "done", "job": task.id, "status": "failed",
                    "error": {"code": "projection_pending", "message": "Projection is pending",
                              "retryable": True}})
    assert task.status == "failed" and published[-1][1] == "analysis.failed"
    assert not queue.circuit_open("uiview_facts", "h", (5, 0))  # not a strike
    assert 29 < queue.cooling("uiview_facts", "h", (5, 0)) <= 30
    runs = len(sent)
    for _ in range(10):  # a client retrying every second
        assert queue.submit("uiview_facts", {}, {}, "h", "interactive", (5, 0), "r") is None
    assert len(sent) == runs
    # The route tells the client to wait as long as the queue does.
    error = failure_error(queue.failure("uiview_facts", "h", (5, 0))["error"])
    assert error.status == 503 and error.code == "projection_pending"
    assert error.headers() == {"Retry-After": "30"}
    # A new publication is a new revision: it runs at once.
    assert queue.submit("uiview_facts", {}, {}, "h", "interactive", (6, 0), "r") is not None
    assert len(sent) == runs + 1


def test_cooldown_expires_and_a_manual_recompute_clears_it(tmp_path):
    queue, _, sent = _queue(tmp_path, transient_retry_s=30.0)
    task = queue.submit("overview", {}, {}, "h", "interactive", (5, 0), "r")
    queue._message({"t": "done", "job": task.id, "status": "failed",
                    "error": {"code": "projection_pending", "retryable": True}})
    queue.failures[("overview", "h")]["retry_at"] -= 31  # time passes
    assert queue.cooling("overview", "h", (5, 0)) == 0
    again = queue.submit("overview", {}, {}, "h", "interactive", (5, 0), "r")
    assert again is not None and again is not task
    queue._message({"t": "done", "job": again.id, "status": "failed",
                    "error": {"code": "projection_pending", "retryable": True}})
    assert queue.submit("overview", {}, {}, "h", "interactive", (5, 0), "r") is None
    queue.clear_failures("overview", "h")  # POST /v1/analytics/recompute
    assert queue.submit("overview", {}, {}, "h", "interactive", (5, 0), "r") is not None


def test_a_real_failure_after_a_transient_one_counts_as_a_strike(tmp_path):
    queue, _, _ = _queue(tmp_path, transient_retry_s=0.0)
    task = queue.submit("overview", {}, {}, "h", "interactive", (5, 0), "r")
    queue._message({"t": "done", "job": task.id, "status": "failed",
                    "error": {"code": "projection_pending", "retryable": True}})
    task = queue.submit("overview", {}, {}, "h", "interactive", (5, 0), "r")
    queue._message({"t": "done", "job": task.id, "status": "failed",
                    "error": {"code": "analysis_failed", "retryable": True}})
    record = queue.failure("overview", "h", (5, 0))
    assert record["count"] == 1 and "retry_at" not in record
    assert queue.cooling("overview", "h", (5, 0)) == 0
