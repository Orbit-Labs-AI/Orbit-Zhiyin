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
    assert set(schema["$defs"]) == {
        "analysis_run",
        "analysis_snapshot",
        "analysis_section",
        "analysis_row",
        "session_result",
        "session_exclusion",
    }


def _dead_pid() -> int:
    import subprocess
    import sys

    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_runs_of_killed_processes_are_failed_instead_of_running_forever(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    killed, legacy, live = [history.start("features", {"index": i}) for i in range(3)]
    with history.connect() as connection:
        connection.execute(
            "UPDATE analysis_run SET owner_pid=? WHERE run_id=?", (_dead_pid(), killed)
        )
        connection.execute("UPDATE analysis_run SET owner_pid=NULL WHERE run_id=?", (legacy,))
    history.start("features", {"index": 3})  # Any later start sweeps orphans.
    assert history.get_run(killed)["status"] == "failed"
    assert history.get_run(killed)["error_type"] == "Interrupted"
    assert history.get_run(legacy)["status"] == "failed"
    assert history.get_run(live)["status"] == "running"  # This process is still alive.


def test_reuse_serves_verified_identical_request(tmp_path):
    history = AnalysisHistory(tmp_path / "analysis.sqlite")
    history.complete(history.start("products", {"index": 7}), {"index": 7})
    assert history.reuse("products", {"index": 0}) is None
    run_id, result = history.reuse("products", {"index": 7})
    assert result == {"index": 7} and history.get_run(run_id)["status"] == "completed"
    assert history.result(run_id) == {"index": 7}


def test_version_one_history_is_migrated_in_place(tmp_path):
    import sqlite3

    path = tmp_path / "analysis.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        files("tandem_data").joinpath("migrations/analysis/001.sql").read_text()
        + "\nPRAGMA user_version=1;"
    )
    connection.execute(
        "INSERT INTO analysis_run(run_id,engine,status,started_at,request_json) "
        "VALUES('old','products','running',1,'{}')"
    )
    connection.commit()
    connection.close()
    history = AnalysisHistory(path)
    history.recover_interrupted()
    assert history.get_run("old")["status"] == "failed"
