import math

import pytest

from orbit_backend.analytics.inputs import Scope
from orbit_backend.sessionops import toolcalls
from orbit_backend.uiview import a4a6_common as common
from orbit_backend.uiview import a4a6_tools as tools

try:
    from .a4a6_fixture import DAY, T0, build_standard, client, conn, gateway, home, orbit
except ImportError:
    from a4a6_fixture import DAY, T0, build_standard, client, conn, gateway, home, orbit

__all__ = ["client", "conn", "gateway", "home", "orbit"]  # pytest fixtures
NOW = T0 + 30 * DAY
SECRET = "sk-ant-" + "A1b2C3d4E5f6G7h8I9j0K1"


def build(conn, scope=None, params=None, inventory=None, now=NOW):
    return tools.build_tools(conn, scope or Scope(), params or {}, inventory_items=inventory,
                             now_ms=now)


def linear(values, q):
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def test_standard_header(orbit, conn):
    expected = build_standard(orbit)
    body = build(conn)
    assert body["header"] == {"calls": 566, "tool_kinds": 6, "mcp_servers": 1, "sessions": 40}
    assert expected == {"sessions": 40, "calls": 566}
    assert body["coverage"]["approval_agents_with"] == ["codex"]
    assert body["coverage"]["approval_agents_without"] == ["claude_code"]
    pw = next(t for t in body["tools"] if t["key"] == "mcp·pw")
    assert pw["kind"] == "mcp" and pw["mcp_server"] == "pw"


def test_error_rate_uses_known_results_only(orbit, conn):
    orbit.session("a", agent="codex")
    for i in range(5):
        orbit.call("a", status="unknown", at=T0 + i)
    body = build(conn)
    err = body["kpis"]["error_rate"]
    assert err["value"] is None and err["unknown_share"] == 1 and err["lo"] is None
    assert body["tools"][0]["err"] is None

    orbit.session("b")
    for i in range(35):  # 10 unknown (above, 5 + 5 here) of 40; 3 failed of 30 known.
        status = "unknown" if i < 5 else ("failed" if i < 8 else "success")
        orbit.call("b", status=status, at=T0 + 100 + i)
    err = build(conn)["kpis"]["error_rate"]
    assert (err["failed"], err["known"], err["unknown"]) == (3, 30, 10)
    assert err["value"] == pytest.approx(0.1) and err["unknown_share"] == pytest.approx(0.25)
    assert 0 <= err["lo"] <= err["value"] <= err["hi"] <= 1


def test_duration_quantiles_and_daily(orbit, conn):
    orbit.session("a")
    durations = [5, 100, 7, 80, 1200, 33, 0, 61]
    for i, d in enumerate(durations):
        orbit.call("a", duration=d, at=T0 + i * DAY // 2, quality="estimated" if i % 2 else
                    "reported")
    orbit.call("a", at=T0 + 1)  # No duration: not in the quantiles.
    row = build(conn)["tools"][0]
    assert row["p50_ms"] == linear(durations, 0.5)
    assert row["p90_ms"] == pytest.approx(linear(durations, 0.9))
    assert row["p95_ms"] == pytest.approx(linear(durations, 0.95))
    assert row["duration_quality"] == {"reported": 4, "estimated": 4}
    assert sum(row["daily"]) == row["n"] == 9 and len(row["days"]) == len(row["daily"])


def test_matrix_rows_sum_to_one_and_order_exclusion(orbit, conn):
    build_standard(orbit)
    orbit.session("dup")
    first = orbit.call("dup", name="Read", kind="file.read")
    shared = orbit.db.execute("SELECT call_event_uid FROM tool_call WHERE call_uid = ?",
                               (first,)).fetchone()[0]
    orbit.call("dup", name="Edit", kind="file.edit", event_uid=shared)
    orbit.call("dup", name="Bash", kind="shell")
    orbit.session("nul")
    orbit.call("nul", name="Read", kind="file.read", no_event=True)
    orbit.call("nul", name="Read", kind="file.read")
    m = build(conn)["matrix"]
    for row, n in zip(m["prob"], m["row_n"], strict=True):
        if n:
            assert sum(row) == pytest.approx(1, abs=1e-9)
    assert m["excluded_order_calls"] == 5
    assert m["pairs"] == 566 - 40 and "other" in m["nodes"]  # mcp falls into other.
    chain = m["top_chain"]
    assert chain and chain["support_sessions"] >= 3 and len(chain["probs"]) == 2


