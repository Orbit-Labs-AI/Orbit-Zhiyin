import json
import time
from datetime import UTC, datetime

import pytest

from tandem_backend.sessionops import exclusion
from tandem_backend.uiview import sessions

from .l1_builder import *  # noqa: F403 - pytest fixtures
from .l1_builder import DAY, MIN, T0, codex_unknown, handwritten_cc


def populate(l1, n=9, base=T0):
    """n simple sessions, one every 8 hours, alternating agent and project."""
    for i in range(n):
        uid, at = f"s{i:02d}", base - i * 8 * 3600_000
        agent = "codex" if i % 2 else "claude_code"
        l1.session(uid, agent=agent, project="p1" if i % 3 else "p2", started=at,
                   title=f"任务 {i}" if i % 4 else None)
        l1.user(uid, at, f"第 {i} 个任务：整理 changelog")
        l1.call(uid, at + MIN, head="git status",
                status="unknown" if agent == "codex" else "success")
        l1.reply(uid, at + 2 * MIN, final=True)


def facts(l1, **kw):
    return sessions.l1_facts(l1.db, UTC, **kw)


def test_fact_rows(l1):
    handwritten_cc(l1)
    codex_unknown(l1)
    rows = {r["id"]: r for r in facts(l1, excluded=["cx-1"])}
    cc, cx = rows["cc-fix"], rows["cx-1"]
    assert (cc["a"], cc["p"], cc["d"], cc["h"], cc["mi"]) == ("claude_code", "p1", "2025-10-09",
                                                             8, 53)
    assert (cc["msgs"], cc["tools"], cc["errors"], cc["corr"]) == (3, 8, 3, 2)
    assert cc["dur"] == 12.0 and cc["dur_basis"] == "active_estimate"
    # Completed, but 2 of 3 human messages are corrections (2/3 >= 1/3, >= 2): needs rework.
    assert cc["tok"] == 211_700 and cc["out"] == "part" and cc["out_basis"] == "estimate"
    assert cx["errors"] is None and cx["tok"] is None and cx["out"] is None
    assert cx["title"] == "重构 data loader 模块" and cx["title_source"] == "first_message"
    assert cx["excluded"] is True and cc["excluded"] is False
    assert list(rows) == ["cc-fix", "cx-1"]  # newest first


def test_active_duration_caps_idle_gaps(l1):
    l1.session("idle", started=T0)
    l1.user("idle", T0, "开始")
    l1.reply("idle", T0 + 2 * MIN)
    l1.user("idle", T0 + 62 * MIN, "继续")  # 60 min idle gap counts as 5 min
    row = facts(l1)[0]
    assert row["dur"] == 7.0 and row["span"] == 62.0


def test_estimated_outcome_rules():
    est = sessions.estimate_outcome
    assert est(True, "completed", None, []) == "live"
    assert est(False, "completed", None, ["failed"] * 3) == "part"
    assert est(False, "completed", None, ["failed", "failed", "success"]) == "ok"
    assert est(False, "unknown", "interrupted", []) == "fail"  # shown as 疑似中断
    assert est(False, "unknown", "completed", ["success"]) == "ok"
    assert est(False, "unknown", None, []) is None
    # Correction density, not a raw count: 3 corrections in 200 messages is routine steering.
    assert est(False, "unknown", "completed", [], corr=3, msgs=200) == "ok"
    assert est(False, "unknown", "completed", [], corr=2, msgs=6) == "part"  # 2/6 = 1/3
    assert est(False, "unknown", "completed", [], corr=1, msgs=1) == "ok"  # one hit never decides
    assert sessions.errors_of([]) == 0
    assert sessions.errors_of(["unknown", "unknown"]) is None
    assert sessions.errors_of(["unknown", "failed"]) == 1


