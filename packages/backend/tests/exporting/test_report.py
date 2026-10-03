"""Report assembly: numbers come from the section snapshots, never fabricated (EXP-01)."""

from __future__ import annotations

import copy

import pytest

from orbit_backend.exporting import report, sharecard
from orbit_backend.services.snapshots import scope_hash

OVERVIEW = {"coverage": {"events": {"status": "available"}, "tool_calls": {"status": "partial"}},
            "overview": {"counts": {"sessions": 12, "main_sessions": 10, "human_messages": 40,
                                    "turns": 30, "correction_signals": 3,
                                    "correction_signal_rate": 0.075},
                         "usage": {"request_count": 50, "total_tokens": 123456, "cost_usd": 1.25},
                         "activity_rhythm": {"active_days": 12},
                         "top_tools": [{"name_raw": "Bash", "call_count": 20}]}}
TOTALS = {"call_count": 30, "known_failure_count": 3, "success_rate": 0.9, "failure_rate": 0.1,
          "median_duration_ms": 120, "rejected_count": 1, "interrupted_count": 0}
TOOLS = {"coverage": {"tool_calls": {"status": "available"}},
         "tools": {"effective_n": 30, "totals": TOTALS,
                   "by_tool": [{"name_raw": "Bash", "kind": "builtin", "call_count": 20,
                                "known_failure_count": 2, "success_rate": 0.9,
                                "failure_rate": 0.1, "median_duration_ms": 99}]}}
PROJECTS = {"coverage": {}, "projects": [
    {"name": "/Users/alice/work/app", "project_id": "p1", "session_count": 8,
     "main_session_count": 7, "human_message_count": 30, "usage": {"total_tokens": 1000}},
    {"name": "lib", "project_id": "p2", "session_count": 2, "main_session_count": 2,
     "human_message_count": None, "usage": {"total_tokens": None}}]}


@pytest.fixture
def sections(monkeypatch):
    state = {"overview": (OVERVIEW, "fresh"), "tools": (TOOLS, "fresh"),
             "projects": (PROJECTS, "stale")}

    def fetch(gw, names, scope_dict, wait_ms=3000):
        return ({n: state.get(n, (None, "computing")) for n in names},
                scope_hash(scope_dict, {}))

    monkeypatch.setattr(report, "fetch_sections", fetch)
    return state


