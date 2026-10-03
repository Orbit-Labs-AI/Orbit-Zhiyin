"""Recommendation integration tests use fictional bundles and temporary stores."""

import json

import pytest
from fastapi.testclient import TestClient

from orbit_backend.analytics import service
from orbit_backend.analytics.inputs import AnalysisInputBundle
from orbit_backend.analytics.recommendations import recommend_bottlenecks
from orbit_backend.api import create_app
from orbit_backend.cli import main
from orbit_backend.models import Event, ParsedSession, Session
from orbit_backend.store import Store


def synthetic_bundle():
    events = [{
        "event_uid": "delivery", "session_uid": "synthetic-root", "turn_uid": "turn-1",
        "seq": 0, "ts": 100, "kind": "message.assistant", "actor": "assistant", "text": "fictional output",
        "attrs": {"task_uid": "fictional-task"},
    }]
    for i in range(8):
        annotation = {
            "state": "confirmed", "source": "synthetic-reviewer", "available_at": 110 + i * 10,
            "intents": ["correction"] if i < 3 else ["request"],
        }
        if i < 3:
            annotation.update(target_event_uid="delivery", friction_types=["scope"])
        events.append({
            "event_uid": f"human-{i}", "session_uid": "synthetic-root", "turn_uid": "turn-1",
            "seq": i + 1, "ts": 110 + i * 10, "kind": "message.user", "actor": "human",
            "text": "synthetic scope correction" if i < 3 else "synthetic request",
            "attrs": {"origin": "human", "task_uid": "fictional-task", "interaction": annotation},
        })
    return AnalysisInputBundle.from_dict({
        "input_contract": "analysis-input-v1",
        "sessions": [{"session_uid": "synthetic-root", "root_uid": "synthetic-root", "kind": "main",
                      "project_id": "synthetic-project", "started_at": 100}],
        "events": events, "tool_calls": [], "model_calls": [],
        "coverage": {name: {"status": "available"} for name in
                     ("events", "sessions", "tool_calls", "model_calls", "turns", "projects", "lineage")},
        "projects": [{"project_id": "synthetic-project", "name": "Fictional integration fixture"}],
    })


@pytest.fixture
def synthetic_analysis(monkeypatch, tmp_path):
    """Exercise the real feature/recommendation engine while isolating persistence."""
    path = tmp_path / "synthetic-api.sqlite"

    def fake_analyze_store(store, scope=None, with_text=True):
        assert store.path == path
        return service.analyze_bundle(synthetic_bundle(), scope=scope, with_text=False)

    monkeypatch.setattr(service, "analyze_store", fake_analyze_store)
    return path


def test_analyze_bundle_attaches_same_default_recommendations_without_cycles():
    result = service.analyze_bundle(synthetic_bundle(), with_text=False)
    recommendations = result["bottleneck_recommendations"]
    assert recommendations == recommend_bottlenecks(result)
    assert recommendations["target_agent"] == "generic"
    assert recommendations["recommendations"]
    assert any(s["rule_id"] == "correction_density" for s in recommendations["signals"])
    json.dumps(result, allow_nan=False)


def test_api_and_cli_default_output_match_for_nonempty_synthetic_recommendations(synthetic_analysis, tmp_path, capsys):
    with TestClient(create_app(synthetic_analysis)) as client:
        response = client.get("/v1/analytics/recommendations")
    assert response.status_code == 200
    api = response.json()
    output = tmp_path / "synthetic-analytics.json"
    main(["--db", str(synthetic_analysis), "analytics", "--no-text", "--output", str(output)])
    cli = json.loads(output.read_text(encoding="utf-8"))
    assert api["bottleneck_recommendations"]["recommendations"]
    assert api["bottleneck_recommendations"] == cli["bottleneck_recommendations"]
    assert api["analysis_digest"] == cli["analysis_digest"]
    assert api["scope"] == cli["scope"]
    assert "主会话" in capsys.readouterr().out