def test_mixed_case_tool_names_from_two_agents_are_one_row(orbit, conn):
    """claude_code says Bash/Edit/Grep/Read/WebSearch, codex bash/edit/grep/read/web.search:
    one row per tool, original spellings kept, drilldown by key or alias returns the same calls."""
    spellings = {"claude_code": (("Bash", "shell"), ("Edit", "file.edit"), ("Grep", "search"),
                                 ("Read", "file.read"), ("WebSearch", "web.search")),
                 "codex": (("bash", "shell"), ("edit", "file.edit"), ("grep", "search"),
                           ("read", "file.read"), ("web.search", "web.search"))}
    at = T0
    for agent, calls in spellings.items():
        for s in range(2):
            uid = f"{agent}-{s}"
            orbit.session(uid, agent=agent)
            for i, (name, kind) in enumerate(calls):
                for k in range(i + 1):  # Bash ×1 … WebSearch ×5 per session.
                    at += 1000
                    failed = agent == "codex" and k == 0
                    orbit.call(uid, name=name, kind=kind, at=at, head="ls" if kind == "shell" else None,
                                status="failed" if failed else "success",
                                approval="approved" if agent == "codex" and kind == "shell" else None,
                                wait=6000 if agent == "codex" and kind == "shell" else None)
    body = build(conn)
    rows = {t["key"]: t for t in body["tools"]}
    assert set(rows) == {"bash", "edit", "grep", "read", "websearch"}
    assert body["header"]["tool_kinds"] == 5
    for i, key in enumerate(("bash", "edit", "grep", "read", "websearch")):
        row = rows[key]
        assert row["n"] == 2 * 2 * (i + 1) and row["failed"] == 2 and row["known"] == row["n"]
        assert row["err"] == pytest.approx(2 / row["n"]) and sum(row["daily"]) == row["n"]
        cc, cx = spellings["claude_code"][i][0], spellings["codex"][i][0]
        assert sorted((a["name"], a["agents"], a["n"]) for a in row["aliases"]) == sorted(
            [(cc, ["claude_code"], row["n"] // 2), (cx, ["codex"], row["n"] // 2)])
        assert row["name"] in (cc, cx)
        for name in (key, cc, cx, cc.upper()):
            got = toolcalls.query(conn, {"name": name}, limit=200)["items"]
            assert len(got) == row["n"], name
            failed = toolcalls.query(conn, {"name": name, "status": "failed"}, limit=200)["items"]
            assert len(failed) == row["failed"], name
    assert sum(r["n"] for r in rows.values()) == body["header"]["calls"]
    assert sum(r["failed"] for r in rows.values()) == body["kpis"]["error_rate"]["failed"]
    assert rows["bash"]["approval_rate"] == pytest.approx(0.5)  # codex's bash calls only.
    asked = body["kpis"]["approvals"]["count"]
    assert asked == round(sum(r["approval_rate"] * r["n"] for r in rows.values())) == 2
    assert {b["bucket"]: b["n"] for b in body["approval"]["histogram"]}["5–15s"] == asked
    assert toolcalls.tool_name_spellings("WebSearch") == ["web.search", "web_search", "websearch"]
    assert toolcalls.tool_name_key("MultiEdit") == "multiedit"
    kinds = {t["key"] for t in build(conn, params={"group_by": "kind"})["tools"]}
    assert kinds == {"shell", "file.edit", "search", "file.read", "web.search"}


def test_retries(orbit, conn):
    orbit.session("a")
    for i in range(3):
        orbit.call("a", head="npm", status="failed", digest="d1", at=T0 + i,
                    command="npm run build")
    orbit.call("a", head="npm", status="success", digest="d1", at=T0 + 3)
    orbit.call("a", head="pytest", status="failed", digest="x1", at=T0 + 4)
    orbit.call("a", head="pytest", status="failed", digest="x2", at=T0 + 5)
    rows = build(conn)["retries"]
    assert rows == [{"command": "npm run build", "count": 2, "max_run": 3,
                     "session_uids": ["a"]}]


def test_failure_classification(orbit, conn):
    orbit.session("a")
    orbit.call("a", status="failed", error_class="timeout_hard", result="bash: x: command not found")
    orbit.call("a", status="failed", result="Permission denied: /etc/hosts")
    orbit.call("a", status="failed", result=f"usage: tool [-x] token={SECRET} " + "y" * 400)
    orbit.call("a", status="failed", result="bash: foo: command not found")
    orbit.call("a", status="success", result="Permission denied but retried ok")
    orbit.call("a", status="unknown", result="timeout")
    f = build(conn)["failures"]
    assert f["total"] == 4 and f["unknown_status"] == 1
    by = {(r["source"], r["key"]): r for r in f["rows"]}
    assert set(by) == {("error_class", "timeout_hard"), ("text_rule", "permission"),
                       ("text_rule", "arguments"), ("text_rule", "env_missing")}
    assert by[("text_rule", "permission")]["n"] == 1  # The successful call is not counted.
    typical = by[("text_rule", "arguments")]["typical"]
    assert len(typical) <= 200 and SECRET not in typical
    assert sum(r["share"] for r in f["rows"]) == pytest.approx(1)


def test_approvals(orbit, conn):
    orbit.session("cc")
    orbit.call("cc", head="ls")
    orbit.session("cx", agent="codex")
    orbit.call("cx", head="ls", approval="approved", wait=4999)
    orbit.call("cx", head="cat", approval="approved", wait=5000)
    orbit.call("cx", head="rm", approval="denied", wait=400_000)
    orbit.call("cx", head="git", approval="approved")
    body = build(conn)
    assert body["coverage"]["approval_agents_without"] == ["claude_code"]
    hist = {b["bucket"]: b["n"] for b in body["approval"]["histogram"]}
    assert hist["<5s"] == 1 and hist["5–15s"] == 1 and hist[">5m"] == 1
    assert body["approval"]["half_bucket"] == "5–15s"
    assert body["approval"]["readonly_prompted"]["n"] == 2
    k = body["kpis"]["approvals"]
    assert (k["count"], k["timed_n"], k["median_wait_ms"]) == (4, 3, 5000)
    assert tools.wait_bucket(4999) == "<5s" and tools.wait_bucket(5000) == "5–15s"


def test_readonly_prompted_counts_only_truly_readonly_commands(orbit, conn):
    """UT-07: a prompted ``find -delete`` / ``git branch -D`` / ``sed -i`` is not read-only, so
    it must not feed readonly_prompted or the 「只读命令自动放行」 automation."""
    orbit.session("cx", agent="codex")
    orbit.call("cx", head="find", command="find . -name '*.log' -delete", approval="approved")
    orbit.call("cx", head="git branch", command="git branch -D old", approval="approved")
    orbit.call("cx", head="sed", command="sed -i 's/a/b/' x.txt", approval="approved")
    orbit.call("cx", head="echo", command="echo hi > out.txt", approval="approved")
    body = build(conn)
    assert body["approval"]["readonly_prompted"]["n"] == 0
    assert all(a["kind"] != "permission_rule" for a in body["automation"])
    orbit.call("cx", head="sed", command="sed -n '1,5p' x.txt", approval="approved")
    orbit.call("cx", head="git branch", command="git branch -a", approval="approved")
    body = build(conn)
    heads = {h["head"]: h["n"] for h in body["approval"]["readonly_prompted"]["heads"]}
    assert heads == {"sed": 1, "git branch": 1}
    assert any(a["kind"] == "permission_rule" and a["count"] == 2 for a in body["automation"])


def test_parallel(orbit, conn):
    orbit.session("p")
    orbit.session("k0", kind="subagent", parent="p", started=T0, status="interrupted")
    orbit.session("k1", kind="subagent", parent="p", started=T0 + 2000)
    orbit.session("k2", kind="subagent", parent="p", started=T0 + 5000)
    orbit.session("k3", kind="subagent", parent="p", started=T0 + 60_000)
    par = build(conn)["parallel"]
    buckets = {b["degree"]: b for b in par["buckets"]}
    assert buckets["3"] == {"degree": "3", "n": 3, "stopped": 1}
    assert buckets["1"]["n"] == 1 and par["max"] == 3
    assert par["stopped_share_ge4"]["value"] is None


def test_mcp_inventory_merge(orbit, conn):
    orbit.session("a")
    orbit.call("a", name="mcp__pw__click", kind="mcp", mcp_server="pw", status="failed")
    inventory = [
        {"type": "mcp", "name": "pw", "config_path": "/c/a.json", "inv_id": "i1",
         "status": "active", "resident": {"tokens_est": None, "basis": "unknown"}},
        {"type": "mcp", "name": "idle", "config_path": "/c/a.json", "inv_id": "i2",
         "status": "unused", "resident": {"tokens_est": None, "basis": "unknown"}},
        {"type": "mcp", "name": "idle", "config_path": "/c/a.json", "inv_id": "i3",
         "status": "unused", "resident": {"tokens_est": None, "basis": "unknown"}},
        {"type": "skill", "name": "x", "config_path": "/c/s.md", "inv_id": "i4"},
    ]
    body = build(conn, inventory=inventory)
    servers = {m["server"]: m for m in body["mcp"]}
    assert set(servers) == {"pw", "idle"}
    assert servers["idle"]["calls"] == 0 and servers["idle"]["status"] == "unused"
    assert servers["idle"]["resident_tokens"] is None and servers["idle"]["inv_id"] == "i2"
    assert servers["pw"]["calls"] == 1 and servers["pw"]["err"] == 1
    assert {"kind": "removal", "title": "移除闲置 MCP", "count": 1,
            "candidate_id": None} in body["automation"]
    assert build(conn)["mcp"][0]["status"] == "unscanned"
    assert servers["idle"]["tools"] == []
    assert servers["pw"]["tools"] == [{"name": "click", "raw": ["mcp__pw__click"], "n": 1,
                                       "failed": 1, "known": 1, "unknown": 0, "err": 1}]


def test_mcp_tools_per_server(orbit, conn):
    orbit.session("a")
    for i, (name, status) in enumerate([
            ("mcp__codex_apps__github_search", "success"),
            ("mcp__codex_apps__github_search", "failed"),
            ("codex_apps.github_search", "success"),   # another agent's spelling: same tool
            ("mcp__codex_apps__fetch", "unknown"),
            ("mcp__pw__click", "success")]):
        server = "pw" if "pw" in name else "codex_apps"
        orbit.call("a", name=name, kind="mcp", mcp_server=server, status=status, at=T0 + i)
    servers = {m["server"]: m for m in build(conn)["mcp"]}
    ca = servers["codex_apps"]
    assert ca["calls"] == 4 and ca["failed"] == 1
    assert [(t["name"], t["n"], t["failed"], t["known"]) for t in ca["tools"]] == [
        ("github_search", 3, 1, 3), ("fetch", 1, 0, 0)]
    assert ca["tools"][0]["raw"] == ["codex_apps.github_search", "mcp__codex_apps__github_search"]
    assert ca["tools"][0]["err"] == pytest.approx(1 / 3) and ca["tools"][1]["err"] is None
    assert sum(t["n"] for t in ca["tools"]) == ca["calls"]
    assert [t["name"] for t in servers["pw"]["tools"]] == ["click"]


def test_mcp_tools_without_name_fold_into_one(orbit, conn):
    orbit.session("a")
    for i, name in enumerate(["", "mcp__pw__", "mcp__pw__click"]):
        orbit.call("a", name=name, kind="mcp", mcp_server="pw", status="success", at=T0 + i)
    tools = {m["server"]: m for m in build(conn)["mcp"]}["pw"]["tools"]
    assert [(t["name"], t["n"], t["raw"]) for t in tools] == [
        (None, 2, ["mcp__pw__"]), ("click", 1, ["mcp__pw__click"])]


def test_prev_delta_and_trend(orbit, conn):
    orbit.session("a", started=T0)
    lo, hi = T0 + 10 * DAY, T0 + 20 * DAY
    for i in range(4):
        orbit.call("a", at=lo - DAY - i, status="failed" if i == 0 else "success")
    for i in range(6):
        orbit.call("a", at=lo + DAY + i, approval="approved" if i < 2 else None)
    orbit.call("a", at=lo - 30 * DAY)  # Outside both windows, inside the 12-week trend.
    k = build(conn, Scope(from_ts=lo, until_ts=hi))["kpis"]
    assert (k["calls"]["value"], k["calls"]["prev"], k["calls"]["delta"]) == (6, 4, 2)
    assert k["error_rate"]["prev"] == pytest.approx(0.25)
    assert k["error_rate"]["delta"] == pytest.approx(-0.25)
    assert (k["approvals"]["count"], k["approvals"]["prev"]) == (2, 0)
    assert len(k["calls"]["trend"]) == 12 and sum(w["value"] for w in k["calls"]["trend"]) == 11
    assert build(conn)["kpis"]["calls"]["prev"] is None


def test_week_buckets_and_scope_where():
    weeks = common.week_buckets(NOW)
    assert len(weeks) == 12 and weeks[-1][1] == NOW and weeks[0][0] == NOW - 84 * DAY
    assert common.prev_window(10, 20) == (0, 10) and common.prev_window(None, 20) is None
    sql, params = common.scope_where(Scope(project_ids=[]), "s")
    assert "json_each" in sql and params == ["[]"]
    assert common.scope_where(Scope(), "s") == ("1", [])


def test_route(orbit, gateway, client):
    build_standard(orbit)
    assert client.get("/v1/uiview/tools").json()["meta"]["reason"] == "no_projection"
    gateway.revisions.update(data_rev=7)
    first = client.get("/v1/uiview/tools")
    assert first.status_code == 200
    body = first.json()
    assert body["meta"]["contract"] == "orbit-uiview-a4a6-v1" and body["meta"]["data_rev"] == 7
    assert body["meta"]["source"] == "computed" and body["header"]["calls"] == 566
    assert body["meta"]["coverage"]["approval_agents_without"] == ["claude_code"]
    again = client.get("/v1/uiview/tools").json()
    assert again["meta"]["source"] == "cache" and again["header"] == body["header"]

    assert client.post("/v1/sessions/s00/exclude").status_code == 200
    excluded = client.get("/v1/uiview/tools").json()
    assert excluded["meta"]["source"] == "computed"
    assert excluded["header"]["calls"] == 566 - 15 and excluded["header"]["sessions"] == 39
    assert excluded["parallel"]["max"] == 0  # s00's sub-agents go with it.

    codex = client.get("/v1/uiview/tools", params={"agent": "codex", "group_by": "kind"}).json()
    assert codex["header"]["sessions"] == 10
    assert {t["key"] for t in codex["tools"]} <= {"file.read", "search", "file.edit", "shell",
                                                   "mcp", "subagent"}
    assert client.get("/v1/uiview/tools", params={"from_ts": 5, "until_ts": 1}).status_code == 422
    assert client.get("/v1/uiview/tools", params={"group_by": "x"}).status_code == 422
    gateway.revisions.update(data_rev=8)
    assert client.get("/v1/uiview/tools").json()["meta"]["source"] == "computed"


def test_register_all_skips_missing_modules():
    class Api:
        def __init__(self):
            self.paths = []

        def get(self, path):
            self.paths.append(path)
            return lambda fn: fn

    api = Api()
    loaded = common.register_all(api, gw=None)
    assert "a4a6_tools" in loaded and "/v1/uiview/tools" in api.paths


def test_cache_key_names_home_and_data_identity(tmp_path):
    """The process-wide CACHE must not serve one gateway's result to another home, nor a
    pre-wipe result after clear-all-data restarts projection_run ids at the same data_rev."""
    scope, params = Scope(), {"group_by": "tool"}
    rev = {"data_rev": 1, "inventory_rev": 0, "counts": {"sessions": 5, "events": 40, "projects": 1}}
    a = common.cache_key("tools", scope, params, rev, home=tmp_path / "a")
    assert a == common.cache_key("tools", scope, params, dict(rev), home=tmp_path / "a")
    assert a != common.cache_key("tools", scope, params, rev, home=tmp_path / "b")
    reimported = {**rev, "counts": {"sessions": 3, "events": 12, "projects": 1}}  # same run id 1
    assert a != common.cache_key("tools", scope, params, reimported, home=tmp_path / "a")
    assert a != common.cache_key("tools", scope, params, {**rev, "data_rev": 2}, home=tmp_path / "a")
    lru = common.LRU(4)
    lru.put(a, {"from": "a"})
    assert lru.get(common.cache_key("tools", scope, params, rev, home=tmp_path / "b")) is None
