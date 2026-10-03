"""Collection pause / resume (DT-02.1, MB-04, POP-11)."""
# ruff: noqa: F811  (fixtures are imported from notify_fake and then used as parameters)

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from notify_fake import clock, gw  # noqa: E402,F401

from orbit_backend.platform.collection import Collection  # noqa: E402


def enable_sources(gw, *ids):
    with gw.state.lock:
        for key in ids:
            gw.state.state["sources"][key] = {"agent": "codex", "root": "/tmp/x", "enabled": True}
        gw.state.state["sources"]["off"] = {"agent": "codex", "root": "/tmp/y", "enabled": False}


def test_pause_is_idempotent_and_survives_restart(gw, clock):
    c = Collection(gw, clock=clock)
    assert not c.paused
    first = c.pause("user")
    clock.tick(5)
    second = c.pause("other")
    assert first["paused"] and second["since"] == first["since"] and second["reason"] == "user"
    assert len(c.intervals()) == 1
    restarted = Collection(gw, clock=clock)
    assert restarted.paused and restarted.since == first["since"]
    frames, _ = gw.bus.since(0, {"service"})
    assert [f.data["state"] for f in frames] == ["paused"]


def test_resume_submits_catch_up_import(gw, clock):
    enable_sources(gw, "codex:a", "claude:b")
    c = Collection(gw, clock=clock)
    c.pause()
    clock.tick(90)
    out = c.resume()
    assert out["paused"] is False and out["paused_ms"] == 90_000
    assert out["catch_up_job_id"] == "job-1" and out["catch_up_pending"] is False
    assert gw.jobs.calls == [("import", ["codex:a", "claude:b"], "full", "sync")]
    assert c.resume()["catch_up_job_id"] is None  # Idempotent: nothing more submitted.
    assert len(gw.jobs.calls) == 1
    interval = c.intervals()[0]
    assert interval["ended_at"] - interval["started_at"] == 90_000
    frames, _ = gw.bus.since(0, {"service"})
    assert [f.data["state"] for f in frames] == ["paused", "resumed", "running"]
    assert Collection(gw, clock=clock).paused is False


def test_conflict_sets_catch_up_pending(gw, clock):
    enable_sources(gw, "codex:a")
    gw.jobs.conflict = True
    c = Collection(gw, clock=clock)
    c.pause()
    out = c.resume()
    assert out["catch_up_pending"] is True and out["catch_up_job_id"] is None
    assert c.status()["catch_up_pending"] is True
    assert c.consume_catch_up() is True and c.consume_catch_up() is False


def test_resume_without_sources_submits_nothing(gw, clock):
    c = Collection(gw, clock=clock)
    c.pause()
    assert c.resume()["catch_up_job_id"] is None and gw.jobs.calls == []


def test_paused_ms_today_and_prune(gw, clock):
    c = Collection(gw, clock=clock)
    for _ in range(205):
        c.pause()
        clock.tick(1)
        c.resume()
    assert c.status()["paused_ms_today"] > 0
    c.pause()
    assert c.prune() == 5
    assert len(c.intervals(200)) == 200 and c.intervals(1)[0]["ended_at"] is None
    with gw.appdb.read() as db:
        assert db.execute("SELECT COUNT(*) FROM collection_pause").fetchone()[0] == 201


class Stopper:
    """``stopping`` stand-in: lets the sync loop run ``rounds`` iterations."""

    def __init__(self, rounds: int):
        self.rounds = rounds

    def wait(self, _interval: float) -> bool:
        self.rounds -= 1
        return self.rounds < 0

    def is_set(self) -> bool:
        return self.rounds < 0


def run_sync_loop(gw, rounds: int) -> None:
    from orbit_backend.services.gateway import Gateway

    gw.stopping, gw.sync_interval_s = Stopper(rounds), (0.0, 0.0)
    Gateway._sync_loop(gw)


def test_sync_loop_respects_pause(gw, clock):
    enable_sources(gw, "a")
    gw.state.update_settings({"sync_mode": "live"})
    gw.platform.collection = c = Collection(gw, clock=clock)
    c.pause()
    run_sync_loop(gw, 3)
    assert gw.jobs.calls == []  # Paused: no origin='sync' import.
    c.resume()
    run_sync_loop(gw, 1)
    assert [call[3] for call in gw.jobs.calls] == ["sync", "sync"]  # catch-up + live poll


def test_sync_loop_retries_catch_up_until_submitted(gw, clock):
    enable_sources(gw, "a")  # sync_mode is not live: only the catch-up submits.
    gw.platform.collection = c = Collection(gw, clock=clock)
    gw.jobs.conflict = True
    c.pause()
    c.resume()
    run_sync_loop(gw, 2)
    assert c.catch_up_pending and gw.jobs.calls == []
    gw.jobs.conflict = False
    run_sync_loop(gw, 3)
    assert not c.catch_up_pending and gw.jobs.calls == [("import", ["a"], "full", "sync")]


