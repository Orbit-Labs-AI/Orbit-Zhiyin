"""Notification policy engine and attention queue (FE-18.1, AN-13.1)."""
# ruff: noqa: F811  (fixtures are imported from notify_fake and then used as parameters)

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from notify_fake import clock, gw  # noqa: E402,F401

notify = sys.modules["tandem_backend.platform.notify"]  # package attr `notify` is a function
from tandem_backend.platform.notify import Notifier  # noqa: E402


def frames(gw, event=None):
    got, _ = gw.bus.since(0, {"notify"})
    return [f for f in got if event is None or f.event == event]


def make(gw, clock):
    return Notifier(gw, clock=clock).start()


def test_matrix_routing_and_aliases(gw, clock):
    n = make(gw, clock)
    ids = {alias: n.emit({"type": alias, "title": alias, "session_uid": "s1"})
           for alias in ("waiting", "done", "stuck", "ctx")}
    rows = {r["id"]: r for r in n.listing()}
    assert rows[ids["waiting"]]["type"] == "awaiting_approval"
    assert rows[ids["waiting"]]["channels"] == ["banner", "hud", "badge"]
    assert rows[ids["waiting"]]["severity"] == "urgent"
    assert rows[ids["done"]]["channels"] == ["hud", "badge"]
    assert rows[ids["stuck"]]["type"] == "failing"
    assert rows[ids["ctx"]]["channels"] == ["hud"]
    with pytest.raises(ValueError):
        n.emit({"type": "nope", "title": "x"})
    with pytest.raises(ValueError):
        n.emit({"type": "system", "title": ""})
    assert notify.notify({"type": "weekly", "title": "周报"}) is not None


def test_cooldown_dedupe_merges_count(gw, clock):
    n = make(gw, clock)
    first = n.emit({"type": "failing", "title": "卡住", "session_uid": "s1"})
    clock.tick(10)
    again = n.emit({"type": "failing", "title": "卡住", "session_uid": "s1",
                    "payload": {"n": 2}})
    assert again == first
    row = n.listing()[0]
    assert row["count"] == 2 and row["payload"] == {"n": 2}
    assert row["last_ts"] - row["ts"] == 10_000
    assert len(frames(gw, "notification")) == 1
    assert frames(gw, "attention")[-1].data["deduped"] == {"id": first, "count": 2}
    clock.tick(300)  # Beyond cooldown: a fresh row supersedes the old one.
    third = n.emit({"type": "failing", "title": "卡住", "session_uid": "s1"})
    assert third != first
    assert [i["id"] for i in n.attention()] == [third]


def test_quiet_hours_cross_midnight(gw, clock, monkeypatch):
    n = make(gw, clock)
    n.set_policy({"quiet_hours": {"enabled": True, "start": "22:00", "end": "08:00"}})
    minute = {"v": 23 * 60}
    monkeypatch.setattr(notify, "_local_minute", lambda _ts: minute["v"])
    n.emit({"type": "failing", "title": "a"})
    n.emit({"type": "waiting", "title": "b"})  # In quiet_hours.allow.
    minute["v"] = 7 * 60 + 59
    n.emit({"type": "system", "title": "c"})
    minute["v"] = 12 * 60
    n.emit({"type": "ai_job_done", "title": "d"})
    rows = {r["title"]: r for r in n.listing()}
    assert rows["a"]["channels"] == ["badge"] and rows["a"]["suppressed_reason"] == "quiet_hours"
    assert rows["b"]["channels"] == ["banner", "hud", "badge"]
    assert rows["c"]["channels"] == ["badge"]
    assert rows["d"]["channels"] == ["banner", "badge"]


def test_rate_limit_keeps_badge_and_spares_urgent(gw, clock):
    n = make(gw, clock)
    for i in range(7):
        n.emit({"type": "ai_job_done", "title": f"t{i}", "key": f"k{i}"})
    rows = sorted(n.listing(), key=lambda r: r["id"])
    assert all(r["channels"] == ["banner", "badge"] for r in rows[:6])
    assert rows[6]["channels"] == ["badge"] and rows[6]["suppressed_reason"] == "rate_limited"
    urgent = n.emit({"type": "waiting", "title": "u", "session_uid": "x"})
    assert n.listing()[0]["id"] == urgent and "banner" in n.listing()[0]["channels"]
    clock.tick(61)
    n.emit({"type": "ai_job_done", "title": "later", "key": "k-later"})
    assert n.listing()[0]["channels"] == ["banner", "badge"]


def test_muted_snoozed_force_and_disabled(gw, clock):
    n = make(gw, clock)
    n.set_policy({"muted_types": ["done"]})
    n.emit({"type": "just_finished", "title": "m", "session_uid": "s"})
    n.snooze(600, "type:stuck")
    n.emit({"type": "failing", "title": "s", "session_uid": "s"})
    n.set_policy({"muted_types": ["system"]})
    forced = n.emit({"type": "system", "title": "f", "force": True})
    rows = {r["title"]: r for r in n.listing()}
    assert rows["m"]["channels"] == ["badge"] and rows["m"]["suppressed_reason"] == "muted_type"
    assert rows["s"]["channels"] == ["badge"] and rows["s"]["suppressed_reason"] == "snoozed"
    assert rows["f"]["id"] == forced and rows["f"]["channels"] == ["banner", "badge"]
    assert n.snoozes()[0]["scope"] == "type:failing"
    n.unsnooze("type:failing")
    assert n.snoozes() == []
    gw.platform.settings = {"notifications": False}
    n.emit({"type": "waiting", "title": "off"})
    off = n.listing()[0]
    assert off["state"] == "suppressed" and off["suppressed_reason"] == "disabled"


