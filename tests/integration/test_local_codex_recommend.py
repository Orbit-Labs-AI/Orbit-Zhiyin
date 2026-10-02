"""Native fixture files exercise import, SQLite, analysis and Skill matching."""

import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    return importlib.import_module("evals.recommendation.local_codex")


def transcript(root, name="native-test", failures=3):
    path = root / "sessions" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "session_meta", "payload": {"id": name, "source": "cli", "cwd": "/fictional-project"}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
        {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "turn", "item": {
            "id": "user", "type": "UserMessage", "content": [{"type": "text", "text": "排查构造项目中的测试失败"}]}}},
    ]
    for i in range(10):
        rows.append({"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "turn", "item": {
            "id": f"command-{i}", "type": "CommandExecution", "command": ["pytest", f"case-{i}"],
            "status": "failed" if i < failures else "completed", "exit_code": 1 if i < failures else 0,
            "duration_ms": 10, "aggregated_output": "fictional command output"}}})
    for i, row in enumerate(rows):
        row["timestamp"] = f"2026-10-02T02:00:{i:02d}Z"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def test_native_files_reach_real_recommendation_with_unchanged_sources(tmp_path, runner):
    source, output = tmp_path / "codex", tmp_path / "result"
    path = transcript(source)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    summary = runner.run(source, output)
    assert (output / "data/tandem.db").is_file()
    assert summary["selected_files"] == summary["analyzed_main_sessions"] == 1
    assert summary["recommendation_count"] > 0
    result = json.loads((output / "recommendations.json").read_text())
    assert all(c["family"] == "skills" and c["evidence"] for c in result["recommendations"])
    assert any(c["rule_id"] == "tool_failures" for c in result["recommendations"])
    assert all(c["recommendation_status"] == "needs_context" for c in result["recommendations"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert (output / "analytics.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="fresh"):
        runner.run(source, output)


def test_no_bottleneck_does_not_fall_back_to_synthetic_activity(tmp_path, runner):
    source, output = tmp_path / "codex", tmp_path / "result"
    transcript(source, failures=0)
    summary = runner.run(source, output)
    assert summary["pipeline_status"] == "completed" and summary["recommendation_count"] == 0
    result = json.loads((output / "recommendations.json").read_text())
    assert not result["signals"] and not result["recommendations"]


def test_latest_selects_by_mtime_and_does_not_import_older_files(tmp_path, runner):
    source, output = tmp_path / "codex", tmp_path / "result"
    old = transcript(source, "old")
    new = transcript(source, "new")
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))
    summary = runner.run(source, output, latest=1)
    selection = json.loads((output / "selection.json").read_text())
    assert summary["selected_files"] == 1
    assert selection["selected_files"] == ["sessions/new.jsonl"]


def test_empty_sources_and_source_output_overlap_fail_before_writing(tmp_path, runner):
    source = tmp_path / "codex"
    source.mkdir()
    with pytest.raises(ValueError, match="No allowlisted"):
        runner.run(source, tmp_path / "empty")
    assert not (tmp_path / "empty").exists()
    with pytest.raises(ValueError, match="separate"):
        runner.run(source, source / "results")


def test_context_and_catalog_errors_do_not_ingest_local_files(tmp_path, runner):
    source = tmp_path / "codex"
    transcript(source)
    with pytest.raises(ValueError, match="agent=codex"):
        runner.run(source, tmp_path / "invalid", context={"agent": "generic"})
    empty = tmp_path / "catalog.json"
    empty.write_text(json.dumps({"schema_version": "recommendation-catalog-v1", "family": "skills", "items": []}))
    with pytest.raises(ValueError, match="no valid"):
        runner.run(source, tmp_path / "invalid", catalog=empty)
    assert not (tmp_path / "invalid").exists()


def test_live_append_between_indexing_and_projection_rescans_same_sample(tmp_path, runner):
    source, output = tmp_path / "codex", tmp_path / "result"
    path = transcript(source)
    rescans = []

    def progress(event):
        if event["stage"] == "normalize" and not rescans:
            row = json.loads(path.read_text().splitlines()[-1])
            row["payload"]["item"]["id"] = "appended-command"
            with path.open("a") as stream:
                stream.write(json.dumps(row) + "\n")
        if event["stage"] == "rescan":
            rescans.append(event)

    summary = runner.run(source, output, progress=progress)
    assert summary["selected_files"] == 1 and summary["recommendation_count"] > 0
    assert len(rescans) == 1
    assert json.loads((output / "import.json").read_text())["attempt"] == 2
    assert json.loads((output / "verify.json").read_text())["integrity"] == "ok"


def test_continuously_changing_source_fails_after_three_attempts(tmp_path, runner):
    source, output = tmp_path / "codex", tmp_path / "result"
    path = transcript(source)
    attempts = []

    def progress(event):
        if event["stage"] == "normalize":
            attempts.append(event)
            with path.open("a") as stream:
                stream.write('{"type":"event_msg","payload":{"type":"task_complete"}}\n')

    with pytest.raises(runner.SourceUnavailable, match="changed"):
        runner.run(source, output, progress=progress)
    assert len(attempts) == 3
    assert not (output / "analytics.json").exists()


def test_partial_source_verification_cannot_be_reported_as_success(tmp_path, runner, monkeypatch):
    source, output = tmp_path / "codex", tmp_path / "result"
    transcript(source)
    monkeypatch.setattr(runner.Store, "verify", lambda _: {
        "integrity": "partial", "unavailable_sources": [{"status": "missing"}]})
    with pytest.raises(RuntimeError, match="verification was incomplete"):
        runner.run(source, output)
    assert json.loads((output / "verify.json").read_text())["integrity"] == "partial"
    assert not (output / "recommendations.json").exists()
