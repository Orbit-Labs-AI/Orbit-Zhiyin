import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbit_backend.analytics.inputs import AnalysisInputBundle, Scope
from orbit_backend.analytics.presentation import build_presentation
from orbit_backend.analytics.presentation.service import _tokens
from orbit_backend.analytics.service import analyze_bundle
from orbit_backend.api import create_app
from orbit_backend.cli import main


def fixture_bundle():
    raw = json.loads((Path(__file__).parents[1] / "fixtures/bottleneck-features-v1.json").read_text(encoding="utf-8"))
    for session in raw["sessions"]:
        session["agent"] = "codex"
    return AnalysisInputBundle.from_dict(raw)


def present(bundle, scope=None):
    return build_presentation(analyze_bundle(bundle, scope, with_text=False))


def test_all_eight_families_feed_serializable_immutable_sections():
    analysis = analyze_bundle(fixture_bundle(), Scope(display_timezone="Asia/Shanghai"), with_text=False)
    snapshot = copy.deepcopy(analysis)
    view = build_presentation(analysis)
    assert view["schema_version"] == "presentation-v2"
    assert view["overview"]["sessions"]["value"] == analysis["overview"]["counts"]["main_sessions"]
    assert view["overview"]["correction_rate"] == view["diagnostics"]["correction_rate"]
    assert view["tools"]["call_count"] >= 1
    assert view["projects"][0]["completion"]["value"] is None
    assert view["projects"][0]["declared_acceptance_sets"]
    assert "code" not in view["profile"]  # profile no longer claims a four-letter code
    assert view["resources"]["popular"]["value"] is None
    assert view["overview"]["collaboration_duration"]["value"] == sum(
        s["features"]["observed_session_span_ms"] for s in analysis["sessions"])
    assert view["overview"]["human_work_duration"]["value"] is None
    json.dumps(view, allow_nan=False)
    view["scope"]["display_timezone"] = "changed"
    assert analysis == snapshot


def test_missing_sources_and_true_empty_selection_remain_distinct():
    bundle = fixture_bundle()
    bundle.events = bundle.tool_calls = bundle.model_calls = None
    for name in ("events", "tool_calls", "model_calls"):
        bundle.coverage[name] = {"status": "unavailable"}
    view = present(bundle)
    assert view["overview"]["messages"]["value"] is None
    assert view["tools"]["call_count"] is None
    assert view["overview"]["activity"]["series"] is None
    assert view["timeline"] is None
    empty = present(fixture_bundle(), Scope(agent_ids=[]))
    assert empty["overview"]["sessions"]["value"] == 0
    assert empty["sessions"] == empty["projects"] == []
    assert empty["overview"]["correction_rate"]["value"] is None


def test_tool_exclusion_cannot_be_undone_by_retained_event_reconstruction():
    bundle = fixture_bundle()
    bundle.tool_calls = None
    bundle.coverage["tool_calls"] = {"status": "excluded"}
    view = present(bundle)
    assert view["tools"]["call_count"] is None
    assert view["tools"]["success_rate"]["value"] is None
    assert view["diagnostics"]["outcomes"]["objective"]["declared_task_results"] is None
    assert all(s["tool_calls"] is None for s in view["sessions"])
    assert all(p["declared_acceptance_sets"] is None for p in view["projects"])
    assert all(p["execution_time"]["value"] is None for p in view["projects"])


def test_activity_keeps_source_specific_partial_coverage_and_unknown_humans():
    bundle = fixture_bundle()
    bundle.coverage["tool_calls"]["status"] = "partial"
    for event in bundle.events:
        if event["kind"] == "message.user":
            event["attrs"]["origin"] = "unknown"
    view = present(bundle)
    series = view["overview"]["activity"]["series"]
    assert series["tool_calls"]["status"] == "partial"
    assert series["human_messages"]["status"] == "partial"
    assert series["human_messages"]["known_n"] == 0
    assert all(r["count"] is None for r in series["human_messages"]["by_hour"])


def test_session_sort_and_project_profile_never_reuse_unfiltered_global_rows():
    bundle = fixture_bundle()
    other = {**bundle.sessions[0], "session_uid": "later", "root_uid": "later", "project_id": "other", "agent": "claude_code"}
    bundle.sessions.append(other)
    latest = max(e["ts"] or 0 for e in bundle.events) + 1000
    bundle.events.append({"event_uid": "other-request", "session_uid": "later", "seq": 1,
                          "kind": "message.user", "actor": "human", "ts": latest, "turn_uid": "later-turn",
                          "text": "新任务：请先给方案，再修改 web.ts", "attrs": {"origin": "human"}})
    view = present(bundle)
    assert view["sessions"][0]["session_uid"] == "later"
    other_project = next(p for p in view["projects"] if p["project_id"] == "other")
    assert other_project["profile"]["task_distribution"]["task_count"] == 1
    assert other_project["agent_composition"]["rows"][0]["name"] == "claude_code"
    selected = present(bundle, Scope(agent_ids=["codex"]))
    assert all(s["agent"] == "codex" for s in selected["sessions"])
    assert all(p["project_id"] != "other" for p in selected["projects"])


