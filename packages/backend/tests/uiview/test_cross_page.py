"""One definition per metric and filter across pages (A1 overview / A3 sessions / A4 tools / A6).

- tool-call results: ``metrics.tool_state`` (interrupted = known, not failed) everywhere;
- the prototype's "no project" id ``_none`` selects sessions whose project is NULL on every
  page, not an empty set;
- A6 ``days`` is N local calendar days like A1 / A3 ``range``, not N×24 h back from now.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from orbit_backend.analytics.inputs import Scope
from orbit_backend.uiview import a4a6_common as common
from orbit_backend.uiview import a4a6_sentiment, derive, facts, metrics, sessions
from orbit_backend.uiview import a4a6_tools as tools

from .a4a6_fixture import T0, conn, home, orbit  # noqa: F401 - pytest fixtures


@pytest.mark.parametrize(("status", "state"), [
    ("completed", "ok"), ("success", "ok"), ("failed", "failed"), ("error", "failed"),
    ("interrupted", "stopped"), ("rejected", "stopped"), ("unknown", "unknown"),
    ("running", "unknown"), (None, "unknown"), ("", "unknown")])
def test_tool_state(status, state):
    assert metrics.tool_state(status) == state


def test_interrupted_calls_count_alike_on_every_page(orbit, conn):  # noqa: F811
    orbit.session("s1")
    for status in ("completed", "failed", "interrupted", "unknown"):
        orbit.call("s1", status=status)
    kpi = tools.build_tools(conn, Scope(), {}, now_ms=T0 + 86_400_000)["kpis"]["error_rate"]
    assert (kpi["failed"], kpi["known"], kpi["unknown"]) == (1, 3, 1)
    statuses = ["completed", "failed", "interrupted", "unknown"]
    assert sessions.errors_of(statuses) == 1
    assert sessions.errors_of(["interrupted", "unknown"]) == 0  # interrupted is a known result
    assert sessions.errors_of(["unknown", "running"]) is None
    per_root = facts._tools(conn, '["s1"]', {})["s1"]
    (_kind, n, failed, known), = per_root.values()
    assert (n, failed, known) == (4, 1, 3)


def test_no_project_id_matches_null_project():
    assert derive.project_matches(None, derive.NO_PROJECT_ID)
    assert not derive.project_matches("p1", derive.NO_PROJECT_ID)
    assert derive.project_matches("p1", None) and derive.project_matches(None, None)
    assert derive.passes({"p": None, "a": "codex"}, {"project": "_none"})
    rows = [{"id": "a", "p": None, "a": "codex", "started_at": 1, "d": "2025-01-01",
             "live": False, "excluded": False},
            {"id": "b", "p": "p1", "a": "codex", "started_at": 1, "d": "2025-01-01",
             "live": False, "excluded": False}]
    body = sessions.list_sessions(rows, now_ms=2, tz=UTC, project="_none")
    assert [r["id"] for r in body["rows"]] == ["a"]


def test_no_project_id_in_sql_scopes(orbit, conn):  # noqa: F811
    orbit.session("with", project="p1")
    orbit.session("none", project=None)
    orbit.call("with")
    orbit.call("none")
    where, params = common.scope_where({"project_ids": ["_none"]})
    got = {r[0] for r in conn.execute(f"SELECT session_uid FROM session s WHERE {where}", params)}
    assert got == {"none"}
    where, params = common.scope_where({"project_ids": ["p1", "_none"]})
    got = {r[0] for r in conn.execute(f"SELECT session_uid FROM session s WHERE {where}", params)}
    assert got == {"with", "none"}
    body = tools.build_tools(conn, Scope(project_ids=["_none"]), {}, now_ms=T0 + 86_400_000)
    assert body["header"]["calls"] == 1
    got = a4a6_sentiment.fetch_sessions(conn, {"project_ids": ["_none"]})
    assert set(got) == {"none"}


def test_sentiment_days_are_local_calendar_days():
    zone = ZoneInfo("Asia/Shanghai")
    now = int(datetime(2026, 10, 3, 15, 30, tzinfo=zone).timestamp() * 1000)
    since, until = a4a6_sentiment._window({"days": 7}, now, zone)
    assert until == now
    assert datetime.fromtimestamp(since / 1000, zone) == datetime(2026, 9, 27, tzinfo=zone)
    # The same 7 days A1 / A3 call range=7: today and the six days before it.
    assert derive.win(7) == (-6, 0)
    assert (date(2026, 10, 3) - datetime.fromtimestamp(since / 1000, zone).date()).days == 6
    # An explicit since still wins; without a zone the old rolling window stays.
    assert a4a6_sentiment._window({"since": 5, "days": 7}, now, zone)[0] == 5
    assert a4a6_sentiment._window({"days": 1}, now)[0] == now - 86_400_000


def test_sentiment_previous_window_is_the_n_days_before():
    """The comparison window is the N local calendar days before ``since`` (A1 prev_win),
    not an equal-length span that starts mid-day."""
    zone = ZoneInfo("Asia/Shanghai")
    now = int(datetime(2025, 10, 10, 15, 30, tzinfo=zone).timestamp() * 1000)
    since, until = a4a6_sentiment._window({"days": 7}, now, zone)
    prev = a4a6_sentiment._prev_start({"days": 7}, since, until, zone)
    assert prev == int(datetime(2025, 9, 27, tzinfo=zone).timestamp() * 1000)
    assert since == int(datetime(2025, 10, 4, tzinfo=zone).timestamp() * 1000)
    # explicit since / no zone keep the equal-length span
    assert a4a6_sentiment._prev_start({"since": 50}, 50, 80, zone) == 20
    assert a4a6_sentiment._prev_start({"days": 7}, since, until) == since - (until - since)


def test_project_persona_comes_from_the_fact_rows():
    """A5's persona column was always ``persona_pending`` (nothing set ``persona_lookup``);
    it now reads the same fact rows and ``persona.persona`` as A2, per project."""
    from orbit_backend.uiview import a4a6_projects, persona

    from .synth import analysed

    body = analysed()[4]
    rows = [r for r in body["rows"] if not r.get("excluded")]
    pid = next(r["p"] for r in rows if r.get("p"))
    find = a4a6_projects.facts_persona_lookup(body)
    got = a4a6_projects._persona(pid, find)
    mine = derive.prepare([r for r in rows if r.get("p") == pid], date.today())
    want = persona.persona(mine, body.get("aux") or {})
    assert got["status"] == "available" and got["code"] == want["code"]
    assert got["n"] == len(mine) and got["v"] == want["v"]
    # agents and the window narrow the rows; an empty selection is not "pending"
    empty = a4a6_projects._persona(pid, a4a6_projects.facts_persona_lookup(body, agents=["nope"]))
    assert empty["code"] is None and empty["status"] == "insufficient_sample"
    assert a4a6_projects._persona(pid, a4a6_projects.facts_persona_lookup(None))["status"] \
        == "persona_pending"


def test_feature_corrections_use_the_shared_verdict():
    """A1 ``corr`` (``correction_signal_count``) uses ``rules.is_correction`` like A3 / A6:
    a correction past the length gate is not counted, a short one is."""
    from orbit_backend.analytics.features import session_features
    from orbit_backend.analytics.interaction.rules import CORRECTION_CHARS, is_correction

    short = "不对，改回去"
    long_ = short + "。" + "补充背景说明" * (CORRECTION_CHARS[1] // 6 + 1)
    assert is_correction(short) and not is_correction(long_)

    def ev(uid, text):
        return {"event_uid": uid, "session_uid": "s", "kind": "message.user", "seq": 1,
                "ts": 1_790_000_000_000, "actor": "human", "text": text,
                "attrs": {"origin": "human"}}

    reply = {"event_uid": "a0", "session_uid": "s", "kind": "message.assistant", "seq": 0,
             "ts": 1_790_000_000_000, "actor": "assistant", "text": "好的", "attrs": {}}
    result = session_features({"session_uid": "s"}, [reply, ev("u1", short), ev("u2", long_)],
                              [], {"s"})
    assert result["features"]["correction_signal_count"] == 1
    assert [c["event_uid"] for c in result["correction_signals"]] == ["u1"]


def test_corrections_count_only_after_the_agent_responded_on_every_page(orbit, conn):  # noqa: F811
    """signals.detect_correction counts a correction only once the agent has replied in the
    session and never a replayed copy; A1 (session_features), A3 list and detail, A5 and A6
    use the same rule (``rules.countable_messages`` / ``countable_sql``)."""
    from orbit_backend.analytics.common import human
    from orbit_backend.analytics.features import session_features
    from orbit_backend.analytics.interaction.rules import countable_messages
    from orbit_backend.uiview import a4a6_projects, trajectory

    text = "不对，改回去"
    orbit.session("s")
    first = orbit.event("s", ts=T0 + 1_000, kind="message.user", text=text,
                        attrs={"origin": "human"})
    orbit.event("s", ts=T0 + 2_000, kind="message.assistant", text="好的")
    second = orbit.event("s", ts=T0 + 3_000, kind="message.user", text=text,
                         attrs={"origin": "human"})
    replay = orbit.event("s", ts=T0 + 4_000, kind="message.user", text=text,
                         attrs={"origin": "human", "replayed_from": second})
    orbit.db.execute("UPDATE event SET actor = 'human' WHERE kind = 'message.user'")
    orbit.db.execute("INSERT INTO event_context(event_uid, project_id) "
                     "SELECT event_uid, 'p1' FROM event WHERE session_uid = 's'")

    rows = [dict(r) for r in conn.execute("SELECT * FROM event WHERE session_uid='s' ORDER BY seq")]
    import json
    for r in rows:
        r["attrs"] = json.loads(r["attrs"] or "{}")
    assert [e["event_uid"] for e in countable_messages(rows, lambda e: human(e, {"s"}))] \
        == [second]
    features = session_features({"session_uid": "s"}, rows, [], {"s"})
    assert features["features"]["correction_signal_count"] == 1
    assert [c["event_uid"] for c in features["correction_signals"]] == [second]

    listed = {r["id"]: r for r in sessions.l1_facts(conn, UTC)}["s"]
    assert listed["msgs"] == 3 and listed["corr"] == 1
    detail = trajectory.build_detail(conn, "s", tz=UTC)
    flags = {e["event_uid"]: e["corr"] for e in detail["trajectory"]["events"] if e["lane"] == "user"}
    assert flags == {first: False, second: True, replay: False}

    humans = a4a6_sentiment.fetch_humans(conn, ["s"])  # replays are already dropped here
    assert [bool(a4a6_sentiment.message_corrections(m)) for m in humans] == [False, True]
    loaded = a4a6_projects.load(conn, {})
    assert loaded["sessions"]["s"]["corr"] == 1
