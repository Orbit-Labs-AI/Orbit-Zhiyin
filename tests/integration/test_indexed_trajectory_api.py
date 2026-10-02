from fastapi.testclient import TestClient
from tandem_data.contract import canonical
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store

from tandem_backend.api import create_app


def test_app_full_messages_original_and_trajectory_for_review_sessions(tmp_path):
    root, home = tmp_path / "codex", tmp_path / "data"
    file = root / "sessions/rollout-review.jsonl"
    file.parent.mkdir(parents=True)
    text = "无截断正文" * 12000
    rows = [
        {"type": "session_meta", "payload": {"id": "review", "source": {"subagent": "guardian"}}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": text}},
        {"type": "unknown_future", "payload": "original"},
    ]
    file.write_text("".join(canonical(r) + "\n" for r in rows))
    with Store(home) as store:
        ImportService(store).import_source(ImportRequest("codex", root))
        session = store.db.execute("SELECT session_uid FROM session").fetchone()[0]
    with TestClient(create_app(home=home)) as client:
        assert client.get("/v1/sessions").json()[0]["id"] == session
        events = client.get(f"/v1/sessions/{session}/events").json()["items"]
        assert any(e["text"] == text for e in events)
        first = client.get(f"/v1/sessions/{session}/trajectory?limit=2").json()
        assert first["total"] == 3 and first["next_after"] == 2
        last = client.get(f"/v1/sessions/{session}/trajectory", params={"after": 2, "run_id": first["run_id"]}).json()
        assert last["next_after"] is None
        source_url = first["items"][1]["source_url"]
        original = client.get(source_url, params={"include_content": True}).json()
        assert original["status"] == "available"
        assert original["content"] == canonical(rows[1]) + "\n"
        file.unlink()
        assert client.get(source_url).json()["status"] == "missing"
        assert client.get("/v1/records/missing/source").status_code == 404
        assert client.get("/v1/sessions/missing/trajectory").status_code == 404
        assert client.get(f"/v1/sessions/{session}/trajectory?run_id=-1").status_code == 409
