from __future__ import annotations

from types import SimpleNamespace

import pytest
from realtime_fixtures import NOW, Reads

from orbit_backend.realtime.service import Realtime, content_hash
from orbit_backend.services.auth import ApiError

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


def make(orbit, recorder, paused=False):
    snoozes = []
    platform = SimpleNamespace(collection=SimpleNamespace(paused=paused),
                               notifier=SimpleNamespace(
                                   snooze=lambda s, scope: snoozes.append((s, scope))))
    gw = SimpleNamespace(reads=Reads(orbit.path), platform=platform, appdb=None)
    rt = Realtime(gw, clock=lambda: T, notify=recorder.notify, resolve=recorder.resolve)
    return rt, gw, snoozes


def seed_failing(orbit, uid="s1"):
    orbit.session(uid, started=NOW - 60_000, title="修复构建")
    orbit.event(uid, NOW - 50_000, actor="human")
    for i in range(3):
        orbit.call(uid, NOW - 40_000 + i * 1000, head="npm install", status="failed",
                    error_class="timeout")
    orbit.event(uid, NOW - 10_000, actor="tool")


def test_transition_notifies_once_and_resolves(orbit):
    seed_failing(orbit)
    recorder = Recorder()
    rt, _, _ = make(orbit, recorder)
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
    orbit.call("s1", NOW + 5_000, head="npm install", status="ok")
    orbit.event("s1", NOW + 6_000, actor="tool")
    rt.snapshot(now=T + 7)
    assert recorder.resolved == ["failing:s1"]
    assert len(recorder.notified) == 1


def test_just_finished_and_leaving_horizon(orbit):
    orbit.session("s2", started=NOW - 20 * 60_000)  # >= min_run_s (600 s)
    orbit.event("s2", NOW - 1_000, actor="assistant")
    recorder = Recorder()
    rt, _, _ = make(orbit, recorder)
    assert rt.snapshot(now=T)["sessions"][0]["state"] == "running"
    snap = rt.snapshot(now=T + 100)
    assert snap["sessions"][0]["state"] == "just_finished" and snap["status"] == "idle"
    assert [e["type"] for e in recorder.notified] == ["just_finished"]
    assert recorder.notified[0]["severity"] == "info"
    rt.snapshot(now=T + 1000)
    assert recorder.resolved == ["just_finished:s2"]


def test_paused_emits_nothing(orbit):
    seed_failing(orbit)
    recorder = Recorder()
    rt, _, _ = make(orbit, recorder, paused=True)
    snap = rt.snapshot(now=T)
    assert snap["status"] == "paused" and recorder.notified == []


def test_notifier_error_never_breaks_refresh(orbit):
    seed_failing(orbit)
    rt, _, _ = make(orbit, Recorder(fail=True))
    assert rt.snapshot(now=T)["counts"]["failing"] == 1


def test_missing_db_is_idle(tmp_path):
    reads = SimpleNamespace(read=lambda check=True: (_ for _ in ()).throw(
        ApiError(503, "no_projection", "none")))
    gw = SimpleNamespace(reads=reads, platform=None, appdb=None)
    snap = Realtime(gw, clock=lambda: T).snapshot(now=T)
    assert snap["status"] == "idle" and snap["sessions"] == []


def test_dismiss_hides_cards_and_snoozes(orbit):
    seed_failing(orbit)
    rt, _, snoozes = make(orbit, Recorder())
    rt.snapshot(now=T)
    result = rt.dismiss("s1", 600)
    assert result == {"session_uid": "s1", "until": NOW + 600_000}
    assert snoozes == [(600, "session:s1:failing"), (600, "session:s1:context_pressure")]
    item = rt.snapshot(now=T + 1)["sessions"][0]
    assert item["state"] == "failing" and "failing" not in item["flags"]
    assert item["dismissed_until"] == NOW + 600_000
    with pytest.raises(ApiError):
        rt.dismiss("nope")


