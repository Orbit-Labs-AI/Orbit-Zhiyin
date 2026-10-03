"""GET /v1/shell/popover over an empty home and a synthetic orbit.db with a fixed clock."""

from __future__ import annotations

from realtime_fixtures import NOW, Orbit

from orbit_backend.realtime.service import Realtime
from orbit_backend.shell import popover

H = 3_600_000
MIN = 60_000


def test_empty_home_is_idle_and_zero(gateway_factory):
    client, _ = gateway_factory()
    body = client.get("/v1/shell/popover?tz_offset_min=480").json()
    assert body["status"] == "idle" and body["paused"] is None
    assert body["today"]["sessions"] == 0 and body["today"]["duration_s"] == 0
    assert body["today"]["running"] == 0 and body["live"] == [] and body["recent_done"] == []
    assert len(body["week"]["days"]) == 7
    assert all(d["sessions"] == 0 for d in body["week"]["days"])
    assert body["week"]["avg_per_day"] == 0 and body["weekly"]["sessions"] == 0
    assert body["yesterday"] is None and body["persona"] is None and body["top_rec"] is None
    assert body["opening"] is None and body["attention"] == []


def test_paused_collection(gateway_factory):
    client, _ = gateway_factory()
    client.post("/v1/platform/collection/pause", json={})
    body = client.get("/v1/shell/popover").json()
    assert body["status"] == "paused" and body["paused"]["since"] is not None
    assert len(body["week"]["days"]) == 7
    client.post("/v1/platform/collection/resume", json={})
    assert client.get("/v1/shell/popover").json()["status"] == "idle"


def seed(home):
    t = Orbit(home)
    # Running: started 30 min ago, events up to 20 s ago.
    t.session("run", started=NOW - 30 * MIN, title="running one")
    t.event("run", NOW - 30 * MIN, actor="human", kind="message.user", text="go")
    t.event("run", NOW - 20_000)
    # Completed and failed today (UTC day of NOW = 2027-01-15, 08:00Z).
    t.session("done", status="completed", started=NOW - 3 * H, ended=NOW - 2 * H,
              title="finished", agent="codex")
    t.event("done", NOW - 2 * H)
    t.session("bad", status="failed", started=NOW - 90 * MIN, ended=NOW - 80 * MIN)
    t.event("bad", NOW - 80 * MIN)
    # 23:00Z the previous day: "yesterday" at UTC, "today" at UTC+8 (07:00 local).
    t.session("late", status="completed", started=NOW - 9 * H, ended=NOW - 9 * H + 20 * MIN)
    # Earlier this week.
    for day in (2, 3, 3):
        uid = f"old{day}-{t.n}"
        t.session(uid, status="completed", started=NOW - day * 24 * H, ended=NOW - day * 24 * H + H)
        t.event(uid, NOW - day * 24 * H)
    t.db.close()


def make_gateway(gateway_factory, tmp_path):
    home = tmp_path / "orbit"
    home.mkdir()
    seed(home)
    _, gw = gateway_factory(home=home, started=False)
    gw.realtime = Realtime(gw, clock=lambda: NOW / 1000)
    submitted = []
    gw.supervisor.analysis.submit = lambda *a, **k: submitted.append(a)  # must stay unused
    return gw, submitted


def test_counts_live_and_recent(gateway_factory, tmp_path):
    gw, submitted = make_gateway(gateway_factory, tmp_path)
    body = popover.build(gw, tz_offset_min=0, now=NOW)
    assert body["status"] == "active"
    assert body["today"]["date"] == "2027-01-15"
    assert body["today"]["sessions"] == 3  # run, done, bad (late is yesterday at UTC)
    # Active time like the overview / session list ``dur`` (event gaps capped at 5 min):
    # run's 29m40s gap counts 5 min; done and bad have one event each (no active span), so
    # their wall-clock 1 h and 10 min are not work time.
    assert body["today"]["duration_s"] == 5 * 60
    assert body["today"]["duration_basis"] == "active_estimate"
    assert body["today"]["running"] == 1
    assert [s["session_uid"] for s in body["live"]][0] == "run"
    assert all("lanes" not in s for s in body["live"])
    assert [r["session_uid"] for r in body["recent_done"]] == ["bad", "done"]
    assert body["recent_done"][0]["status"] == "failed"
    assert body["recent_done"][1] == {**body["recent_done"][1], "agent": "codex",
                                      "duration_s": 3600, "status": "completed"}
    week = body["week"]
    assert len(week["days"]) == 7 and week["days"][-1]["date"] == "2027-01-15"
    assert [d["sessions"] for d in week["days"]] == [0, 0, 0, 2, 1, 1, 3]
    assert week["days"][-1]["by_agent"] == {"claude_code": 2, "codex": 1, "other": 0}
    assert week["today"] == 3 and week["avg_per_day"] == round(7 / 7, 1)
    assert body["weekly"]["sessions"] == 7
    assert body["yesterday"]["sessions"] == 1 and body["yesterday"]["date"] == "2027-01-14"
    assert body["opening"] is None  # Active: the idle-state hint is not shown.
    assert submitted == []  # A popover read never queues an analysis.