def test_sync_loop_survives_an_unexpected_error_and_logs_it(gw, clock, monkeypatch):
    from orbit_backend.services import gateway as gateway_module

    enable_sources(gw, "a")
    gw.state.update_settings({"sync_mode": "live"})
    gw.platform.collection = c = Collection(gw, clock=clock)
    logged = []
    monkeypatch.setattr(gateway_module.logs, "log_event", lambda ev, level, **f: logged.append((ev, f)))
    real = c.consume_catch_up
    failures = iter([KeyError("boom")])

    def flaky():
        error = next(failures, None)
        if error:
            raise error
        return real()

    c.consume_catch_up = flaky
    run_sync_loop(gw, 2)  # round 1 raises, round 2 still submits
    assert [ev for ev, _ in logged] == ["sync_loop_error"] and "KeyError" in logged[0][1]["error"]
    assert [call[3] for call in gw.jobs.calls] == ["sync"]


def test_latest_job_returns_only_the_newest_of_an_origin(gw):
    with gw.state.lock:
        gw.state.state["jobs"] = {
            "j1": {"id": "j1", "origin": "sync", "created_at": 1, "results": [{"changed": True}]},
            "j2": {"id": "j2", "origin": "user", "created_at": 3},
            "j3": {"id": "j3", "origin": "sync", "created_at": 2, "results": []},
        }
    newest = gw.state.latest_job("sync")
    assert newest["id"] == "j3"
    newest["results"].append("mutated")  # a copy: state untouched
    assert gw.state.state["jobs"]["j3"]["results"] == []
    assert gw.state.latest_job("nope") is None


def test_failed_resume_dispatch_retries_in_manual_mode_with_backoff(gw, clock, monkeypatch):
    import threading
    from types import SimpleNamespace

    from orbit_backend.services import gateway
    from orbit_backend.services.jobs import JobService

    enable_sources(gw, "a")
    gw.state.update_settings({"sync_mode": "off"})
    attempts = []

    def unavailable(*_):
        attempts.append(1)
        raise RuntimeError("synthetic worker unavailable")

    runner = SimpleNamespace(start=unavailable, cancel=lambda *_: None)
    gw.jobs = JobService(gw.state, runner, lambda *_: None)
    gw.stopping, gw.sync_interval_s = threading.Event(), (2.0, 30.0)
    c = Collection(gw, clock=clock)
    c.pause()
    out = c.resume()
    assert out["catch_up_job_id"] is None and out["catch_up_pending"]
    assert gw.state.latest_job("sync")["status"] == "failed"
    assert gateway._sync_round(gw, c, 2.0) > 0
    assert len(attempts) == 1  # Failure does not create a tight dispatch loop.

    # A retry that also fails must not consume the pending intent.
    failed_at = gw.state.latest_job("sync")["finished_at"]
    monkeypatch.setattr(gateway.time, "time", lambda: failed_at / 1000 + 31)
    gateway._sync_round(gw, c, 2.0)
    assert len(attempts) == 2 and c.catch_up_pending

    # Once the worker returns, the same explicit catch-up runs with sync still off.
    next_at = gw.state.latest_job("sync")["finished_at"]
    monkeypatch.setattr(gateway.time, "time", lambda: next_at / 1000 + 31)
    runner.start = lambda *_: attempts.append(1)
    gateway._sync_round(gw, c, 2.0)
    assert len(attempts) == 3 and not c.catch_up_pending
    assert gw.state.latest_job("sync")["status"] == "queued"


def test_latest_job_timestamp_ties_use_persisted_insertion_order(tmp_path, monkeypatch):
    from orbit_backend.services import jobs

    monkeypatch.setattr(jobs, "now_ms", lambda: 123456)
    state = jobs.AppState(tmp_path / "app-state.json")
    first, _ = state.create_job("verify", origin="sync")
    state.transition(first["id"], "failed")
    second, _ = state.create_job("verify", origin="sync")
    assert first["created_at"] == second["created_at"]
    assert state.latest_job("sync")["id"] == second["id"]
    assert state.latest_job("sync")["status"] == "queued"
    assert [job["id"] for job in state.jobs()] == [second["id"], first["id"]]

    # Serialization and restart must retain the same tie order, not UUID order.
    restored = jobs.AppState(state.path)
    assert restored.latest_job("sync")["id"] == second["id"]
    assert [job["id"] for job in restored.jobs()] == [second["id"], first["id"]]
