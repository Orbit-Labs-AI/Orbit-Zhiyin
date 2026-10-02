import json
from unittest.mock import Mock

from fastapi.testclient import TestClient

from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.preference.dictionary import FEATURES as PREFERENCE_FEATURES
from tandem_backend.analytics.service import analyze_bundle, analyze_store
from tandem_backend.analytics.task.dictionary import FEATURES as TASK_FEATURES
from tandem_backend.api import create_app
from tandem_backend.cli import main
from tandem_backend.models import Event, ParsedSession, Session
from tandem_backend.store import Store


def test_mock_api_family_routes_scope_errors_and_compatibility(fixtures, monkeypatch, tmp_path):
    s, e, b = fixtures
    data = b([e("请修复代码", "a", 0, ts=10), e("以后这个项目用中文", "b", 1, ts=20)])
    mock = Mock(side_effect=lambda store, scope, with_text=True: analyze_bundle(data, scope, with_text))
    monkeypatch.setattr("tandem_backend.analytics.service.analyze_store", mock)
    with TestClient(create_app(tmp_path / "mock.sqlite")) as client:
        result = client.get("/v1/analytics/tasks").json()
        task_id = result["tasks"]["records"][0]["task_id"]
        result = client.get("/v1/analytics/preferences", params={"task_id": task_id}).json()
        assert result["preferences"]["effective"]["applicable"][0]["value"] == "zh"
        assert client.get("/v1/analytics/preferences?task_id=missing").status_code == 404
        assert client.get("/v1/analytics/preferences?until_ts=20").json()["preferences"]["records"] == []
        assert client.get("/v1/analytics/tasks?excluded_session_uids=s").json()["tasks"]["records"] == []
        assert client.get("/v1/analytics/tasks?from_ts=20&until_ts=10").status_code == 422
        detail = client.get("/v1/analytics/sessions/s").json()["session"]
        assert detail["task_ids"] == [task_id] and detail["preference_ids"]
    assert mock.call_count == 6  # Invalid time bounds are rejected before analysis.


def test_bundle_missing_data_and_bounded_future_isolation(fixtures):
    s, e, b = fixtures
    data = b([e("请修复代码", "a", 0, ts=10), e("以后这个项目用中文", "b", 1, ts=20),
              e("这个项目改用英文", "c", 2, ts=30)])
    result = analyze_bundle(data, Scope(until_ts=30), with_text=False)
    assert [p["value"] for p in result["preferences"]["records"]] == ["zh"]
    assert "preference_statement" in result["feature_dictionary"] and "task_goal_history" in result["feature_dictionary"]
    assert PREFERENCE_FEATURES.keys() <= result["preferences"]["records"][0].keys()
    assert TASK_FEATURES.keys() <= result["tasks"]["records"][0].keys()
    data.events = None
    result = analyze_bundle(data, with_text=False)
    assert result["tasks"]["records"] is result["preferences"]["records"] is None
    assert result["tasks"]["summary"]["task_count"] is None


def test_sqlite_cli_api_chain_and_legacy_identity(tmp_path):
    store = Store(tmp_path / "fixture.sqlite")
    s = Session("s", "legacy", "fixture", "/fictional", "synthetic", analytics_metadata={"kind": "main", "root_uid": "s"})
    events = [Event("a", "s", 0, "user_message", "2026-01-01T00:00:00Z", text="请编写报告", details={"origin": "human"}),
              Event("b", "s", 1, "user_message", "2026-01-01T00:00:01Z", text="以后这个项目用中文", details={"origin": "human"})]
    store.save(ParsedSession(s, events), "fixture", json.dumps({"parser": 26, "before": None, "exclude": []}))
    output = tmp_path / "analytics.json"
    main(["--db", str(store.path), "analytics", "--no-text", "--output", str(output)])
    result = json.loads(output.read_text())
    assert result == json.loads(json.dumps(analyze_store(store, with_text=False)))
    assert result["preferences"]["records"][0]["preference_scope"]["identity_quality"] == "legacy_path"
    with TestClient(create_app(store.path)) as client:
        assert client.get("/v1/analytics/tasks").json()["tasks"] == result["tasks"]
        assert client.get("/v1/analytics/preferences").json()["preferences"]["records"] == result["preferences"]["records"]