def test_api_cli_and_python_share_exact_scope_and_computation(monkeypatch, tmp_path):
    bundle = fixture_bundle()

    class FixtureStore:
        path = tmp_path / "fixture.db"

        def analysis_bundle(self, scope):
            return bundle

    monkeypatch.setattr("orbit_backend.api.routes.Store", lambda _: FixtureStore())
    monkeypatch.setattr("orbit_backend.cli.commands.Store", lambda _: FixtureStore())
    client = TestClient(create_app(db=tmp_path / "unused.db"))
    end = max(e["ts"] or 0 for e in bundle.events) + 1
    response = client.get("/v1/analytics/presentation", params={"window": "7d", "until_ts": end,
                          "display_timezone": "Asia/Shanghai", "agent_ids": "codex"})
    assert response.status_code == 200, response.text
    output = tmp_path / "display.json"
    main(["--db", str(tmp_path / "unused.db"), "analytics", "--presentation", "--window", "7d",
          "--until-ts", str(end), "--display-timezone", "Asia/Shanghai", "--agent-id", "codex",
          "--output", str(output)])
    assert json.loads(output.read_text(encoding="utf-8")) == response.json()
    empty = client.get("/v1/analytics/presentation", params={"agent_ids": ""})
    assert empty.status_code == 200
    assert empty.json()["sessions"] == []
    for query in ({"window": "bad"}, {"window": "7d", "from_ts": 1},
                  {"window": "all", "until_ts": end}, {"display_timezone": "bad/zone"}):
        assert client.get("/v1/analytics/presentation", params=query).status_code == 422


def test_cross_project_native_task_labels_and_preference_candidates_do_not_leak():
    sessions = [{"session_uid": sid, "root_uid": sid, "kind": "main", "source_id": "same-source",
                 "project_id": None, "legacy_project_id": sid} for sid in ("a", "b")]
    events = [{"session_uid": sid, "event_uid": sid, "seq": 1, "ts": 100, "kind": "message.user",
               "actor": "human", "text": text, "attrs": {"origin": "human", "task_id": "shared",
                  "task_id_source": "native"}}
              for sid, text in (("a", "write Python code"), ("b", "write a summary"))]
    events.append({**events[0], "event_uid": "candidate", "seq": 2, "text": "以后我偏好英文", "text_truncated": True})
    bundle = AnalysisInputBundle(sessions, events, [], [], {k: {"status": "available"}
                                  for k in ("sessions", "events", "tool_calls", "model_calls", "projects")})
    view = present(bundle)
    a = next(p for p in view["projects"] if p["legacy_project_id"] == "a")
    b = next(p for p in view["projects"] if p["legacy_project_id"] == "b")
    assert a["profile"]["task_distribution"]["domain"]["counts"] == {"software": 1}
    assert b["profile"]["task_distribution"]["domain"]["counts"] == {}
    assert a["profile"]["preferences"]["candidate_n"] == 1
    assert b["profile"]["preferences"]["candidate_n"] == 0


def test_snapshot_total_retains_authoritative_evidence_and_separate_bucket_basis():
    from orbit_backend.analytics.cost_time import usage

    snapshot = {"session_uid": "s", "event_uid": "snapshot-event", "seq": 1, "kind": "model.usage",
                "attrs": {"measurement": "cumulative", "snapshot_key": "cycle", "usage_scope": "session_snapshot",
                          "coverage": "root_tree", "input_tokens": 8000, "cache_read_tokens": 0,
                          "cache_write_tokens": 0, "output_tokens": 0}}
    measured = usage(None, [snapshot], [{"session_uid": "s", "root_uid": "s"}], Scope())
    tokens = _tokens(measured)
    assert tokens["value"] == 8000
    assert tokens["evidence_refs"] == [{"session_uid": "s", "event_uid": "snapshot-event"}]
    assert tokens["basis"] == "cumulative_snapshot"
    assert tokens["bucket_basis"] == "call_delta_known_rows"