def test_attention_order_resolve_and_ack(gw, clock):
    n = make(gw, clock)
    n.emit({"type": "ctx", "title": "ctx", "session_uid": "a"})
    clock.tick(1)
    n.emit({"type": "stuck", "title": "fail1", "session_uid": "b"})
    clock.tick(1)
    n.emit({"type": "stuck", "title": "fail2", "session_uid": "c"})
    clock.tick(1)
    n.emit({"type": "waiting", "title": "wait", "session_uid": "d"})
    n.emit({"type": "done", "title": "done", "session_uid": "e"})  # info: not in attention.
    assert [i["title"] for i in n.attention()] == ["wait", "fail2", "fail1", "ctx"]
    assert n.resolve("awaiting_approval:d") == 1
    assert [i["title"] for i in n.attention()] == ["fail2", "fail1", "ctx"]
    assert frames(gw, "attention")[-1].data["urgent"] == 0
    target = n.attention()[0]["id"]
    out = n.ack(target, snooze_s=3600, mute_type=True)
    assert out["muted_type"] == "failing" and out["scope"] == "session:c:failing"
    assert "failing" in n.policy()["muted_types"]
    assert target not in [i["id"] for i in n.attention()]
    with pytest.raises(KeyError):
        n.ack(99999)
    assert n.ack_all() == 3  # fail1, ctx and the info row.
    assert n.attention() == [] and n.summary()["active"] == 0


def test_policy_validation_and_presets(gw, clock):
    n = make(gw, clock)
    for bad in ({"matrix": {"nope": ["badge"]}}, {"matrix": {"failing": ["sms"]}},
                {"quiet_hours": {"start": "25:00"}}, {"cooldown_s": {"failing": -1}},
                {"rate_limit": {"per_minute": 0}}, {"muted_types": ["x"]}, {"extra": 1}):
        with pytest.raises(ValueError):
            n.set_policy(bad)
    rev = n.policy()["policy_rev"]
    quiet = n.set_policy(preset="quiet")
    assert quiet["matrix"]["failing"] == ["hud", "badge"] and quiet["matrix"]["weekly"] == []
    assert quiet["policy_rev"] > rev
    assert n.set_policy(preset="all")["matrix"]["weekly"] == ["banner", "hud", "badge"]
    assert n.set_policy({"matrix": {"ctx": ["badge"]}})["matrix"]["context_pressure"] == ["badge"]


def test_restart_rebuilds_cooldown_and_policy(gw, clock):
    n = make(gw, clock)
    first = n.emit({"type": "stuck", "title": "x", "session_uid": "s"})
    n.set_policy({"rate_limit": {"per_minute": 2}})
    n.close()
    again = make(gw, clock)
    assert again.policy()["rate_limit"]["per_minute"] == 2
    clock.tick(5)
    assert again.emit({"type": "stuck", "title": "x", "session_uid": "s"}) == first
    assert notify._active is again


def test_prune_keeps_open_rows(gw, clock):
    n = make(gw, clock)
    keep = n.emit({"type": "waiting", "title": "open", "session_uid": "k"})
    for i in range(520):
        n.emit({"type": "weekly", "title": f"w{i}", "key": f"w{i}"})
    n.ack_all()
    keep2 = n.emit({"type": "waiting", "title": "open2", "session_uid": "k2"})
    n.snooze(60)
    clock.tick(31 * 86400)
    out = n.prune()
    assert out["snoozes"] == 1
    remaining = {r["id"] for r in n.listing("delivered")}
    assert remaining == {keep2}
    assert keep not in remaining  # Acked rows age out; open ones never do.
    with gw.appdb.read() as db:
        assert db.execute("SELECT COUNT(*) FROM notification").fetchone()[0] == 1


def test_observe_failed_job_and_degraded_service(gw, clock):
    n = make(gw, clock)
    n.observe("job", "job", {"id": "j1", "kind": "import", "status": "failed",
                             "error": {"code": "boom", "message": "坏了"}})
    n.observe("job", "job", {"id": "j2", "kind": "import", "status": "running"})
    n.observe("service", "service", {"name": "ingest", "state": "degraded"})
    n.observe("data", "data.published", {})
    rows = n.listing()
    assert [r["title"] for r in rows] == ["后台服务降级", "导入失败"]
    assert rows[1]["payload"]["job_id"] == "j1" and rows[1]["body"] == "坏了"


@pytest.mark.serial
def test_emit_is_fast(gw, clock):
    n = make(gw, clock)
    n.set_policy({"rate_limit": {"per_minute": 100000, "per_hour": 100000}})
    count = 1000
    started = time.perf_counter()
    for i in range(count):
        n.emit({"type": "ai_job_done", "title": "t", "key": f"k{i % 50}"})
    per_call = (time.perf_counter() - started) / count
    assert per_call < 0.001, per_call