def test_timezone_moves_day_boundary(gateway_factory, tmp_path):
    gw, submitted = make_gateway(gateway_factory, tmp_path)
    east = popover.build(gw, tz_offset_min=480, now=NOW)  # NOW is 16:00 local
    assert east["today"]["sessions"] == 4  # "late" (07:00 local) now counts as today
    assert len(east["week"]["days"]) == 7
    west = popover.build(gw, tz_offset_min=-600, now=NOW)  # 22:00 the previous day
    assert west["today"]["date"] == "2027-01-14" and len(west["week"]["days"]) == 7
    assert submitted == []


def test_idle_shows_opening_and_yesterday(gateway_factory, tmp_path):
    home = tmp_path / "orbit"
    home.mkdir()
    t = Orbit(home)
    t.session("y", status="completed", started=NOW - 20 * H, ended=NOW - 19 * H)
    t.event("y", NOW - 20 * H, actor="human", kind="message.user", text="不对，重新来")
    t.db.close()
    _, gw = gateway_factory(home=home, started=False)
    gw.realtime = Realtime(gw, clock=lambda: NOW / 1000)
    body = popover.build(gw, tz_offset_min=0, now=NOW, wait_opening=True)
    assert body["status"] == "idle" and body["today"]["sessions"] == 0
    assert body["yesterday"]["sessions"] == 1
    assert set(body["yesterday"]["baseline"]) >= {"sessions_per_day", "hours_per_day",
                                                  "correction_rate", "completion_rate"}
    assert body["yesterday"]["completion_rate"] == 1.0
    assert body["opening"] is None or (set(body["opening"]) == {"text", "refs", "next", "basis"} and body["opening"]["basis"] == "rule")


def test_today_duration_matches_the_session_list_active_time(gateway_factory, tmp_path):
    """Menu bar / widget ``duration_s`` is the sum of the A3 list ``dur`` of today's sessions."""
    from datetime import UTC

    from orbit_backend.uiview import sessions as uiview_sessions

    gw, _ = make_gateway(gateway_factory, tmp_path)
    body = popover.build(gw, tz_offset_min=0, now=NOW)
    with gw.reads.read(check=False) as db:
        rows = uiview_sessions.l1_facts(db, UTC)
    start = NOW - NOW % (24 * H)
    today = [r for r in rows if r["started_at"] is not None and start <= r["started_at"] <= NOW]
    assert len(today) == body["today"]["sessions"]
    assert body["today"]["duration_s"] == round(sum(r["dur"] or 0 for r in today) * 60)


def test_realtime_today_counts_the_same_session_set(gateway_factory, tmp_path):
    """HUD / widget ``today`` (realtime) counts the menu-bar set: main sessions only, so a
    subagent session with recent events is not a session of its own."""
    import sqlite3

    home = tmp_path / "orbit"
    home.mkdir()
    seed(home)
    t = Orbit(home)
    t.n = 10_000  # past seed()'s event ids
    t.session("child", started=NOW - 10 * MIN)
    t.event("child", NOW - 5 * MIN)
    t.db.close()
    db = sqlite3.connect(home / "orbit.db")
    db.execute("UPDATE session SET kind = 'subagent', root_uid = 'run' WHERE session_uid = 'child'")
    db.commit()
    db.close()
    _, gw = gateway_factory(home=home, started=False)
    rt = Realtime(gw, clock=lambda: NOW / 1000)
    tails = rt._tails(NOW)
    assert "child" in {t.session_uid for t in tails}
    counted = rt._counted(tails)
    assert counted == {"run", "done", "bad"}
    body = popover.build(gw, tz_offset_min=0, now=NOW)
    assert body["today"]["sessions"] == len(counted)
