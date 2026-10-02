"""Shell producers: weekly schedule, new-source watch, first-analysis watcher and their
registration on the maintenance thread."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from synthetic import write_codex_tree

from tandem_backend.services.sections import rules_digest
from tandem_backend.services.snapshots import SnapshotKey, scope_hash
from tandem_backend.shell import default_scope, tasks
from tandem_backend.shell.producers import AnalysisWatcher

TZ = timezone(timedelta(hours=8))


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)  # 2026-10-05 is a Monday


def test_weekly_due():
    assert at(4, 20).isoweekday() == 7 and at(5, 9).isoweekday() == 1
    # Sunday: this ISO week's Monday 09:00 has passed.
    assert tasks.weekly_due(at(4, 20), None) == "2026-W40"
    assert tasks.weekly_due(at(4, 20), "2026-W40") is None  # already ran this week
    # Monday 08:59 is too early, even when last week never ran; 09:00 is due.
    assert tasks.weekly_due(at(5, 8, 59), "2026-W39") is None
    assert tasks.weekly_due(at(5, 9, 0), "2026-W40") == "2026-W41"
    # A missed week runs on the next check (here Wednesday, two weeks later).
    assert tasks.weekly_due(at(14, 11), "2026-W40") == "2026-W42"
    assert tasks.weekly_due(at(14, 11), "2026-W42") is None


def notes(client, kind=None):
    query = f"&type={kind}" if kind else ""
    return client.get(f"/v1/notifications?state=all{query}").json()["items"]


def test_weekly_report_skips_without_export_or_when_disabled(gateway_factory, monkeypatch):
    # Every call passes an explicit local time, and the export package is forced absent:
    # with the real one merged, an enabled run would freeze W41 and later calls in this
    # test would see an already-run week (the real export path is covered by the stand-in
    # test below).
    monkeypatch.setattr(tasks, "_export", lambda: None)
    _, gw = gateway_factory(started=False)
    monday = at(5, 10)
    with gw.state.lock:
        gw.state.state["settings"]["weekly_report"] = True  # Default is off.
    assert tasks.weekly_report(gw, at(5, 8)) == {"skipped": "not_due"}
    assert tasks.weekly_report(gw, monday) == {"skipped": "export_unavailable",
                                               "week": "2026-W41"}
    with gw.state.lock:
        gw.state.state["settings"]["weekly_report"] = False
    assert tasks.weekly_report(gw, monday) == {"skipped": "disabled", "week": "2026-W41"}
    # Disabled wins over the schedule: before Monday 09:00 it still says why it is idle.
    assert tasks.weekly_report(gw, at(5, 8)) == {"skipped": "disabled"}
    assert tasks.last_weekly_key(gw) is None  # nothing was frozen or notified


def test_source_watch_notifies_new_roots_once(gateway_factory, tmp_path):
    root = tmp_path / "agents" / "codex"
    write_codex_tree(root, 3)
    empty = tmp_path / "agents" / "empty"
    empty.mkdir(parents=True)
    found = [{"agent": "codex", "root": str(root)}, {"agent": "codex", "root": str(empty)}]
    client, gw = gateway_factory(discovery=lambda: found)
    assert {"source_watch", "weekly_report"} <= set(gw.platform.maintenance.tasks)
    run = client.post("/v1/platform/maintenance/run", json={"task": "source_watch"}).json()
    assert run["ok"] and run["detail"]["new"] == [{"agent": "codex", "root": str(root),
                                                   "files": 3}]
    (item,) = notes(client, "new_source")
    assert item["title"] == "发现新的数据来源" and item["state"] == "delivered"
    assert item["payload"] == {"agent": "codex", "root": str(root), "files": 3}
    assert tasks.source_watch(gw)["new"] == []  # once per root, ever
    assert len(notes(client, "new_source")) == 1
    status = client.get("/v1/platform/maintenance").json()
    assert status["weekly_report"]["interval_s"] == 3600


def test_configured_root_is_not_new(gateway_factory, tmp_path):
    root = tmp_path / "agents" / "codex"
    write_codex_tree(root, 2)
    client, gw = gateway_factory(discovery=lambda: [{"agent": "codex", "root": str(root)}])
    client.post("/v1/app/sources", json={"agent": "codex", "root": str(root), "enabled": False})
    assert tasks.source_watch(gw)["new"] == []


def test_analysis_watcher_fires_once(gateway_factory):
    client, gw = gateway_factory()
    watcher = gw.shell_watcher
    assert watcher.observe in gw.platform.observers
    assert watcher.check() == []  # nothing published yet
    gw.revisions.update(data_rev=3, inventory_rev=0)
    assert watcher.check() == []  # published, overview not computed yet
    scope = default_scope(gw, 30)
    key = SnapshotKey("overview", scope_hash(scope, {}), 3, 0, rules_digest())
    gw.snapshots.put(key, {"overview": {"counts": {"main_sessions": 12}}})
    assert watcher.check() == ["analysis_ready"]
    (item,) = [n for n in notes(client, "system") if n["title"] == "首次分析完成"]
    assert item["payload"]["sessions"] == 12
    assert watcher.check() == []  # never twice


def test_watcher_tap_ignores_unrelated_frames(gateway_factory):
    _, gw = gateway_factory(started=False)
    watcher = AnalysisWatcher(gw)
    kicked = []
    watcher.kick = lambda: kicked.append(1)
    watcher.observe("analysis", "analysis.ready", {"section": "text"})
    watcher.observe("job", "job.updated", {"kind": "inventory", "status": "completed"})
    assert kicked == []
    watcher.observe("analysis", "analysis.ready", {"section": "overview"})
    watcher.observe("job", "job.updated", {"kind": "import", "status": "completed"})
    assert kicked == [1, 1]


def test_weekly_report_with_export_stand_in(gateway_factory, monkeypatch):
    from types import SimpleNamespace

    client, gw = gateway_factory()
    with gw.state.lock:
        gw.state.state["settings"]["weekly_report"] = True  # Default is off.
    saved = []
    report = SimpleNamespace(
        DEFAULT_SECTIONS=("overview", "metrics", "persona"), SECTION_IDS=("overview", "metrics"),
        build_scope=lambda raw: dict(raw),
        assemble=lambda gw_, sections, scope: {"scope_hash": "h", "sections": sections,
                                               "scope": scope})
    snapshots = SimpleNamespace(KINDS=("report", "weekly"),
                                save=lambda appdb, kind, scope, h, payload, rules:
                                saved.append((kind, scope, payload)) or "snap-1")
    monkeypatch.setattr(tasks, "_export", lambda: (report, snapshots))
    result = tasks.weekly_report(gw, at(7, 10))  # Wednesday of 2026-W41
    assert result == {"week": "2026-W41", "snapshot_id": "snap-1", "kind": "weekly"}
    kind, scope, payload = saved[0]
    assert payload["sections"] == ["overview", "metrics"]
    # Last full week: Monday 2026-09-28 00:00 → Monday 2026-10-05 00:00 local.
    assert scope["until_ts"] - scope["from_ts"] == 7 * 86_400_000
    assert scope["until_ts"] == int(at(5, 0).timestamp() * 1000)
    (item,) = notes(client, "weekly")
    assert item["payload"] == {"snapshot_id": "snap-1", "week": "2026-W41"}
    assert tasks.weekly_report(gw, at(8, 10)) == {"skipped": "not_due"}
    assert tasks.weekly_due(at(12, 9), tasks.last_weekly_key(gw)) == "2026-W42"
    with gw.state.lock:
        gw.state.state["settings"]["weekly_report"] = False
    assert tasks.weekly_report(gw, at(8, 10)) == {"skipped": "disabled"}  # W41 already ran
