"""Legacy fallback, shutdown forwarding, scope budget, RSS recycling and preemption."""

from __future__ import annotations

from conftest import (
    AUTH,
    BASE,
    PORT,
    TOKEN,
    add_codex,
    bus_events,
    fast_config,
    make_gateway,
    run_job,
    wait_for,
    wait_job,
)
from fastapi.testclient import TestClient

from tandem_backend.services.worker_protocol import DEBUG_DELAY_ENV


def _import_head(client, source):
    assert wait_job(client, run_job(client, "import", [source], phase="head")["id"])[
        "status"] == "completed"


def test_legacy_routes_fall_through_with_uniform_errors(tmp_path, codex_root):
    gateway = make_gateway(tmp_path / "home")
    client = TestClient(gateway.app(token=TOKEN, port=PORT), base_url=BASE, headers=AUTH)
    with client:
        _import_head(client, add_codex(client, codex_root))
        runs = client.get("/v1/analytics/runs")  # Served by create_app(), not the gateway.
        assert runs.status_code == 200
        missing = client.get("/v1/analytics/runs/unknown-run")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        invalid = client.get("/v1/analytics/runs", params={"limit": 0})
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_request"
        # Gateway routes win over the legacy ones with the same path.
        assert "services" in client.get("/health").json()
        legacy = gateway.legacy.app
        assert legacy is not None
        closed = []
        legacy.router.on_shutdown.append(lambda: closed.append(True))
    assert closed == [True]  # create_app()'s shutdown handlers are forwarded.


def test_scope_budget_is_reported_as_422(client_factory, codex_root):
    client, gateway = client_factory(config=fast_config(
        worker_env={"TANDEM_ANALYSIS_MAX_EVENTS": "10"}))
    _import_head(client, add_codex(client, codex_root))
    response = client.get("/v1/analytics/overview", params={"wait_ms": 3000})
    if response.status_code == 202:
        wait_for(lambda: bus_events(gateway, "analysis.failed"), 60)
        response = client.get("/v1/analytics/overview")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "analysis_scope_too_large"
    assert response.json()["error"]["retryable"] is False


def test_rss_limit_recycles_worker_after_task(client_factory, codex_root):
    client, gateway = client_factory(config=fast_config(rss_limit_bytes=1))
    _import_head(client, add_codex(client, codex_root))
    analysis = gateway.supervisor.analysis
    assert client.get("/v1/analytics/tools").status_code == 202
    pid = wait_for(lambda: analysis.worker.pid, 30)
    wait_for(lambda: bus_events(gateway, "analysis.ready"), 60)
    wait_for(lambda: analysis.worker.pid != pid, 15, message="recycled")
    assert client.get("/v1/analytics/tools").json()["meta"]["freshness"] == "fresh"
    assert analysis.worker.restarts_total == 0  # intentional recycle, not a crash


def test_interactive_preempts_prewarm(client_factory, codex_root):
    client, gateway = client_factory(config=fast_config(worker_env={DEBUG_DELAY_ENV: "2000"}))
    _import_head(client, add_codex(client, codex_root))
    queued = gateway.prewarm()
    assert queued  # default scope, light sections
    analysis = gateway.supervisor.analysis
    wait_for(lambda: analysis.running and analysis.running.priority == "prewarm", 30)
    prewarm_pid = analysis.worker.pid
    response = client.get("/v1/analytics/text", params={"from_ts": 3_000})
    assert response.status_code == 202
    job_id = response.json()["meta"]["job_id"]
    wait_for(lambda: [f for f in bus_events(gateway, "analysis.ready")
                      if f.data["job_id"] == job_id], 60, message="interactive result")
    ready = bus_events(gateway, "analysis.ready")
    assert ready[0].data["job_id"] == job_id  # interactive finished before any prewarm
    assert prewarm_pid != analysis.worker.pid or analysis.worker.pid is None
    assert not bus_events(gateway, "analysis.failed")  # preempted prewarm is not a failure
