"""Round-5 uiview wiring: every ``/v1/uiview/*`` route on the real gateway app, facts aux
units / mood / Kimi name, facet + ``agents=`` filters on tools / projects / sentiment, and the
share card reading the A2 persona payload. Synthetic orbit.db under tmp_path only."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from orbit_data import MAPPER_VERSION, REDUCER_VERSION

from orbit_backend.exporting import sharecard
from orbit_backend.services.gateway import Gateway
from orbit_backend.services.sections import SECTIONS, rules_digest
from orbit_backend.services.snapshots import SnapshotKey, scope_hash
from orbit_backend.services.supervisor import SupervisorConfig
from orbit_backend.sessionops import exclusion
from orbit_backend.uiview import a4a6_common, facts, fetch, persona

from .a4a6_ps_fixture import HOUR, T0, Orbit, ro
from .synth import TODAY, analysed

TOKEN = "synthetic-test-token-0123456789abcdef"
PORT = 8765


# -- facts payload -----------------------------------------------------------------------

def test_wire_rows_carry_persona_units():
    body = analysed()[4]
    wire = facts.compact(body)
    assert set(facts.AUX_KEYS) <= set(wire["fields"]) | set(wire["constants"])
    rows = facts.expand(wire)
    by_id = {r["id"]: r for r in rows}
    for uid, a in body["aux"].items():
        r = by_id[uid]
        assert r["dn"] == len(a["turns"]) and r["op"] == a["open"]
        assert r["t0"] == a["t0"] and r["t1"] == a["t1"]
    # The client can rebuild D / I / V on any subset from the row units alone.
    subset = [r for r in body["rows"] if r["a"] == "codex"]
    units = persona.units(subset, body["aux"])
    wired = [by_id[r["id"]] for r in subset]
    assert units["D"] == (sum(r["dk"] for r in wired), sum(r["dn"] for r in wired))
    assert units["V"] == (sum(r["vk"] for r in wired), sum(r["dn"] for r in wired))
    opens = [r["op"] for r in wired if r["op"] is not None]
    assert units["I"] == (opens.count(0), len(opens))


def test_aux_units_without_aux_are_null():
    assert facts.aux_units(None) == dict.fromkeys(facts.AUX_KEYS)
    assert facts.aux_units({"turns": [[5, 1], [4, 0], [9, 1]], "open": 1, "t0": 1, "t1": 2}) == \
        {"dk": 2, "dn": 3, "vk": 2, "op": 1, "t0": 1, "t1": 2}


def test_kimi_agent_name():
    assert facts.AGENT_NAMES["kimi"] == ("Kimi CLI", "Kimi")
    assert facts._agents([{"a": "kimi"}])[0] == {"id": "kimi", "name": "Kimi CLI",
                                                  "short": "Kimi", "n": 1}


def test_mood_is_session_balance(tmp_path):
    t = Orbit(tmp_path)
    for uid in ("m1", "m2", "m3"):
        t.session(uid)
    t.human("m1", "我很开心", ts=T0)
    t.human("m1", "我很开心", ts=T0 + 1)
    t.human("m1", "我很失望", ts=T0 + 2)
    t.human("m2", "帮我写一个接口", ts=T0)
    conn = ro(t.path)
    moods = facts._moods(conn, ["m1", "m2", "m3"])
    conn.close()
    t.close()
    assert moods == {"m1": round(1 / 3, 3)}  # m2: no emotion signal, m3: no messages → null


# -- real gateway --------------------------------------------------------------------------

def seed(t: Orbit) -> None:
    t.db.execute("INSERT INTO projection_run VALUES (1, 1, ?, ?, 0, 0, 0)",
                 (MAPPER_VERSION, REDUCER_VERSION))
    for pid in ("p1", "p2"):
        t.project(pid)
    for i in range(6):
        uid = f"s{i}"
        t.session(uid, project="p1" if i % 2 == 0 else "p2",
                  agent="codex" if i >= 4 else "claude_code", start=T0 + i * HOUR)
        t.human(uid, "我很开心" if i % 2 == 0 else "我很失望", ts=T0 + i * HOUR)
        t.call(uid, name="Bash", head="pytest", ts=T0 + i * HOUR + 1000,
               status="failed" if i == 1 else "ok")


def fact_row(i: int) -> dict:
    row = dict.fromkeys(facts.ROW_KEYS)
    row.update(id=f"s{i}", d="2025-10-09", h=9 + i, mi=0, a="codex" if i >= 4 else "claude_code",
               p="p1" if i % 2 == 0 else "p2", topic="git" if i < 2 else "data",
               out="ok", tools=1, msgs=1, steps=1, live=False, excluded=False)
    return row


@pytest.fixture
def gw(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    t = Orbit(home)
    seed(t)
    t.close()
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, tick_s=0.05)
    gateway = Gateway(home, config=config, discovery=lambda: [], prewarm_debounce_s=3600.0)
    gateway.revisions.update(data_rev=1)  # workers are not started; publish a revision
    a4a6_common.CACHE.items.clear()
    client = TestClient(gateway.app(token=TOKEN, port=PORT), base_url=f"http://127.0.0.1:{PORT}",
                        headers={"Authorization": f"Bearer {TOKEN}"})
    gateway.client = client
    yield gateway
    exclusion.set_provider(None)
    gateway.close()


def put_facts(gw, n: int = 6) -> None:
    rev = gw.revisions.snapshot()
    assert rev["data_rev"] is not None
    rows = [fact_row(i) for i in range(n)]
    body = {"contract": facts.CONTRACT, "rows": rows,
            "aux": {r["id"]: {"t0": T0, "t1": T0 + 1, "turns": [[6, 1]], "open": 1, "tools": {}}
                    for r in rows},
            "meta": {"display_timezone": "UTC"}, "agents": facts._agents(rows),
            "projects": [{"id": "p1", "name": "p1", "path": None, "n": 3}]}
    key = SnapshotKey(fetch.SECTION, scope_hash(fetch.default_scope(), {}), rev["data_rev"],
                      rev["inventory_rev"], rules_digest())
    gw.snapshots.put(key, json.loads(json.dumps(body)))


def test_every_uiview_route_answers_on_the_gateway(gw):
    assert "uiview_facts" in SECTIONS
    put_facts(gw)
    paths = sorted({r.path for r in gw.client.app.routes
                    if getattr(r, "path", "").startswith("/v1/uiview")})
    calls = {"/v1/uiview/sessions/compare": {"a": "s0", "b": "s2"},
             "/v1/uiview/overview": {"today": "2025-10-10"},
             "/v1/uiview/persona": {"today": "2025-10-10"},
             "/v1/uiview/persona/reveal": {"today": "2025-10-10"}}
    expected = {"/v1/uiview/facts", "/v1/uiview/overview", "/v1/uiview/persona",
                "/v1/uiview/persona/reveal", "/v1/uiview/sessions",
                "/v1/uiview/sessions/compare", "/v1/uiview/sessions/{session_uid}",
                "/v1/uiview/sessions/{session_uid}/suggest_b", "/v1/uiview/tools",
                "/v1/uiview/projects", "/v1/uiview/projects/{project_id}",
                "/v1/uiview/sentiment"}
    assert expected <= set(paths)
    for path in paths:
        url = path.replace("{session_uid}", "s0").replace("{project_id}", "p1")
        r = gw.client.get(url, params=calls.get(path, {}))
        assert r.status_code in (200, 202), (path, r.status_code, r.text[:300])
    wire = gw.client.get("/v1/uiview/facts").json()
    assert wire["meta"]["freshness"] == "fresh" and len(wire["rows"]) == 6
    # Session rows are overlaid with the cached fact rows (topic comes from facts only).
    listed = gw.client.get("/v1/uiview/sessions", params={"topic": "git"}).json()["rows"]
    assert sorted(r["id"] for r in listed) == ["s0", "s1"]


def test_openapi_lists_every_uiview_route(gw):
    """The real gateway app renders its schema: a function-local ``Annotated`` alias under
    ``from __future__ import annotations`` used to stay ForwardRef('many') → 500."""
    r = gw.client.get("/v1/openapi.json")
    assert r.status_code == 200, r.text[:300]
    spec = r.json()
    routes = {route.path for route in gw.client.app.routes
              if getattr(route, "path", "").startswith("/v1/uiview")}
    assert routes and routes <= set(spec["paths"])
    for path in ("/v1/uiview/projects", "/v1/uiview/projects/{project_id}",
                 "/v1/uiview/sentiment", "/v1/uiview/tools"):
        params = {p["name"]: p for p in spec["paths"][path]["get"]["parameters"]}
        assert params["agent"]["in"] == "query"
        assert '"array"' in json.dumps(params["agent"]["schema"]), (path, params["agent"])


def test_catalog_status_has_one_route_and_preserves_gateway_fields(gw):
    status_routes = [route for route in gw.client.app.routes
                     if getattr(route, "path", "") == "/v1/catalog/status"
                     and "GET" in getattr(route, "methods", set())]
    assert len(status_routes) == 1
    response = gw.client.get("/v1/catalog/status")
    assert response.status_code == 200
    assert {"coverage", "first_sync"} <= set(response.json())
    spec = gw.client.get("/v1/openapi.json").json()
    assert "get" in spec["paths"]["/v1/catalog/status"]


def test_facets_and_agents_filter_a4a6_pages(gw):
    put_facts(gw)
    c = gw.client
    tools = c.get("/v1/uiview/tools", params={"topic": "git"}).json()
    assert tools["header"]["sessions"] == 2 and tools["header"]["calls"] == 2
    assert c.get("/v1/uiview/tools", params={"hour": 9}).json()["header"]["sessions"] == 1
    assert c.get("/v1/uiview/tools", params={"agents": "codex"}).json()["header"]["sessions"] == 2
    assert c.get("/v1/uiview/tools",
                 params={"agent": "codex"}).json()["header"]["sessions"] == 2  # alias
    assert c.get("/v1/uiview/tools", params={"topic": "data", "agents": "codex,claude_code"}
                 ).json()["header"]["sessions"] == 4
    assert c.get("/v1/uiview/tools", params={"fric": "方向错误"}).json()["header"]["calls"] == 0

    projects = c.get("/v1/uiview/projects", params={"topic": "git"}).json()
    assert projects["meta"]["n_sessions"] == 2
    assert c.get("/v1/uiview/projects",
                 params={"agents": "codex"}).json()["meta"]["n_sessions"] == 2

    since, until = T0 - HOUR, T0 + 10 * HOUR
    window = {"since": since, "until": until}
    assert c.get("/v1/uiview/sentiment", params=window).json()["meta"]["n_sessions"] == 6
    assert c.get("/v1/uiview/sentiment", params={**window, "outcome": "ok", "topic": "git"}
                 ).json()["meta"]["n_sessions"] == 2
    assert c.get("/v1/uiview/sentiment", params={**window, "agents": "codex"}
                 ).json()["meta"]["n_sessions"] == 2


def test_facets_wait_for_facts(gw):
    r = gw.client.get("/v1/uiview/tools", params={"topic": "git"})
    assert r.status_code == 202 and r.json()["meta"]["freshness"] == "computing"
    assert gw.client.get("/v1/uiview/tools").status_code == 200  # no facet: no facts needed


# -- empty home ------------------------------------------------------------------------------

EMPTY_LISTS = ("/v1/sessions", "/v1/projects", "/v1/sources")
EMPTY_DICTS = ("/v1/inventory", "/v1/analytics/tool_calls", "/v1/uiview/sessions",
               "/v1/uiview/projects", "/v1/uiview/sentiment")
ALREADY_EMPTY = ("/v1/uiview/facts", "/v1/uiview/overview", "/v1/uiview/persona",
                 "/v1/uiview/persona/reveal", "/v1/uiview/tools", "/v1/sessions/excluded")
BY_ID = ("/v1/sessions/s0/events", "/v1/sessions/s0/resume", "/v1/sessions/s0/source_location",
         "/v1/uiview/sessions/s0", "/v1/uiview/sessions/s0/suggest_b",
         "/v1/uiview/projects/p1")


def _client(home):
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, tick_s=0.05)
    gateway = Gateway(home, config=config, discovery=lambda: [], prewarm_debounce_s=3600.0)
    return gateway, TestClient(gateway.app(token=TOKEN, port=PORT),
                               base_url=f"http://127.0.0.1:{PORT}",
                               headers={"Authorization": f"Bearer {TOKEN}"})


def test_empty_home_lists_answer_200_with_the_populated_shape(gw, tmp_path, monkeypatch):
    """Before the first import (no orbit.db) lists and summaries are an empty state:
    200 with the same keys as with data, plus freshness ``none``; ids are 404."""
    monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
    empty_gw, client = _client(tmp_path / "empty-home")
    try:
        assert not (tmp_path / "empty-home" / "orbit.db").exists()
        for path in EMPTY_LISTS:
            r = client.get(path)
            assert r.status_code == 200 and r.json() == [], (path, r.status_code, r.text[:200])
            assert r.headers["x-orbit-freshness"] == "none"
        assert client.get("/v1/sessions").headers["x-total-count"] == "0"
        for path in EMPTY_DICTS:
            r = client.get(path)
            assert r.status_code == 200, (path, r.status_code, r.text[:200])
            body = r.json()
            assert body["meta"]["freshness"] == "none", path
            assert body["meta"]["reason"] == "no_projection", path
            full = gw.client.get(path).json()  # same route on the seeded home
            assert set(body) - {"meta"} == set(full) - {"meta"}, (path, set(body) ^ set(full))
            assert set(full.get("meta") or {}) <= set(body["meta"]), path
        assert client.get("/v1/inventory").json()["items"] is None
        assert client.get("/v1/analytics/tool_calls").json()["items"] == []
        assert client.get("/v1/uiview/sessions").json()["rows"] == []
        assert client.get("/v1/uiview/projects").json()["projects"] == []
        assert client.get("/v1/uiview/sentiment").json()["meta"]["n_sessions"] == 0
        for path in ALREADY_EMPTY:
            assert client.get(path).status_code == 200, path
        for path in BY_ID:
            r = client.get(path)
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", path
        assert not (tmp_path / "empty-home" / "orbit.db").exists()  # reads never create it

        # orbit.db exists but nothing is published yet (first import still publishing):
        # transient, so still a retryable 503 and never the earlier empty body as stale.
        from orbit_data.store import Store

        with Store(tmp_path / "empty-home"):
            pass
        for path in (*EMPTY_LISTS[:2], "/v1/analytics/tool_calls", "/v1/uiview/projects",
                     "/v1/uiview/sentiment"):
            r = client.get(path)
            assert r.status_code == 503, (path, r.status_code, r.text[:200])
            assert r.json()["error"]["code"] == "projection_pending" and r.headers["retry-after"]
    finally:
        empty_gw.close()


# -- share card ------------------------------------------------------------------------------

def test_share_card_matches_uiview_persona():
    p = persona.page(analysed()[4], {"period": "all"}, TODAY)
    result = sharecard.payload(p)
    assert result["gate"]["sessions"] == p["n"] and result["gate"]["active_days"] == p["days"]
    assert [a["n_units"] for a in result["gate"]["axes"]] == [a["n_units"] for a in p["axes"]]
    assert result["code"] == (p["code"] if result["eligible"] else None)
    assert sharecard.payload(None)["blocked_reason"] == "persona_unavailable"


def test_share_card_route_reads_the_persona_payload(gw):
    put_facts(gw)
    card = gw.client.post("/v1/export/share_card", json={"save": False}).json()
    assert card["blocked_reason"] == "insufficient_data"  # default 90-day window: 0 sessions
    assert card["gate"]["sessions"] is not None and card["method"] == persona.METHOD


def test_one_session_persona_over_the_gateway(gw):
    """A single session is enough: the route returns a full four-letter code (bug 4)."""
    put_facts(gw, n=1)
    q = {"today": "2025-10-10", "period": "all"}
    body = gw.client.get("/v1/uiview/persona", params=q).json()
    assert body["ok"] and body["n"] == 1 and body["classified"]
    assert len(body["code"]) == 4 and "?" not in body["code"]
    assert body["hint"] == "基于 1 个会话，数据越多越准"
    reveal = gw.client.get("/v1/uiview/persona/reveal", params=q).json()
    assert reveal["ok"] and reveal["code"] == body["code"]
    assert reveal["candidates"][0]["code"] == body["code"]
