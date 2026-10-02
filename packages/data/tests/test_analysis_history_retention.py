"""Retention of completed runs, stale-run cleanup and the run observer (analysis.sqlite)."""

from __future__ import annotations

import tandem_data.analysis_history as module
from tandem_data.analysis_history import AnalysisHistory


def _complete(history: AnalysisHistory, key: str, payload: str) -> str:
    run_id = history.start("features", {"k": key}, request_key=key, input_fp="fp")
    history.complete(run_id, {"analysis_digest": payload, "blob": payload * 1000})
    return run_id


def test_prune_keeps_newest_completed_runs_and_drops_their_orphan_snapshots(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    a = [_complete(history, "a", f"a{i}") for i in range(4)]
    b = [_complete(history, "b", f"b{i}") for i in range(2)]
    with history.connect() as db:  # deterministic order: later index = newer
        for index, run_id in enumerate([*a, *b]):
            db.execute("UPDATE analysis_run SET started_at=? WHERE run_id=?", (index, run_id))
    stats = history.prune(keep_runs_per_request=2, keep_runs=3)
    with history.connect() as db:
        runs = {r[0] for r in db.execute("SELECT run_id FROM analysis_run")}
        snapshots = db.execute("SELECT count(*) FROM analysis_snapshot").fetchone()[0]
    # Newest three overall are b1, b0, a3; a2 is within a's per-request limit but over the
    # overall limit.
    assert runs == {b[1], b[0], a[3]}
    assert stats["old_runs"] == 3 and stats["snapshots"] == 3 and snapshots == 3


def test_fail_stale_and_fail_runs_close_only_running_rows(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    old = history.start("features", {})
    fresh = history.start("features", {})
    done = _complete(history, "k", "x")
    with history.connect() as db:
        db.execute("UPDATE analysis_run SET started_at=0 WHERE run_id IN (?,?)", (old, done))
    assert history.fail_stale(older_than_ms=1000, reason="gateway restart") == 1
    assert history.get_run(old)["status"] == "failed"
    assert history.get_run(fresh)["status"] == "running"
    assert history.fail_runs([fresh, done], "worker killed") == 1
    assert history.get_run(fresh)["error_type"] == "WorkerTerminated"
    assert history.get_run(done)["status"] == "completed"


def test_run_observer_sees_start_and_finish(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(module, "RUN_OBSERVER", lambda run_id, active: seen.append(active))
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    _complete(history, "k", "x")
    failed = history.start("features", {})
    history.fail(failed, ValueError("boom"))
    assert seen == [True, False, True, False]


def test_vacuum_only_when_sparse(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    assert history.vacuum_if_sparse(min_bytes=0, ratio=0.99) is False
    assert history.file_bytes() > 0


def test_size_eviction_spares_the_protected_result(tmp_path):
    import os

    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    blob = os.urandom(200_000).hex()
    for index in range(3):
        history.put_sections(f"rk{index}", "fp", {"text": {"blob": blob}})
    stats = history.prune(max_bytes=1, protect=[("rk2", "fp")])
    with history.connect() as db:
        left = {r[0] for r in db.execute("SELECT request_key FROM analysis_section")}
    assert left == {"rk2"} and stats["evicted"] == 2