def test_list_grouping_paging_and_filters(l1):
    populate(l1)
    rows = facts(l1)
    now = T0 + 3600_000
    body = sessions.list_sessions(rows, now_ms=now, tz=UTC, limit=4)
    assert body["total"] == 9 and body["next_offset"] == 4 and len(body["rows"]) == 4
    assert [r["id"] for r in body["rows"]] == ["s00", "s01", "s02", "s03"]
    assert [d["day"] for d in body["days"]] == ["2025-10-09", "2025-10-08"]
    assert body["days"][0]["label"] == "今天" and body["days"][1]["label"] == "昨天"
    days = [r["d"] for r in body["rows"]]
    assert days == sorted(days, reverse=True)
    last = sessions.list_sessions(rows, now_ms=now, tz=UTC, offset=8, limit=4)
    assert [r["id"] for r in last["rows"]] == ["s08"] and last["next_offset"] is None
    codex = sessions.list_sessions(rows, now_ms=now, tz=UTC, agents=["codex"])
    assert codex["total"] == sum(r["a"] == "codex" for r in rows) == 4
    p2 = sessions.list_sessions(rows, now_ms=now, tz=UTC, project="p2")
    assert {r["id"] for r in p2["rows"]} == {r["id"] for r in rows if r["p"] == "p2"}
    hour = rows[1]["h"]
    by_hour = sessions.list_sessions(rows, now_ms=now, tz=UTC, hour=hour)
    assert by_hour["total"] == sum(r["h"] == hour for r in rows)
    week = sessions.list_sessions(rows, now_ms=now, tz=UTC, range_days=2)
    start = datetime(2025, 10, 8, tzinfo=UTC).timestamp() * 1000
    assert week["total"] == sum(r["started_at"] >= start for r in rows)
    assert week["meta"]["count_label"]["today"] == sum(r["d"] == "2025-10-09" for r in rows)
    ok = sessions.list_sessions(rows, now_ms=now, tz=UTC, outcome="ok")
    assert ok["total"] == sum(r["out"] == "ok" for r in rows)


def test_search_union_of_index_hits_and_substrings(l1):
    populate(l1, 4)
    rows = facts(l1)
    now = T0
    by_title = sessions.list_sessions(rows, now_ms=now, tz=UTC, q="任务 2")
    assert [r["id"] for r in by_title["rows"]] == ["s02"]
    by_project = sessions.list_sessions(rows, now_ms=now, tz=UTC, q="proj p2",
                                        projects={"p1": "Proj p1", "p2": "Proj p2"})
    assert {r["id"] for r in by_project["rows"]} == {r["id"] for r in rows if r["p"] == "p2"}
    by_agent = sessions.list_sessions(rows, now_ms=now, tz=UTC, q="Codex")
    assert by_agent["total"] == 2
    union = sessions.list_sessions(rows, now_ms=now, tz=UTC, q="任务 2", q_uids={"s03"})
    assert {r["id"] for r in union["rows"]} == {"s02", "s03"}


def test_ticks_normalized_with_failures(l1):
    handwritten_cc(l1)
    l1.session("many", started=T0 - DAY)
    for i in range(200):
        l1.call("many", T0 - DAY + i * 1000, status="failed" if i in (50, 150) else "success")
    rows = facts(l1)
    marks = sessions.ticks(l1.db, rows)
    cc = marks["cc-fix"]
    assert len(cc["t"]) + len(cc["e"]) == 8 and len(cc["e"]) == 3
    assert all(0 <= t <= 1 for t in cc["t"] + cc["e"])
    assert cc["e"] == [0.5, 0.5417, 0.5833]
    many = marks["many"]
    assert len(many["t"]) <= sessions.TICKS_MAX and len(many["e"]) == 2


def test_route_list_keeps_excluded_and_validates(client, gateway, l1):
    handwritten_cc(l1)
    codex_unknown(l1)
    exclusion.add(gateway.appdb, "cx-1", "test")
    body = client.get("/v1/uiview/sessions").json()
    rows = {r["id"]: r for r in body["rows"]}
    assert set(rows) == {"cc-fix", "cx-1"}
    assert rows["cx-1"]["excluded"] is True and body["meta"]["count_label"]["excluded"] == 1
    assert rows["cc-fix"]["ticks"]["e"] == [0.5, 0.5417, 0.5833]
    assert rows["cx-1"]["errors"] is None and rows["cx-1"]["a"] == "codex"
    assert set(rows["cc-fix"]) == set(sessions.LIST_FIELDS) | {"ticks"}
    assert client.get("/v1/uiview/sessions?agents=codex").json()["total"] == 1
    assert client.get("/v1/uiview/sessions?q=Cloudflare").json()["total"] == 1
    assert client.get("/v1/uiview/sessions?range=5").status_code == 422
    assert client.get("/v1/uiview/sessions?outcome=bad").status_code == 422
    assert client.get("/v1/uiview/sessions?tz=Mars/Base").status_code == 422
    assert "/Users/" not in json.dumps(body, ensure_ascii=False)


