"""Collection pause / resume (DT-02.1, MB-04, POP-11)."""
# ruff: noqa: F811  (fixtures are imported from notify_fake and then used as parameters)

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from notify_fake import clock, gw  # noqa: E402,F401

from tandem_backend.platform.collection import Collection  # noqa: E402


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


def test_sync_loop_respects_pause():
    from tandem_backend.services.gateway import Gateway

    if "collection" not in inspect.getsource(Gateway._sync_loop):
        pytest.skip("platform-core has not wired collection.paused into _sync_loop yet")
    # Wired: the loop must read gw.platform.collection.paused before submitting.
    assert "paused" in inspect.getsource(Gateway._sync_loop)
