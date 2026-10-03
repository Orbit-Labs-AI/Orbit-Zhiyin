"""`/v1/eval` through a real gateway on a tmp home, with fake suites."""

import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from tandem_backend.evalrun import registry
from tandem_backend.evalrun.contract import Check, SuiteResult
from tandem_backend.services.gateway import Gateway
from tandem_backend.services.supervisor import SupervisorConfig

from .conftest import FAKES, make_suite

TOKEN = "synthetic-test-token-0123456789abcdef"
GATE = threading.Event()


def _slow(ctx):
    GATE.wait(10)
    return SuiteResult("slow", [Check("slow.done", True)])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    suites = {**FAKES, "slow": _slow}
    for suite_id, run in suites.items():
        monkeypatch.setitem(sys.modules, f"tandem_backend.evalrun.suites.{suite_id}", make_suite(suite_id, run))
    monkeypatch.setattr(registry, "ids", lambda: sorted(suites))
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, backoff_s=(0.1, 0.2), tick_s=0.05)
    gateway = Gateway(tmp_path / "tandem", config=config, discovery=lambda: [], prewarm_debounce_s=3600.0)
    app = gateway.app(token=TOKEN, port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c
    GATE.set()


def _wait(c, run_id):
    for _ in range(200):
        report = c.get(f"/v1/eval/runs/{run_id}").json()
        if report["status"] in ("done", "failed"):
            return report
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_suites_list(client):
    body = client.get("/v1/eval/suites").json()
    assert {"id": "ok", "title": "Ok", "ev": ["EV-12"], "kind": "unclassified",
            "description": "Fake suite ok."} in body["suites"]


def test_run_poll_list_and_404(client):
    r = client.post("/v1/eval/runs", json={"suites": ["ok", "half", "skip"], "fail_under": 0.5})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    report = _wait(client, r.json()["run_id"])
    assert report["status"] == "done" and report["passed"] is False and report["score"] == 0.75
    assert [s["suite"] for s in report["suites"]] == ["ok", "half", "skip"]
    assert report["suites"][1]["checks"][1]["id"] == "half.b"
    runs = client.get("/v1/eval/runs?limit=5").json()["runs"]
    assert runs[0]["run_id"] == report["run_id"] and runs[0]["suites"] == ["ok", "half", "skip"]
    assert client.get("/v1/eval/runs/missing").status_code == 404


def test_unknown_suite_and_bad_bar(client):
    assert client.post("/v1/eval/runs", json={"suites": ["nope"]}).status_code == 422
    assert client.post("/v1/eval/runs", json={"suites": "all", "fail_under": 2}).status_code == 422


def test_one_run_at_a_time(client):
    GATE.clear()
    first = client.post("/v1/eval/runs", json={"suites": ["slow"]}).json()["run_id"]
    second = client.post("/v1/eval/runs", json={"suites": ["ok"]})
    assert second.status_code == 409
    assert second.json()["error"] == {"code": "run_in_progress", "run_id": first,
                                      "message": "An evaluation run is already in progress",
                                      "retryable": False}
    GATE.set()
    assert _wait(client, first)["passed"] is True
    third = client.post("/v1/eval/runs", json={"suites": ["ok"]})
    assert third.status_code == 202
    _wait(client, third.json()["run_id"])


def test_label_summary_route(client):
    body = client.get("/v1/eval/labels/summary?days=30").json()
    assert body == {"rows": [], "total_labels": 0}
