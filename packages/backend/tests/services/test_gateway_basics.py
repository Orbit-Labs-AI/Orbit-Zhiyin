"""Guard, status, fallback and process handshake of the gateway."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time

import httpx
import pytest
from conftest import AUTH, BASE, PORT, TOKEN, wait_for
from fastapi.testclient import TestClient

from tandem_backend.services.auth import validate_token
from tandem_backend.services.gateway import create_gateway


def test_token_host_and_origin_guard(client_factory):
    client, _ = client_factory()
    anonymous = TestClient(client.app, base_url=BASE)
    missing = anonymous.get("/v1/status")
    assert missing.status_code == 401
    assert missing.json() == {"error": {"code": "unauthorized",
                                        "message": "Missing or invalid bearer token",
                                        "retryable": False}}
    assert missing.headers["www-authenticate"] == "Bearer"
    wrong = anonymous.get("/v1/status", headers={"Authorization": "Bearer " + "x" * 40})
    assert wrong.status_code == 401
    # Host and Origin are checked before the token: DNS rebinding cannot reach routes.
    rebound = client.get("/v1/status", headers={"Host": "evil.example:8765"})
    assert rebound.status_code == 403 and rebound.json()["error"]["code"] == "invalid_host"
    other_port = client.get("/v1/status", headers={"Host": "127.0.0.1:9999"})
    assert other_port.status_code == 403
    foreign = client.get("/v1/status", headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403 and foreign.json()["error"]["code"] == "invalid_origin"
    same_origin = client.get("/v1/status", headers={"Origin": f"http://localhost:{PORT}"})
    assert same_origin.status_code == 200
    for response in (missing, rebound, same_origin):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
    # Unknown fallback paths also require the token (they reach the legacy app only after).
    assert anonymous.get("/v1/catalog").status_code == 401
    assert anonymous.get("/v1/openapi.json").status_code == 401


def test_short_token_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        validate_token("short")
    with pytest.raises(ValueError):
        create_gateway(tmp_path, "x" * 31)
    result = subprocess.run(
        [sys.executable, "-m", "tandem_backend.services", "gateway", "--home", str(tmp_path)],
        env={**os.environ, "TANDEM_API_TOKEN": "too-short"}, capture_output=True, timeout=60)
    assert result.returncode == 2 and b"at least 32" in result.stderr


def test_status_without_database_is_fast_and_onboarding(client_factory):
    client, gateway = client_factory()
    assert not (gateway.home / "tandem.db").exists()
    client.get("/health")  # Warm the route table once.
    durations = []
    for _ in range(25):
        started = time.perf_counter()
        response = client.get("/v1/status")
        durations.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200
    body = response.json()
    assert body["state"] == "onboarding" and body["data_rev"] is None
    assert body["counts"] is None  # Unknown, not zero.
    assert statistics.median(durations) < 20, durations
    assert max(durations) < 100, durations
    # No worker is started just to answer status (lazy start).
    assert body["services"]["ingest"]["pid"] is None
    assert body["services"]["analysis"]["pid"] is None
    health = client.get("/health").json()
    assert health["ok"] is True and health["projection"] == "absent"


def test_reads_and_fallback_without_database(client_factory):
    client, _ = client_factory()
    response = client.get("/v1/sessions")  # Nothing imported yet: empty, not unavailable.
    assert response.status_code == 200 and response.json() == []
    assert response.headers["x-tandem-freshness"] == "none"
    assert response.headers["x-total-count"] == "0"
    legacy = client.get("/v1/analytics/statistics")  # Not a gateway route: create_app().
    assert legacy.status_code == 503 and legacy.json()["error"]["code"] == "no_projection"
    overview = client.get("/v1/analytics/overview")
    assert overview.status_code == 200
    assert overview.json()["overview"] is None
    assert overview.json()["meta"]["freshness"] == "none"
    assert overview.json()["meta"]["reason"] == "no_projection"
    invalid = client.get("/v1/analytics/overview", params={"from_ts": 5, "until_ts": 1})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_request"
    bad_events = client.get("/v1/events", params={"topics": "nope"})
    assert bad_events.status_code == 422


def _start_helper(home, extra_env=None):
    process = subprocess.Popen(
        [sys.executable, "-m", "tandem_backend.services", "gateway", "--home", str(home)],
        env={**os.environ, "TANDEM_API_TOKEN": TOKEN, **(extra_env or {})},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    line = process.stdout.readline()
    return process, json.loads(line)["port"]


def test_helper_prints_port_first_and_serves(tmp_path):
    process, port = _start_helper(tmp_path / "home")
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=AUTH, timeout=10) as http:
            status = http.get("/v1/status")
            assert status.status_code == 200 and status.json()["state"] == "onboarding"
            assert http.get("/v1/status", headers={"Authorization": ""}).status_code == 401
    finally:
        process.terminate()
        assert process.wait(15) is not None


def test_helper_exits_when_parent_disappears(tmp_path):
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    process, _ = _start_helper(tmp_path / "home", {"TANDEM_PARENT_PID": str(parent.pid)})
    try:
        time.sleep(1.5)
        assert process.poll() is None
        parent.kill()
        parent.wait()
        wait_for(lambda: process.poll() is not None, 20, 0.1, "gateway exit")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_analytics_routes_apply_agent_ids_and_reject_unknown_filters(client_factory):
    """a1a3-B10: filters are applied (part of the scope hash) or fail with 422."""
    client, _gateway = client_factory()
    base = client.get("/v1/analytics/sessions")
    assert base.status_code == 200 and base.json()["meta"]["freshness"] == "none"
    scoped = client.get("/v1/analytics/sessions", params={"agent_ids": "codex"})
    assert scoped.status_code == 200
    assert scoped.json()["meta"]["scope_hash"] != base.json()["meta"]["scope_hash"]
    for params in ({"weekday": 1, "hour": 5}, {"query": "x"}, {"bogus": "1"}):
        response = client.get("/v1/analytics/overview", params=params)
        assert response.status_code == 422, params
        assert all(key in response.json()["error"]["message"] for key in params)
    detail = client.get("/v1/analytics/sessions/s1", params={"hour": 5})
    assert detail.status_code == 422