def post(client, **body):
    response = client.post("/v1/export/report", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def by_id(body):
    return {s["id"]: s for s in body["sections"]}


def test_numbers_equal_section_data(env, sections):
    client, _, _ = env
    body = post(client, save=False)
    assert body["snapshot_id"] is None and body["format"] == "markdown"
    assert [s["id"] for s in body["sections"]] == list(report.DEFAULT_SECTIONS)
    s = by_id(body)
    counts, usage = OVERVIEW["overview"]["counts"], OVERVIEW["overview"]["usage"]
    assert s["overview"]["data"]["main_sessions"] == counts["main_sessions"]
    assert s["overview"]["data"]["total_tokens"] == usage["total_tokens"]
    metrics = {r["id"]: r["value"] for r in s["metrics"]["data"]["rows"]}
    assert metrics == {**{k: counts[k] for k in ("sessions", "main_sessions", "human_messages",
                                                 "turns", "correction_signals",
                                                 "correction_signal_rate")},
                       **usage, "active_days": 12}
    assert s["tools"]["data"]["totals"] == {k: TOTALS[k] for k in report.TOOL_FIELDS}
    assert s["friction"]["data"]["tool_failures"] == TOTALS["known_failure_count"]
    assert s["friction"]["data"]["rejected"] == 1
    projects = s["projects"]["data"]
    assert projects["project_count"] == 2 and projects["rows"][0]["session_count"] == 8
    assert "alice" not in projects["rows"][0]["project"]
    assert s["projects"]["freshness"] == "stale"
    assert s["overview"]["coverage"] == {"events": "available", "tool_calls": "partial"}
    md = body["markdown"]
    assert md.startswith("# Orbit 协作报告\n") and "Tandem" not in md  # orbit-rename: keep
    assert md.count("\n## ") == len(report.DEFAULT_SECTIONS) + 1
    assert "## 口径与限制" in md and "123,456" in md and "7.5%" in md
    assert s["recommendations"]["status"] == "unavailable"


def test_computing_and_unavailable_show_no_numbers(env, sections):
    client, _, _ = env
    sections["tools"] = (None, "computing")
    sections["projects"] = (None, "none")
    s = by_id(post(client, sections=["tools", "friction", "projects"], format="json"))
    for sid, status in (("tools", "computing"), ("friction", "computing"),
                        ("projects", "unavailable")):
        assert s[sid]["status"] == status and s[sid]["data"] is None and s[sid]["n"] is None
        assert not any(ch.isdigit() for ch in s[sid]["markdown"])


def test_insufficient_prints_marker(env, sections):
    client, _, _ = env
    small = copy.deepcopy(OVERVIEW)
    small["overview"]["counts"]["main_sessions"] = 3
    sections["overview"] = (small, "fresh")
    body = post(client, sections=["overview", "metrics"])
    for section in body["sections"]:
        assert section["status"] == "insufficient" and section["n"] == 3
        assert report.INSUFFICIENT in section["markdown"]
    assert "markdown" in body


def test_persona_reads_the_uiview_persona_like_share_card(env, sections, monkeypatch):
    from datetime import date

    from orbit_backend.uiview import persona

    client, _, _ = env
    today = date(2026, 9, 30)
    # Two sessions on one day: D 1 of 2 turns ≥ 5 steps = 50 → D; I 1 of 2 unstructured
    # openings = 50 → I; M overlap → 1 of 1 day = 100 → M; V 0 of 2 → 0 → T.
    body = {"meta": {}, "rows": [{"id": "a", "d": "2026-09-30", "a": "codex"},
                                 {"id": "b", "d": "2026-09-30", "a": "codex"}],
            "aux": {"a": {"turns": [[5, 0]], "open": 0, "t0": 0, "t1": 10},
                    "b": {"turns": [[1, 0]], "open": 1, "t0": 5, "t1": 15}},
            "agents": [{"id": "codex", "short": "Codex"}], "projects": []}
    page = persona.page(body, {"period": "30"}, today)
    monkeypatch.setattr(report, "persona_page", lambda gw, scope, wait_ms: (page, "fresh", []))
    s = by_id(post(client, sections=["persona"]))["persona"]
    assert s["status"] == "ok" and s["data"]["experimental"] and s["data"]["code"] == "DIMT"
    assert s["n"] == 2 and [a["value"] for a in s["data"]["axes"]] == [50.0, 50.0, 100.0, 0.0]
    card = sharecard.payload(page)
    assert card["eligible"] and card["code"] == s["data"]["code"]
    assert "实验性" in s["markdown"] and "DIMT" in s["markdown"]
    empty = persona.page({**body, "rows": []}, {"period": "30"}, today)
    monkeypatch.setattr(report, "persona_page", lambda gw, scope, wait_ms: (empty, "fresh", []))
    s = by_id(post(client, sections=["persona"]))["persona"]
    assert s["status"] == "insufficient" and s["data"] is None and s["n"] == 0
    monkeypatch.setattr(report, "persona_page",
                        lambda gw, scope, wait_ms: (None, "computing", []))
    assert by_id(post(client, sections=["persona"]))["persona"]["status"] == "computing"


def test_persona_request_maps_the_analytics_scope():
    now = 1_000 * 86_400_000
    facts_scope, params, notes = sharecard.persona_request(
        {"display_timezone": "UTC", "from_ts": now - 10 * 86_400_000, "until_ts": now,
         "project_ids": ["p1", "p2"]}, now)
    # 10 days back → period "10", served from the 30-day facts window.
    assert params == {"period": "10", "agents": None, "project": None, "vs": None}
    assert facts_scope["until_ts"] is None and facts_scope["from_ts"] is not None
    assert len(notes) == 2
    _, all_params, none = sharecard.persona_request({"project_ids": ["p1"]}, now)
    assert all_params["period"] == "all" and all_params["project"] == "p1" and none == []


def test_recommendations_titles_and_status(env, sections):
    client, gw, _ = env
    h = scope_hash(report.build_scope({}), {})
    with gw.appdb.write() as db:
        db.execute("INSERT INTO rec_run (run_id, scope_hash, scope, inputs_digest, "
                   "engine_version, status, created_at) VALUES ('r1', ?, '{}', 'd', 'e', 'ok', 1)",
                   (h,))
        for i, key in enumerate(("k1", "k2")):
            db.execute("INSERT INTO rec_candidate (candidate_id, run_id, rec_key, kind, dim, title,"
                       " rank, passed, card, created_at) VALUES (?, 'r1', ?, 'hook', 'hook', ?, ?,"
                       " 1, '{}', 1)", (f"c{i}", key, f"标题 {i}", i))
        db.execute("INSERT INTO rec_state (rec_key, status, updated_at) VALUES ('k1', 'installed', 1)")
    s = by_id(post(client, sections=["recommendations"]))["recommendations"]
    assert s["status"] == "ok" and s["n"] == 2
    assert s["data"]["items"] == [
        {"title": "标题 0", "kind": "hook", "status": "installed", "effect_status": "未测"},
        {"title": "标题 1", "kind": "hook", "status": "new", "effect_status": "未测"}]


def test_save_and_validation(env, sections):
    client, _, _ = env
    body = post(client, sections=["overview"])
    stored = client.get(f"/v1/export/snapshots/{body['snapshot_id']}").json()
    assert stored["kind"] == "report" and stored["payload"]["sections"] == body["sections"]
    assert stored["scope"] == body["scope"] and stored["scope_hash"] == body["scope_hash"]
    assert client.post("/v1/export/report", json={"sections": ["bogus"]}).status_code == 422
    assert client.post("/v1/export/report",
                       json={"scope": {"agent_ids": ["x"]}}).status_code == 422
