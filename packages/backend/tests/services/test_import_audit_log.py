"""Durable import diagnostics survive SSE coalescing without recording source bodies."""

from types import SimpleNamespace

from orbit_backend.services.import_progress import detail
from orbit_backend.services.jobs import AppState, JobService


def test_file_logs_precede_coalescing_and_unchanged_files_are_summarized(tmp_path, monkeypatch):
    entries, frames = [], []
    monkeypatch.setattr("orbit_backend.services.jobs.log_event",
                        lambda event, **fields: entries.append({"event": event, **fields}))
    state = AppState(tmp_path / "app-state.json")
    root = tmp_path / "codex"
    root.mkdir()
    source = state.configure("codex", str(root), True, tmp_path / "home")
    service = JobService(state, SimpleNamespace(start=lambda *_: None, cancel=lambda *_: None),
                         lambda *args: frames.append(args), progress_interval_s=60)
    job = service.submit("import", [source["id"]], phase="full")
    service.started(job["id"])
    frames.clear()
    for index, status in enumerate(["captured", "captured", "unchanged", "failed"]):
        service.progress(job["id"], {"stage": "capture", "completed": index + 1, "total": 10,
                                    "path": f"sessions/{index}.jsonl", "status": status,
                                    "attempts": 1, "text": "PRIVATE SYNTHETIC BODY"})
    assert len(frames) == 1
    assert [entry["status"] for entry in entries if entry["event"] == "import_file"] == [
        "captured", "captured", "failed"]
    service.progress(job["id"], {"stage": "capture_retry", "attempt": 2,
                                "source_status": "changed", "path": "sessions/retry.jsonl"})
    service.finished(job["id"], "partial", [], None)
    summary = next(entry for entry in entries if entry["event"] == "import_summary")
    assert {key: summary[key] for key in ("captured", "unchanged", "failed", "retries")} == {
        "captured": 2, "unchanged": 1, "failed": 1, "retries": 1}
    assert "PRIVATE SYNTHETIC BODY" not in str(entries)
    assert job["id"] not in service.progress_counts


def test_capture_retry_explains_actual_reason():
    frame = {"stage": "capture_retry", "attempt": 2}
    assert "读取时变化" in detail({**frame, "source_status": "changed"})
    assert "数据库暂时被锁定" in detail({**frame, "sqlite_errorname": "SQLITE_BUSY"})
    assert "I/O 错误" in detail({**frame, "errno": 11})
