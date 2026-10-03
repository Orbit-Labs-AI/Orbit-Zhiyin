import copy
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from orbit_backend.analytics.inputs import AnalysisInputBundle, Scope
from orbit_backend.analytics.service import analyze_bundle, analyze_store
from orbit_backend.api import create_app
from orbit_backend.cli import main
from orbit_backend.store import Store, import_codex


def fixture_bundle():
    session = {"session_uid": "s", "kind": "main", "root_uid": "s", "project_id": "p", "started_at": 0}
    events = [
        {"event_uid": "u", "session_uid": "s", "seq": 0, "ts": 100, "turn_uid": "t",
         "kind": "message.user", "actor": "human", "text": "先给方案。请运行测试",
         "attrs": {"origin": "human", "task_id": "task"}},
        {"event_uid": "v", "session_uid": "s", "seq": 1, "ts": 200, "turn_uid": "t2",
         "kind": "message.user", "actor": "human", "text": "不要推送", "attrs": {"origin": "human"}},
    ]
    return AnalysisInputBundle([session], events, [], [], {
        key: {"status": "available"} for key in ("sessions", "events", "tool_calls", "model_calls", "projects")
    })


def test_mock_adapter_engine_api_and_cli_share_scope_and_contract(tmp_path):
    bundle = fixture_bundle()
    original = copy.deepcopy(bundle)
    with patch("orbit_backend.analytics.service.legacy_bundle", return_value=bundle) as adapter:
        with TestClient(create_app(tmp_path / "mock.sqlite")) as client:
            with patch("orbit_backend.analytics.service.representation", side_effect=AssertionError("not needed")):
                response = client.get("/v1/analytics/instruction", params={"until_ts": 150})
                assert response.status_code == 200
                assert [r["event_uid"] for r in response.json()["instruction"]["records"]] == ["u"]
            overview = client.get("/v1/analytics/overview", params={"until_ts": 150}).json()
            assert overview["overview"]["instruction"] == response.json()["instruction"]["summary"]
            assert client.get("/v1/analytics/instruction?project_ids=").json()["instruction"]["records"] == []
            assert client.get("/v1/analytics/instruction?display_timezone=bogus").status_code == 422
        output = tmp_path / "cli.json"
        main(["--db", str(tmp_path / "mock.sqlite"), "analytics", "--no-text", "--until-ts", "150",
              "--output", str(output)])
        assert json.loads(output.read_text())["instruction"] == response.json()["instruction"]
        assert adapter.call_count == 4
    assert bundle == original


def test_unavailable_and_selected_rows_are_distinct():
    bundle = fixture_bundle()
    data = analyze_bundle(bundle, Scope(until_ts=150), with_text=False)
    assert data["sessions"][0]["instruction"]["summary"] == data["instruction"]["summary"]
    assert data["projects"][0]["instruction"] == data["instruction"]["summary"]
    assert "requested_autonomy" in data["feature_dictionary"]
    bundle.events = None
    data = analyze_bundle(bundle, with_text=False)
    assert data["instruction"]["records"] is None
    assert data["instruction"]["summary"]["status"] == "unavailable"
    assert data["sessions"][0]["instruction"]["records"] is None


def test_synthetic_rollout_import_sqlite_cli_and_api(tmp_path):
    source = tmp_path / "codex"
    (source / "sessions").mkdir(parents=True)
    native = [
        {"type": "session_meta", "payload": {"id": "s", "cwd": "/synthetic", "source": "cli", "thread_source": "user"},
         "timestamp": "2026-01-01T00:00:00Z"},
        {"type": "event_msg", "payload": {"type": "user_message",
                                        "message": "先给方案，等我确认后再改文件。不要推送"},
         "timestamp": "2026-01-01T00:00:01Z"},
    ]
    (source / "sessions" / "rollout.jsonl").write_text("\n".join(json.dumps(r) for r in native) + "\n")
    store = Store(tmp_path / "synthetic.sqlite")
    summary = import_codex(store, source)
    assert summary.imported == 1
    expected = analyze_store(store, with_text=False)["instruction"]
    assert expected["summary"]["message_n"] == 1
    assert expected["records"][0]["features"]["requested_autonomy"][0]["value"] == "ask_first"
    with TestClient(create_app(store.path)) as client:
        assert client.get("/v1/analytics/instruction").json()["instruction"] == expected
        assert client.get("/v1/analytics/sessions/s").json()["session"]["instruction"]["records"] == expected["records"]
    output = tmp_path / "analytics.json"
    main(["--db", str(store.path), "analytics", "--no-text", "--output", str(output)])
    assert json.loads(output.read_text())["instruction"] == expected
