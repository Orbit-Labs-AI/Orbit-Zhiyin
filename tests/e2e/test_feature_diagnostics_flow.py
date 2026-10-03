"""Read-only recorded-window selection and an explicit local diagnostic run."""

import hashlib
import json
import runpy
import sqlite3
from pathlib import Path

import pytest

from orbit_backend.cli import demo_home
from orbit_backend.data_access.ingest import ingest

RUNNER = Path(__file__).resolve().parents[2] / "evals/analytics/local_diagnostics.py"


def test_recorded_window_uses_latest_event_and_rejects_empty_or_missing_database(tmp_path):
    runner = runpy.run_path(str(RUNNER))
    with pytest.raises(ValueError, match="existing canonical"):
        runner["snapshot_scope"](tmp_path)
    database = tmp_path / "orbit.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE event (ts INTEGER)")
        with pytest.raises(ValueError, match="No timestamped"):
            runner["snapshot_scope"](tmp_path)
        connection.executemany("INSERT INTO event VALUES (?)", [(100,), (900000000,)])
    scope = runner["snapshot_scope"](tmp_path)
    assert scope.until_ts == 900000001
    assert scope.from_ts == 900000001 - 7 * 86400000
    assert runner["snapshot_scope"](tmp_path, from_ts=100, until_ts=200).until_ts == 200
    with pytest.raises(ValueError):
        runner["snapshot_scope"](tmp_path, from_ts=200, until_ts=100)


def test_explicit_catalog_must_not_fall_back_or_create_a_partial_run(tmp_path):
    runner = runpy.run_path(str(RUNNER))
    runner["run"].__globals__["ROOT"] = tmp_path
    catalog, output = tmp_path / "skills.json", tmp_path / ".local/result"
    catalog.write_text(
        json.dumps({"schema_version": "recommendation-catalog-v1", "family": "skills"})
    )
    with pytest.raises(ValueError, match="explicit items list"):
        runner["run"](tmp_path / "home", output, catalog, None)
    assert not output.exists()
    with pytest.raises(ValueError, match="ignored .local"):
        runner["run"](tmp_path / "home", tmp_path / "public", catalog, None)


def test_snapshot_to_grouped_report_uses_zero_model_calls_and_leaves_source_untouched(tmp_path):
    runner = runpy.run_path(str(RUNNER))
    runner["run"].__globals__["ROOT"] = tmp_path
    source, home = demo_home(tmp_path / "source"), tmp_path / "data"
    logs = list(source.rglob("*.jsonl"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in logs}
    ingest(home, "codex", source)
    catalog = tmp_path / "skills.json"
    catalog.write_text(
        json.dumps({"schema_version": "recommendation-catalog-v1", "family": "skills", "items": []})
    )
    output = tmp_path / ".local/result"
    report = runner["run"](home, output, catalog, runner["snapshot_scope"](home))
    assert len(report["families"]) == 8
    assert report["run"]["model_calls"] == 0 and report["run"]["source_rescan"] is False
    assert report["skills"]["items"] == []
    assert json.loads((output / "recommendations.json").read_text())["recommendations"] == []
    assert (output / "terminal.txt").read_text().startswith("八个特征族")
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in logs} == before
    with pytest.raises(FileExistsError):
        runner["run"](home, output, catalog, runner["snapshot_scope"](home))
