"""Durable analysis runs are independently auditable and never overwrite prior results."""

import json
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files

import pytest

from tandem_data.analysis_history import AnalysisHistory
from tandem_data.schema_export import table_schemas


def test_repeated_runs_keep_individual_requests_and_full_deduplicated_snapshots(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    result = {
        "schema_version": "fixture-v1",
        "lexical": {"terms": [{"term": f"word{i}", "count": i} for i in range(150)]},
    }
    ids = [
        history.start("products", {"scope": "first"}),
        history.start("products", {"scope": "second"}),
    ]
    snapshots = [history.complete(uid, result) for uid in ids]
    assert snapshots[0] == snapshots[1]
    assert history.list_runs()["total"] == 2
    assert history.get_run(ids[0])["request"] == {"scope": "first"}
    assert history.result(ids[0]) == history.result(ids[1]) == result
    assert (
        history.records(ids[0], "/lexical/terms", offset=140, limit=10)["items"]
        == result["lexical"]["terms"][140:]
    )
    with history.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysis_snapshot").fetchone()[0] == 1
    with pytest.raises(ValueError, match="running"):
        history.complete(ids[0], {"changed": True})
    assert history.path.stat().st_mode & 0o077 == 0


def test_failed_running_and_corrupt_records_are_not_reported_as_completed(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    failed, running, complete = [history.start("features", {}) for _ in range(3)]
    history.fail(failed, ValueError("invalid scope"))
    history.complete(complete, {"value": 7})
    assert history.get_run(failed)["error_type"] == "ValueError"
    assert history.get_run(running)["status"] == "running"
    assert history.list_runs(status="completed")["total"] == 1
    with pytest.raises(KeyError):
        history.result(failed)
    with history.connect() as connection:
        connection.execute("UPDATE analysis_snapshot SET payload=?", (b"not a zlib snapshot",))
    with pytest.raises(ValueError, match="corrupt"):
        history.result(complete)


def test_threaded_runs_and_schema_export_are_consistent(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")

    def run(index):
        uid = history.start("products", {"index": index})
        history.complete(uid, {"index": index})
        return uid

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(run, range(12)))
    assert len(set(ids)) == 12 and history.list_runs(status="completed")["total"] == 12
    assert [history.result(uid)["index"] for uid in ids] == list(range(12))
    schema = json.loads(
        files("tandem_data").joinpath("schemas/analysis-history-v1.schema.json").read_text()
    )
    assert table_schemas("analysis") == schema
    assert set(schema["$defs"]) == {"analysis_run", "analysis_snapshot"}
