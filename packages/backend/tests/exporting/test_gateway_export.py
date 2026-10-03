"""`/v1/export/*` through the real Gateway app (tmp home, no orbit.db, workers not started)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orbit_backend.services.gateway import Gateway

TOKEN = "synthetic-test-token-0123456789abcdef"
PORT = 8765


@pytest.fixture
def client(tmp_path):
    gateway = Gateway(tmp_path / "gw", discovery=lambda: [], prewarm_debounce_s=3600.0)
    client = TestClient(gateway.app(token=TOKEN, port=PORT), base_url=f"http://127.0.0.1:{PORT}",
                        headers={"Authorization": f"Bearer {TOKEN}"})
    yield client
    gateway.close()


def test_export_routes_without_data(client):
    tables = client.get("/v1/export/tables").json()["tables"]
    assert {t["id"] for t in tables} == {"tool_calls", "sessions", "model_calls"}
    assert all(t["approx_rows"] is None for t in tables)
    csv = client.get("/v1/export/csv", params={"table": "sessions"})
    assert csv.status_code == 503 and csv.json()["error"]["code"] == "no_projection"

    body = client.post("/v1/export/report", json={"sections": ["overview", "persona"]}).json()
    assert [s["status"] for s in body["sections"]] == ["unavailable", "unavailable"]
    assert all(s["data"] is None for s in body["sections"])
    assert "## 口径与限制" in body["markdown"]

    card = client.post("/v1/export/share_card", json={"hide_numbers": True}).json()
    assert card["eligible"] is False and card["blocked_reason"] == "persona_unavailable"
    assert card["disclaimer"] == "实验性画像，仅供参考"

    items = client.get("/v1/export/snapshots").json()["items"]
    assert [i["kind"] for i in items] == ["report"]
    assert client.delete(f"/v1/export/snapshots/{items[0]['snapshot_id']}").json() == {"ok": True}