def test_live_overlay_from_realtime_snapshot(client, gateway, l1):
    handwritten_cc(l1)

    class Snap:
        def latest(self):
            return {"sessions": [{"session_uid": "cc-fix", "state": "running"}]}

    gateway.realtime = Snap()
    body = client.get("/v1/uiview/sessions").json()
    row = body["rows"][0]
    assert row["live"] is True and row["out"] == "live"
    assert body["meta"]["count_label"]["live"] == 1


@pytest.mark.parametrize("n", [600])
@pytest.mark.serial
def test_list_build_is_fast(l1, n):
    populate(l1, n, base=T0)
    started = time.perf_counter()
    rows = facts(l1)
    sessions.list_sessions(rows, now_ms=T0, tz=UTC)
    assert len(rows) == n and time.perf_counter() - started < 1.0


def _facts_client(gateway, facts_rows):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tandem_backend.services.gateway import install_error_handlers
    from tandem_backend.uiview import routes_sessions

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_sessions.router(gateway, facts_provider=lambda: facts_rows))
    return TestClient(app)


def test_live_row_keeps_live_outcome_over_facts_snapshot(gateway, l1):
    """A facts snapshot taken earlier says 'ok'; the running session must stay 'live' (UT-02)."""
    handwritten_cc(l1)

    class Snap:
        def latest(self):
            return {"sessions": [{"session_uid": "cc-fix", "state": "running"}]}

    gateway.realtime = Snap()
    client = _facts_client(gateway, {"cc-fix": {"out": "ok", "corr": 5}})
    row = client.get("/v1/uiview/sessions").json()["rows"][0]
    assert (row["out"], row["out_basis"], row["live"]) == ("live", "realtime", True)
    assert row["corr"] == 5  # other facts still win
    assert client.get("/v1/uiview/sessions?outcome=live").json()["total"] == 1
    assert client.get("/v1/uiview/sessions?outcome=ok").json()["total"] == 0
    head = client.get("/v1/uiview/sessions/cc-fix").json()["header"]
    assert (head["out"], head["out_basis"], head["live"]) == ("live", "realtime", True)


def test_finished_row_ignores_live_out_from_stale_snapshot(gateway, l1):
    """Snapshot built while running (out='live'); now finished: the L1 estimate stays."""
    handwritten_cc(l1)
    plain = _facts_client(gateway, {}).get("/v1/uiview/sessions").json()["rows"][0]
    assert plain["live"] is False and plain["out"] != "live"
    client = _facts_client(gateway, {"cc-fix": {"out": "live", "out_basis": "realtime"}})
    row = client.get("/v1/uiview/sessions").json()["rows"][0]
    assert (row["out"], row["out_basis"]) == (plain["out"], plain["out_basis"])
    assert client.get("/v1/uiview/sessions?outcome=live").json()["total"] == 0
    head = client.get("/v1/uiview/sessions/cc-fix").json()["header"]
    assert head["out"] == plain["out"] and head["live"] is False


def test_overlay_unit_rules():
    rows = [{"id": "a", "out": "live", "out_basis": "realtime", "live": True},
            {"id": "b", "out": "part", "out_basis": "estimate", "live": False},
            {"id": "c", "out": "ok", "out_basis": "estimate", "live": False}]
    got = {r["id"]: r for r in sessions.overlay(rows, {
        "a": {"out": "fail"}, "b": {"out": "live"}, "c": {"out": None}})}
    assert got["a"]["out"] == "live"
    assert (got["b"]["out"], got["b"]["out_basis"]) == ("part", "estimate")
    assert got["c"]["out"] is None  # facts explicitly unknown still win for finished rows


def test_route_search_uses_full_session_cover(client, l1, monkeypatch):
    """UT-03: the list filter takes every session the search sources hit, and passes the
    cover's completeness through as meta.search_partial."""
    from tandem_backend import features

    populate(l1, 9)
    calls = []

    class Svc:
        def search(self, q, kinds=None, limit=20, session_cover=False):
            calls.append((limit, session_cover))
            return {"results": [], "session_uids": [f"s{i:02d}" for i in range(1, 9)],
                    "session_cover_complete": complete}

    monkeypatch.setattr(features, "current", lambda: Svc())
    complete = True
    body = client.get("/v1/uiview/sessions?q=zzqx").json()
    assert body["total"] == 8 and body["meta"]["search_partial"] is False
    assert calls[-1][1] is True
    complete = False
    assert client.get("/v1/uiview/sessions?q=zzqy").json()["meta"]["search_partial"] is True
