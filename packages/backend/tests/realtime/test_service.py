from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import NOW, Reads

from tandem_backend.realtime.service import Realtime, content_hash
from tandem_backend.services.auth import ApiError

T = NOW / 1000


class Recorder:
    def __init__(self, fail=False):
        self.notified, self.resolved, self.fail = [], [], fail

    def notify(self, event):
        self.notified.append(event)
        if self.fail:
            raise RuntimeError("boom")

    def resolve(self, key):
        self.resolved.append(key)


def make(tandem, recorder, paused=False):
    snoozes = []
    platform = SimpleNamespace(collection=SimpleNamespace(paused=paused),
                               notifier=SimpleNamespace(
                                   snooze=lambda s, scope: snoozes.append((s, scope))))
    gw = SimpleNamespace(reads=Reads(tandem.path), platform=platform, appdb=None)
    rt = Realtime(gw, clock=lambda: T, notify=recorder.notify, resolve=recorder.resolve)
    return rt, gw, snoozes


def seed_failing(tandem, uid="s1"):
    tandem.session(uid, started=NOW - 60_000, title="修复构建")
    tandem.event(uid, NOW - 50_000, actor="human")
    for i in range(3):
        tandem.call(uid, NOW - 40_000 + i * 1000, head="npm install", status="failed",
                    error_class="timeout")
    tandem.event(uid, NOW - 10_000, actor="tool")


def test_transition_notifies_once_and_resolves(tandem):
    seed_failing(tandem)
    recorder = Recorder()
    rt, _, _ = make(tandem, recorder)
    snap = rt.snapshot(now=T)
    assert snap["status"] == "active" and snap["counts"]["failing"] == 1
    item = snap["sessions"][0]
    assert item["state"] == "failing" and item["failure"]["cause_hint"] == "超时"
    assert [e["key"] for e in recorder.notified] == ["failing:s1"]
    event = recorder.notified[0]
    assert event["severity"] == "urgent" and event["title"] and "npm install" in event["body"]
    rt.snapshot(now=T + 2)
    assert len(recorder.notified) == 1 and recorder.resolved == []
    # A successful retry ends the loop; the session is still running.
    tandem.call("s1", NOW + 5_000, head="npm install", status="ok")
    tandem.event("s1", NOW + 6_000, actor="tool")
    rt.snapshot(now=T + 7)
    assert recorder.resolved == ["failing:s1"]
    assert len(recorder.notified) == 1


def test_just_finished_and_leaving_horizon(tandem):
    tandem.session("s2", started=NOW - 60_000)
    tandem.event("s2", NOW - 1_000, actor="assistant")
    recorder = Recorder()
    rt, _, _ = make(tandem, recorder)
    assert rt.snapshot(now=T)["sessions"][0]["state"] == "running"
    snap = rt.snapshot(now=T + 100)
    assert snap["sessions"][0]["state"] == "just_finished" and snap["status"] == "idle"
    assert [e["type"] for e in recorder.notified] == ["just_finished"]
    assert recorder.notified[0]["severity"] == "info"
    rt.snapshot(now=T + 1000)
    assert recorder.resolved == ["just_finished:s2"]


def test_paused_emits_nothing(tandem):
    seed_failing(tandem)
    recorder = Recorder()
    rt, _, _ = make(tandem, recorder, paused=True)
    snap = rt.snapshot(now=T)
    assert snap["status"] == "paused" and recorder.notified == []


def test_notifier_error_never_breaks_refresh(tandem):
    seed_failing(tandem)
    rt, _, _ = make(tandem, Recorder(fail=True))
    assert rt.snapshot(now=T)["counts"]["failing"] == 1


def test_missing_db_is_idle(tmp_path):
    reads = SimpleNamespace(read=lambda check=True: (_ for _ in ()).throw(
        ApiError(503, "no_projection", "none")))
    gw = SimpleNamespace(reads=reads, platform=None, appdb=None)
    snap = Realtime(gw, clock=lambda: T).snapshot(now=T)
    assert snap["status"] == "idle" and snap["sessions"] == []


def test_dismiss_hides_cards_and_snoozes(tandem):
    seed_failing(tandem)
    rt, _, snoozes = make(tandem, Recorder())
    rt.snapshot(now=T)
    result = rt.dismiss("s1", 600)
    assert result == {"session_uid": "s1", "until": NOW + 600_000}
    assert snoozes == [(600, "session:s1:failing"), (600, "session:s1:context_pressure")]
    item = rt.snapshot(now=T + 1)["sessions"][0]
    assert item["state"] == "failing" and "failing" not in item["flags"]
    assert item["dismissed_until"] == NOW + 600_000
    with pytest.raises(ApiError):
        rt.dismiss("nope")


def test_hash_ignores_generated_at_and_running_s(tandem):
    tandem.session("s3", started=NOW - 60_000)
    tandem.event("s3", NOW - 1_000, actor="tool")
    rt, _, _ = make(tandem, Recorder())
    a, b = rt.snapshot(now=T), rt.snapshot(now=T + 1)
    assert a["generated_at"] != b["generated_at"]
    assert a["sessions"][0]["running_s"] != b["sessions"][0]["running_s"]
    assert content_hash(a) == content_hash(b)


def test_density_and_lanes(tandem):
    tandem.session("s4", started=NOW - 600_000)
    for minutes in (0, 0, 3, 9, 15):
        tandem.event("s4", NOW - minutes * 60_000 - 1, actor="human")
    tandem.call("s4", NOW - 120_000, status="failed")
    rt, _, _ = make(tandem, Recorder())
    item = rt.snapshot(now=T, lanes=True)["sessions"][0]
    assert item["density"] == [1, 0, 0, 0, 0, 0, 1, 0, 0, 2]
    assert len(item["lanes"]["human"]) == 5 and len(item["lanes"]["error"]) == 1
    assert "lanes" not in rt.snapshot(now=T)["sessions"][0]