def test_unannotated_temporary_store_returns_same_uncertainty_through_api_and_cli(tmp_path, capsys):
    store = Store(tmp_path / "synthetic-history.sqlite")
    session = Session("s", "p", "fictional", "/fictional", "fixture",
                      analytics_metadata={"kind": "main", "root_uid": "s"})
    event = Event("u", "s", 0, "user_message", "2026-01-01T00:00:00Z", text="不对，请重新处理",
                  details={"origin": "human"})
    store.save(ParsedSession(session, [event]), "fixture", json.dumps({"parser": 26, "before": None, "exclude": []}))
    with TestClient(create_app(store.path)) as client:
        response = client.get("/v1/analytics/recommendations")
    assert response.status_code == 200
    api = response.json()["bottleneck_recommendations"]
    assert api["recommendations"] == []
    correction = next(a for a in api["assessments"] if a["rule_id"] == "correction_density")
    assert correction["status"] == "insufficient_evidence"
    output = tmp_path / "synthetic-store-analytics.json"
    main(["--db", str(store.path), "analytics", "--no-text", "--output", str(output)])
    assert json.loads(output.read_text(encoding="utf-8"))["bottleneck_recommendations"] == api
    capsys.readouterr()


@pytest.mark.parametrize("params", [
    {"target_agent": "unknown"}, {"kind": "workflow"}, {"limit": 0}, {"limit": 21},
    {"limit": -1}, {"limit": "not-an-integer"}, {"display_timezone": "invalid/timezone"},
    {"from_ts": 500, "until_ts": 100},
])
def test_recommendation_endpoint_rejects_invalid_filters_with_422(synthetic_analysis, params):
    with TestClient(create_app(synthetic_analysis)) as client:
        response = client.get("/v1/analytics/recommendations", params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("target_agent,kind", [
    ("generic", "prompt"), ("codex", "skill"), ("claude_code", "agent"), ("claude_code", "hook"),
])
def test_valid_agent_kind_and_limit_match_direct_recommendation_engine(synthetic_analysis, target_agent, kind):
    params = {"target_agent": target_agent, "kind": kind, "limit": 1}
    with TestClient(create_app(synthetic_analysis)) as client:
        response = client.get("/v1/analytics/recommendations", params=params)
    assert response.status_code == 200
    actual = response.json()["bottleneck_recommendations"]
    result = service.analyze_bundle(synthetic_bundle(), with_text=False)
    expected = recommend_bottlenecks(result, **params)
    assert actual == expected
    assert actual["target_agent"] == target_agent and actual["kind"] == kind
    assert len(actual["recommendations"]) <= 1
    assert all(r["kind"] == kind for r in actual["recommendations"])


@pytest.mark.parametrize("params", [
    {"excluded_session_uids": "synthetic-root"}, {"root_session_uids": "unrelated-root"},
    {"project_ids": "unrelated-project"}, {"until_ts": 100},
])
def test_analytics_scope_exclusion_removes_recommendations_and_evidence(synthetic_analysis, params):
    with TestClient(create_app(synthetic_analysis)) as client:
        response = client.get("/v1/analytics/recommendations", params=params)
    assert response.status_code == 200
    result = response.json()
    assert result["bottleneck_recommendations"]["recommendations"] == []
    assert result["bottleneck_recommendations"]["signals"] == []
    assert not any(a["status"] == "triggered" for a in result["bottleneck_recommendations"]["assessments"])
    assert result["bottleneck_recommendations"]["scope"] == result["scope"]


def test_cli_scope_exclusion_cannot_keep_unfiltered_recommendations(synthetic_analysis, tmp_path, capsys):
    output = tmp_path / "excluded-synthetic-analytics.json"
    main(["--db", str(synthetic_analysis), "analytics", "--no-text", "--exclude-session", "synthetic-root",
          "--output", str(output)])
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["scope"]["excluded_session_uids"] == ["synthetic-root"]
    assert data["bottleneck_recommendations"]["recommendations"] == []
    assert data["bottleneck_recommendations"]["signals"] == []
    capsys.readouterr()
