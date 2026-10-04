import sqlite3
import time

import pytest

from orbit_backend.sessionops import toolcalls

from .conftest import T0

SECRET = "sk-ant-" + "A1b2C3d4E5f6G7h8I9j0K1"


@pytest.fixture
def seeded(orbit):
    orbit.session("s1", cwd="/w/p1")
    orbit.session("s2", agent="codex", project="p2", cwd="/w/p2")
    orbit.call("s1", head="git", at=T0 + 1, uid="a1",
                input={"command": f"curl -H 'x-api-key: {SECRET}' https://x.dev"},
                files=["/w/p1/src/a.py", "/elsewhere/b.py"])
    orbit.call("s1", name="Read", kind="file.read", at=T0 + 2, uid="a2",
                input={"file_path": "/w/p1/README.md"})
    orbit.call("s1", head="rm", status="failed", at=T0 + 3, uid="a3")
    orbit.call("s2", head="git", status="completed", at=T0 + 4, uid="a4",
                input={"command": ["git", "status"]})
    orbit.call("s2", name="mcp__pw__click", kind="mcp", at=T0 + 5, uid="a5")
    return orbit


def test_filters_and_item_shape(seeded):
    db = seeded.db
    db.row_factory = sqlite3.Row
    page = toolcalls.query(db, {})
    assert [i["call_uid"] for i in page["items"]] == ["a5", "a4", "a3", "a2", "a1"]
    assert page["has_more"] is False and page["next_cursor"] is None
    first = page["items"][-1]
    assert first["files"] == ["src/a.py", "/elsewhere/b.py"]
    assert SECRET not in first["args_summary"] and "curl" in first["args_summary"]
    assert first["agent"] == "claude_code" and first["title"] == "Title s1"
    assert first["project_id"] == "p1" and first["is_wrapper"] is False
    assert page["items"][-2]["args_summary"] == "/w/p1/README.md"
    assert page["items"][1]["args_summary"] == "git status"

    def uids(**filters):
        return [i["call_uid"] for i in toolcalls.query(db, filters)["items"]]

    assert uids(command_head="git") == ["a4", "a1"]
    assert uids(status="ok") == ["a5", "a4", "a2", "a1"]
    assert uids(status="failed") == ["a3"]
    assert uids(agent=["codex"]) == ["a5", "a4"]
    assert uids(project_id=["p1"], name="Read") == ["a2"]
    assert uids(kind="mcp") == ["a5"]
    assert uids(session_uid="s1", from_ts=T0 + 2, until_ts=T0 + 3) == ["a2"]
    assert [i["call_uid"] for i in toolcalls.query(db, {}, excluded=["s1"])["items"]] == [
        "a5", "a4"]
    with pytest.raises(ValueError):
        toolcalls.query(db, {}, cursor="%%%")
    with pytest.raises(ValueError):
        toolcalls.query(db, {}, limit=0)


def test_keyset_pagination_three_pages(orbit):
    orbit.session("s1")
    for i in range(25):  # Some calls share a timestamp; call_uid breaks ties.
        orbit.call("s1", at=T0 + i // 3, uid=f"k{i:03d}")
    orbit.db.row_factory = sqlite3.Row
    seen, cursor, pages = [], None, 0
    while True:
        page = toolcalls.query(orbit.db, {}, limit=10, cursor=cursor)
        seen += [i["call_uid"] for i in page["items"]]
        pages += 1
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert pages == 3 and len(seen) == 25 == len(set(seen))


def test_session_filter_uses_index(seeded):
    sql = toolcalls.SQL.format(where="tc.session_uid = ?")
    plan = " ".join(r[-1] for r in seeded.db.execute("EXPLAIN QUERY PLAN " + sql, ("s1", 50)))
    assert "SCAN tc" not in plan and "USING INDEX" in plan


@pytest.mark.serial
def test_fifty_thousand_rows_under_300ms(orbit):
    orbit.session("s1")
    orbit.session("s2", agent="codex")
    orbit.db.execute("BEGIN")
    orbit.db.executemany(
        "INSERT INTO tool_call(call_uid, session_uid, name_raw, name, kind, command_head, files, "
        "status, pairing_quality, started_at, duration_source, duration_quality) "
        "VALUES (?, ?, 'Bash', 'Bash', 'shell', 'git', '[]', 'success', 'paired', ?, 'unknown', "
        "'missing')", ((f"t{i:06d}", f"s{i % 2 + 1}", T0 + i) for i in range(50_000)))
    orbit.db.execute("COMMIT")
    orbit.db.row_factory = sqlite3.Row
    toolcalls.query(orbit.db, {})  # Warm the page cache.
    started = time.perf_counter()
    page = toolcalls.query(orbit.db, {"command_head": "git"}, limit=50, excluded=["s2"])
    toolcalls.query(orbit.db, {}, limit=50, cursor=page["next_cursor"])
    toolcalls.query(orbit.db, {"session_uid": "s1"}, limit=50)
    assert (time.perf_counter() - started) / 3 < 0.3
    assert len(page["items"]) == 50 and page["items"][0]["call_uid"] == "t049998"


def test_tool_calls_endpoint(seeded, client):
    body = client.get("/v1/analytics/tool_calls", params={"limit": 2}).json()
    assert [i["call_uid"] for i in body["items"]] == ["a5", "a4"] and body["has_more"]
    nxt = client.get("/v1/analytics/tool_calls",
                     params={"limit": 2, "cursor": body["next_cursor"]}).json()
    assert [i["call_uid"] for i in nxt["items"]] == ["a3", "a2"]
    for params in ({"cursor": "not-a-cursor"}, {"limit": 0}, {"limit": 201},
                   {"status": "weird"}):
        bad = client.get("/v1/analytics/tool_calls", params=params)
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    client.post("/v1/sessions/s2/exclude", json={})
    kept = client.get("/v1/analytics/tool_calls").json()["items"]
    assert {i["session_uid"] for i in kept} == {"s1"}
    everything = client.get("/v1/analytics/tool_calls", params={"include_excluded": True})
    assert len(everything.json()["items"]) == 5
    multi = client.get("/v1/analytics/tool_calls?agent=codex&agent=claude_code&project_id=p2"
                       "&include_excluded=true").json()["items"]
    assert [i["call_uid"] for i in multi] == ["a5", "a4"]


def test_tool_calls_hide_disabled_sources(seeded, client, gateway):
    """SET-07: the A4 drilldown lists the calls the tools page counts (disabled sources hidden)."""
    for agent, enabled in (("claude_code", True), ("codex", False)):
        gateway.state.state["sources"][f"src-{agent}"] = {
            "id": f"src-{agent}", "agent": agent, "root": f"/agents/{agent}", "enabled": enabled}
    kept = client.get("/v1/analytics/tool_calls").json()["items"]
    assert {i["session_uid"] for i in kept} == {"s1"}
    gateway.state.state["sources"]["src-claude_code"]["enabled"] = False
    assert client.get("/v1/analytics/tool_calls").json()["items"] == []  # every source off
