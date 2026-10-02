from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from tandem_backend.platform.maintenance import INTERVALS, UnknownTask
from tandem_backend.services.snapshots import SnapshotKey


def runs(platform, task):
    with platform.appdb.read() as db:
        return db.execute("SELECT ok, detail FROM maintenance_run WHERE task=?",
                          (task,)).fetchall()


@pytest.mark.parametrize("task", ["metrics_flush", "wal_checkpoint", "optimize",
                                  "storage_report", "retention", "snapshot_compact",
                                  "integrity"])
def test_tasks_run_and_are_logged(started, task):
    if task == "snapshot_compact":
        started.gw.snapshots.put(SnapshotKey("s", "h", 1, 0, "r"), {"x": 1})
    result = started.maintenance.run(task)
    assert result["ok"], result
    assert runs(started, task)[0][0] == 1
    assert started.maintenance.status()[task]["last_run"] is not None


def test_storage_report_saved(started):
    started.maintenance.run("storage_report")
    from tandem_backend.platform.storage import latest_report

    report = latest_report(started.appdb)
    ids = [c["id"] for c in report["components"]]
    assert ids[:3] == ["tandem_db", "raw", "app_db"] and report["total_bytes"] > 0


def test_busy_runs_only_flush(started):
    started.gw.state.active = {"id": "j", "status": "running"}
    for task in INTERVALS:
        started.maintenance.last.pop(task, None)
    started.started_at = time.time() - 10 * 86_400
    assert started.maintenance.tick() == ["metrics_flush"]
    started.gw.state.active = None
    ran = started.maintenance.tick()
    assert "wal_checkpoint" in ran and "metrics_flush" not in ran


def test_unknown_task(started):
    with pytest.raises(UnknownTask):
        started.maintenance.run("nope")


def test_telemetry_export(started, tmp_path):
    out = tmp_path / "export"
    out.mkdir()
    started.settings.put_telemetry({"enabled": True, "export_dir": str(out)})
    started.refresh()
    day = (datetime.now(UTC) - timedelta(days=1)).date()
    ts = int(datetime(day.year, day.month, day.day, 5, tzinfo=UTC).timestamp() * 1000)
    with started.appdb.write() as db:
        db.execute("INSERT INTO metric_hour VALUES (?,?,?,?,?,?,?,?)",
                   (ts, "http.request", '{"route":"/a"}', 2, 3.0, 1.0, 2.0, None))
    result = started.maintenance.run("telemetry_export")
    assert result["ok"] and result["detail"]["rows"] == 1
    lines = (out / f"metrics-{day:%Y%m%d}.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["tags"] == {"route": "/a"}


def test_retention_prunes_logs(started):
    logs_dir = started.home / "logs"
    for i in range(3):
        (logs_dir / f"tandem.log.{i + 1}").write_bytes(b"x" * (9 * 1024 * 1024))
    detail = started.maintenance.run("retention")["detail"]
    assert detail["log_files"] >= 1
    assert sum(p.stat().st_size for p in logs_dir.iterdir()) <= 20 * 1024 * 1024


def test_install_sweep(started):
    from tandem_backend.install.service import InstallService

    assert started.maintenance.run("install_sweep")["detail"] == {"skipped": True}
    started.gw.install = InstallService(started.appdb, started.home)
    out = started.maintenance.run("install_sweep")
    assert out["ok"], out
    assert {k: out["detail"][k] for k in ("idle", "backups", "plans")} == {
        "idle": 0, "backups": 0, "plans": 0}


def test_retention_prunes_analysis_runs_and_refreshes_the_storage_report(started):
    from tandem_data.analysis_history import AnalysisHistory

    from tandem_backend.platform.storage import fresh_report, latest_report

    history = AnalysisHistory(started.home / "analysis.sqlite")
    for index in range(4):
        run_id = history.start("features", {}, request_key="k", input_fp="fp")
        history.complete(run_id, {"analysis_digest": str(index), "blob": "x" * 50_000})
    stale = fresh_report(started.appdb, started.home)
    result = started.maintenance.run("retention")
    assert result["ok"], result
    detail = result["detail"]["analysis"]
    assert detail["old_runs"] == 2 and detail["snapshots"] == 2 and detail["file_bytes"] > 0
    report = latest_report(started.appdb)
    analysis = next(c for c in report["components"] if c["id"] == "analysis")
    assert analysis["bytes"] > 0 and analysis["reclaimable_bytes"] >= 0
    assert report["generated_at"] >= stale["generated_at"]


def test_storage_endpoint_recomputes_an_old_report(started):
    from tandem_backend.platform.storage import fresh_report, save_report, storage_report

    old = storage_report(started.home)
    old["generated_at"] -= 3_600_000
    for component in old["components"]:
        component["bytes"] = 0
    save_report(started.appdb, old)
    report = fresh_report(started.appdb, started.home)
    assert report["generated_at"] > old["generated_at"] and report["total_bytes"] > 0
    assert fresh_report(started.appdb, started.home)["generated_at"] == report["generated_at"]