def test_presentation_preserves_explicit_recommendation_catalog_and_agent(monkeypatch, tmp_path):
    bundle = fixture_bundle()

    class FixtureStore:
        path = tmp_path / "fixture.db"

        def analysis_bundle(self, scope):
            return bundle

    monkeypatch.setattr("orbit_backend.api.routes.Store", lambda _: FixtureStore())
    monkeypatch.setattr("orbit_backend.cli.commands.Store", lambda _: FixtureStore())
    empty_catalog = tmp_path / "empty-catalog"
    empty_catalog.mkdir()
    client = TestClient(create_app(db=tmp_path / "unused.db", recommendation_catalog=empty_catalog))
    response = client.get("/v1/analytics/presentation", params={"target_agent": "codex", "family": "hooks"})
    assert response.status_code == 200, response.text
    view = response.json()
    resource_result = view["resources"]["for_you"]
    assert resource_result == view["resource_recommendations"]
    assert resource_result["recommendations"] == []
    assert resource_result["target_agent"] == "codex"
    assert resource_result["family"] == "hooks"
    output = tmp_path / "presentation.json"
    main(["--db", str(tmp_path / "unused.db"), "analytics", "--presentation",
          "--recommendation-catalog", str(empty_catalog), "--recommendation-agent", "codex",
          "--recommendation-family", "hooks", "--output", str(output)])
    assert json.loads(output.read_text(encoding="utf-8")) == view
    generic = client.get("/v1/analytics/presentation").json()
    assert generic["source_analysis_digest"] == view["source_analysis_digest"]
    assert generic["presentation_digest"] != view["presentation_digest"]


AGENTS = ("hermes", "kimi", "opencode", "dsh", "pi", "claude_code", "codex")


def two_agent_bundle(agent):
    """The fixture tree once under ``agent`` and once (ids suffixed) under another agent."""
    raw = json.loads((Path(__file__).parents[1] / "fixtures/bottleneck-features-v1.json").read_text(encoding="utf-8"))
    other = "claude_code" if agent == "codex" else "codex"
    ids = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and (key.endswith("_uid") or key in ("call_uid", "task_uid")):
                    ids.add(item)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    tree = {key: raw[key] for key in ("sessions", "events", "tool_calls", "model_calls", "turns")}
    collect(tree)
    copied = json.dumps(tree)
    for uid in sorted(ids, key=len, reverse=True):
        copied = copied.replace(json.dumps(uid), json.dumps(f"{uid}-x"))
    copy_tree = json.loads(copied)
    for session in raw["sessions"]:
        session["agent"] = agent
    for session in copy_tree["sessions"]:
        session["agent"] = other
    for key in tree:
        raw[key] = raw[key] + copy_tree[key]
    return AnalysisInputBundle.from_dict(raw), other


@pytest.mark.parametrize("agent", AGENTS)
def test_each_agent_flows_through_products_presentation_and_work_graph(agent):
    from orbit_backend.analytics.products import build_products

    bundle, other = two_agent_bundle(agent)
    both = analyze_bundle(bundle, Scope(), with_text=False)
    view = build_presentation(both)
    # Two main sessions in one project, one per agent: 1/2 each, no unknown agents.
    composition = view["projects"][0]["agent_composition"]
    assert composition["total"] == 2 and composition["unknown_n"] == 0
    assert {r["name"]: (r["count"], r["share"]) for r in composition["rows"]} == {
        agent: (1, 0.5), other: (1, 0.5)}
    assert {s["session_uid"]: s["agent"] for s in view["sessions"]} == {"root": agent, "root-x": other}
    assert len(both["work_graph"]["task_trajectories"]) == 2

    scope = Scope(agent_ids=[agent])
    only = analyze_bundle(bundle, scope, with_text=False)
    selected = build_presentation(only)
    assert selected["scope"]["agent_ids"] == [agent]
    assert [(s["session_uid"], s["agent"]) for s in selected["sessions"]] == [("root", agent)]
    assert selected["projects"][0]["agent_composition"]["rows"] == [
        {"name": agent, "count": 1, "share": 1.0}]
    # The fixture tree has two exec_command calls (root + its subagent child), both success.
    assert selected["tools"]["call_count"] == 2
    tools = build_products(bundle, scope)["tools"]
    assert tools["call_count"] == 2
    assert [(r["name"], r["count"], r["share"]["value"]) for r in tools["by_name"]] == [
        ("exec_command", 2, 1.0)]
    assert sorted(tools["by_name"][0]["session_uids"]) == ["child", "root"]
    trajectories = only["work_graph"]["task_trajectories"]
    assert [t["task_uid"] for t in trajectories] == ["synthetic-task"]
    assert len(trajectories[0]["members"]["ToolCall"]) == 2
    assert trajectories[0]["task_success"] is True
