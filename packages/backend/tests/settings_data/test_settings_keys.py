"""SET-05/SET-21/SET-24/OB-04/INIT-04: settings keys, ranges and their consumers."""

from __future__ import annotations

import os
import time

import pytest
from synthetic import write_codex_tree

from tandem_backend.services.gateway import default_scope, next_sync_interval
from tandem_backend.services.ingest_plan import plan_batches
from tandem_backend.services.jobs import AppState
from tandem_backend.services.worker_ingest import IngestWorker


@pytest.mark.parametrize("values", [
    {"default_range_days": 0}, {"default_range_days": 365}, {"sync_mode": "hour"},
    {"sync_mode": "off"}, {"sync_mode": "live"}, {"weekly_report": True},
    {"onboarding_step": 0}, {"onboarding_step": 4}, {"recent_days": None},
    {"recent_days": 90}, {"onboarded": True}])
def test_valid_settings_round_trip(client, values):
    response = client.patch("/v1/app/settings", json=values)
    assert response.status_code == 200, response.text
    for key, value in values.items():
        assert response.json()[key] == value
        assert client.get("/v1/status").json()["settings"][key] == value
        assert client.get("/v1/app/state").json()["settings"][key] == value


@pytest.mark.parametrize("values", [
    {"default_range_days": -1}, {"sync_mode": "manual"}, {"sync_mode": "always"},
    {"weekly_report": 1}, {"onboarding_step": 5}, {"onboarding_step": -1},
    {"onboarding_step": True}, {"recent_days": 0}, {"default_range_days": None},
    {"unknown": 1}])
def test_invalid_settings_rejected(client, values):
    assert client.patch("/v1/app/settings", json=values).status_code == 422


def test_defaults_include_new_keys(client):
    settings = client.get("/v1/status").json()["settings"]
    assert settings["weekly_report"] is False and settings["onboarding_step"] == 0
    assert "hour" in client.get("/v1/app/state").json()["capabilities"]["sync_modes"]


def test_hour_mode_uses_fixed_interval(gateway):
    bounds = gateway.sync_interval_s
    assert gateway.hourly_sync_s == 3600.0
    assert next_sync_interval("hour", 2.0, True, bounds) == 3600.0
    assert next_sync_interval("hour", 30.0, False, bounds) == 3600.0
    assert next_sync_interval("live", 2.0, True, bounds) == bounds[0]
    assert next_sync_interval("live", 20.0, False, bounds) == bounds[1]


def test_zero_range_is_all_time():
    assert default_scope(None)["from_ts"] is None


def test_recent_days_sets_import_plan(tmp_path):
    root = tmp_path / "agents" / "codex"
    root.mkdir(parents=True)
    state = AppState(tmp_path / "app-state.json")
    source = state.configure("codex", str(root), True, tmp_path / "home")
    job, _ = state.create_job("import", [source["id"]])
    assert job["plan"] == {"max_age_days": 90}
    state.transition(job["id"], "cancelled")
    state.update_settings({"recent_days": None})
    job, _ = state.create_job("import", [source["id"]])
    assert job["plan"] == {}
    state.transition(job["id"], "cancelled")
    job, _ = state.create_job("inventory", [source["id"]])
    assert job["plan"] == {}


def test_plan_batches_drops_old_files(tmp_path):
    now = time.time()
    root = tmp_path / "codex"
    files = write_codex_tree(root, 90, now=now, spacing_hours=12)  # 45 days of history.
    kept = [f for b in plan_batches("codex", root, now=now, max_age_days=10) for f in b.files]
    assert len(kept) == 20 and set(kept) == {f.resolve() for f in files[:20]}
    everything = [f for b in plan_batches("codex", root, now=now) for f in b.files]
    assert len(everything) == 90


def test_worker_full_phase_respects_age(tmp_path):
    root = tmp_path / "codex"
    files = write_codex_tree(root, 30, spacing_hours=24)
    source = {"id": "s", "agent": "codex", "root": str(root)}
    batches = IngestWorker._batches(None, {"phase": "full", "plan": {"max_age_days": 7}}, source)
    assert [b.phase for b in batches] == ["full"]
    assert {f.resolve() for f in files[:7]} == set(batches[0].files)
    assert IngestWorker._batches(None, {"phase": "full", "plan": {}}, source) == [None]
    for path in files:  # Everything older than the window: nothing to import.
        os.utime(path, (1, 1))
    assert IngestWorker._batches(None, {"phase": "full", "plan": {"max_age_days": 7}},
                                 source) == []
