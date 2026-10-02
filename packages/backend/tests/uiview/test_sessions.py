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
    assert cc["tok"] == 211_700 and cc["out"] == "ok" and cc["out_basis"] == "estimate"
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
    assert est(False, "unknown", "interrupted", []) == "part"
    assert est(False, "unknown", "completed", ["success"]) == "ok"
    assert est(False, "unknown", None, []) is None
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
def test_list_build_is_fast(l1, n):
    populate(l1, n, base=T0)
    started = time.perf_counter()
    rows = facts(l1)
    sessions.list_sessions(rows, now_ms=T0, tz=UTC)
    assert len(rows) == n and time.perf_counter() - started < 1.0
