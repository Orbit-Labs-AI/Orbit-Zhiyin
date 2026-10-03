"""`/v1/eval` runs the recommend suite through a real gateway on a tmp home."""

import time

import pytest
from fastapi.testclient import TestClient

from orbit_backend.services.gateway import Gateway
from orbit_backend.services.supervisor import SupervisorConfig

TOKEN = "synthetic-test-token-0123456789abcdef"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, backoff_s=(0.1, 0.2), tick_s=0.05)
    gateway = Gateway(tmp_path / "orbit", config=config, discovery=lambda: [], prewarm_debounce_s=3600.0)
    with TestClient(gateway.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def test_recommend_suite_over_http(client):
    listed = {s["id"]: s for s in client.get("/v1/eval/suites").json()["suites"]}
    assert "EV-05.1" in listed["recommend"]["ev"]
    run_id = client.post("/v1/eval/runs", json={"suites": ["recommend"], "fail_under": 0.9}).json()["run_id"]
    for _ in range(200):
        report = client.get(f"/v1/eval/runs/{run_id}").json()
        if report["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert report["status"] == "done" and report["passed"] is True
    suite = report["suites"][0]
    assert suite["suite"] == "recommend" and suite["metrics"]["ablation"]["rows"]
    assert "exposure" not in suite["metrics"]  # real app.db only with --real or params.appdb