def test_hash_ignores_generated_at_and_running_s(orbit):
    orbit.session("s3", started=NOW - 60_000)
    orbit.event("s3", NOW - 1_000, actor="tool")
    rt, _, _ = make(orbit, Recorder())
    a, b = rt.snapshot(now=T), rt.snapshot(now=T + 1)
    assert a["generated_at"] != b["generated_at"]
    assert a["sessions"][0]["running_s"] != b["sessions"][0]["running_s"]
    assert content_hash(a) == content_hash(b)


def test_density_and_lanes(orbit):
    orbit.session("s4", started=NOW - 600_000)
    for minutes in (0, 0, 3, 9, 15):
        orbit.event("s4", NOW - minutes * 60_000 - 1, actor="human")
    orbit.call("s4", NOW - 120_000, status="failed")
    rt, _, _ = make(orbit, Recorder())
    item = rt.snapshot(now=T, lanes=True)["sessions"][0]
    assert item["density"] == [1, 0, 0, 0, 0, 0, 1, 0, 0, 2]
    assert len(item["lanes"]["human"]) == 5 and len(item["lanes"]["error"]) == 1
    assert "lanes" not in rt.snapshot(now=T)["sessions"][0]


def test_paused_lists_no_stale_sessions_and_idle_is_counted_not_listed(orbit):
    """a1a3-B20: paused collection reports nothing; idle sessions are not listed."""
    seed_failing(orbit)
    orbit.session("old", started=NOW - 5 * 3_600_000)
    orbit.event("old", NOW - 4 * 3_600_000, actor="assistant")
    rt, _, _ = make(orbit, Recorder(), paused=True)
    snap = rt.snapshot(now=T)
    assert snap["sessions"] == [] and snap["reason"] == "collection_paused"
    assert snap["today"] is None
    rt, _, _ = make(orbit, Recorder())
    snap = rt.snapshot(now=T)
    assert [s["session_uid"] for s in snap["sessions"]] == ["s1"]
    assert snap["counts"]["idle"] == 1


def test_old_sessions_skip_detail_reads(orbit):
    from orbit_backend.realtime.tail import load_tails

    orbit.session("old", started=NOW - 5 * 3_600_000)
    orbit.event("old", NOW - 2 * 3_600_000, actor="assistant")
    orbit.usage("old", NOW - 2 * 3_600_000, 190_000)
    tails = {t.session_uid: t for t in load_tails(Reads(orbit.path), NOW)}
    assert tails["old"].events == [] and tails["old"].usage is None


def test_tail_reads_reported_context_window(orbit):
    from orbit_backend.realtime.tail import load_tails

    orbit.session("cx", agent="codex", started=NOW - 60_000)
    orbit.event("cx", NOW - 30_000, kind="turn.start", actor="system")
    orbit.db.execute("UPDATE event SET ext=? WHERE session_uid='cx' AND kind='turn.start'",
                      ('{"model_context_window": 258400}',))
    orbit.db.commit()
    orbit.usage("cx", NOW - 20_000, 1000, model="gpt-5-codex")
    tail = next(t for t in load_tails(Reads(orbit.path), NOW) if t.session_uid == "cx")
    assert tail.usage["window_tokens"] == 258_400


def test_failing_ticks_are_logged_once_per_distinct_error(orbit, monkeypatch):
    from orbit_backend.realtime import service

    rt, _, _ = make(orbit, Recorder())
    errors = iter([RuntimeError("db locked"), RuntimeError("db locked"), ValueError("bad row"), None])

    def refresh(now=None):
        error = next(errors)
        if error:
            raise error

    class Ticks:  # stop.wait stand-in: four ticks, then stop
        def __init__(self):
            self.left = 4

        def wait(self, _):
            self.left -= 1
            return self.left < 0

        def is_set(self):
            return False

    logged = []
    monkeypatch.setattr(service.logs, "log_event", lambda ev, level, **f: logged.append(f["error"]))
    rt.refresh, rt.stop, rt.clients = refresh, Ticks(), 1
    rt._run()  # never raises out of the loop
    assert logged == ["RuntimeError: db locked", "ValueError: bad row"]
    assert rt.last_error is None  # the last tick succeeded
