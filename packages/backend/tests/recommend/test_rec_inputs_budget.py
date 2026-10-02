"""recommend_inputs on a scope too large for the heavy budget: no endless 202, budget grows.

Synthetic stand-in for a big home (1000+ sessions, 100k+ tool calls): a heavy section that
times out three times in a row must surface a retryable 503 instead of ``computing`` with
``job_id: null`` forever, and each timed-out retry gets a larger budget.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tandem_backend.recommend import inputs
from tandem_backend.services.auth import ApiError
from tandem_backend.services.snapshots import SnapshotStore
from tandem_backend.services.supervisor import AnalysisQueue, AnalysisTask, SupervisorConfig

REV = (7, 3)
SCOPE = {"from_ts": 1_780_000_000_000 - 7 * 86_400_000}


def _queue(tmp_path, **config) -> AnalysisQueue:
    snapshots = SnapshotStore(tmp_path / "ui.sqlite")
    return AnalysisQueue(tmp_path, SupervisorConfig(**config), snapshots,
                         lambda *a, **kw: None, lambda *a: None)


def _timeout(queue: AnalysisQueue, h: str) -> AnalysisTask:
    task = AnalysisTask("job", inputs.SECTION, SCOPE, {}, h, "interactive", *REV, "rules")
    queue._record_failure(task, {"code": "timeout", "message": "budget", "retryable": True})
    return task


def _gateway(tmp_path, queue: AnalysisQueue):
    revisions = SimpleNamespace(snapshot=lambda: {"data_rev": REV[0], "inventory_rev": REV[1]})
    return SimpleNamespace(revisions=revisions, snapshots=queue.snapshots,
                           supervisor=SimpleNamespace(analysis=queue))


def test_open_circuit_without_snapshot_is_503_not_endless_computing(tmp_path):
    from tandem_backend.services.snapshots import scope_hash

    queue = _queue(tmp_path)
    h = scope_hash(SCOPE, {})
    for _ in range(3):
        _timeout(queue, h)
    assert queue.circuit_open(inputs.SECTION, h, REV)
    with pytest.raises(ApiError) as caught:
        inputs.fetch(_gateway(tmp_path, queue), SCOPE)
    assert caught.value.status == 503 and caught.value.code == "analysis_unavailable"
    assert caught.value.retryable
    assert not queue.pending and queue.running is None  # no fourth attempt was queued


def test_heavy_budget_doubles_after_each_timeout_up_to_cap(tmp_path):
    queue = _queue(tmp_path, heavy_timeout_s=120.0, heavy_timeout_max_s=400.0)
    task = AnalysisTask("job", inputs.SECTION, SCOPE, {}, "h", "interactive", *REV, "rules")
    assert queue._timeout_for(task) == 120.0
    _timeout(queue, "h")
    assert queue._timeout_for(task) == 240.0
    _timeout(queue, "h")
    assert queue._timeout_for(task) == 400.0  # capped
    # A new data revision starts again from the base budget.
    fresh = AnalysisTask("job2", inputs.SECTION, SCOPE, {}, "h", "interactive", 8, 3, "rules")
    assert queue._timeout_for(fresh) == 120.0


def test_heavy_budget_is_configurable_from_env(monkeypatch):
    monkeypatch.setenv("TANDEM_ANALYSIS_HEAVY_TIMEOUT_S", "600")
    assert SupervisorConfig().heavy_timeout_s == 600.0
