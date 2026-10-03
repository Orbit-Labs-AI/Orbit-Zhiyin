"""Worker failure handling: crash requeue, interrupted imports, timeouts, circuit, hangs."""

from __future__ import annotations

import os
import signal

import pytest
from conftest import ALL_TIME, add_codex, bus_events, fast_config, run_job, wait_for, wait_job

from orbit_backend.services.worker_protocol import DEBUG_DELAY_ENV

# Wall-clock heartbeats, timeouts and a fixed port: run outside the parallel (xdist) pass, see scripts/check.sh.
pytestmark = pytest.mark.serial


def _services(client):
    return client.get("/v1/status").json()["services"]


def _import_head(client, source):
    job = run_job(client, "import", [source], phase="head")
    assert wait_job(client, job["id"])["status"] == "completed"


def test_killed_analysis_worker_requeues_once_and_reads_continue(client_factory, codex_root):
    client, gateway = client_factory(config=fast_config(worker_env={DEBUG_DELAY_ENV: "1500"}))
    source = add_codex(client, codex_root)
    _import_head(client, source)
    response = client.get("/v1/analytics/overview", params=ALL_TIME)
    assert response.status_code == 202
    analysis = gateway.supervisor.analysis
    pid = wait_for(lambda: analysis.running and analysis.worker.pid, 30, message="dispatch")
    os.kill(pid, signal.SIGKILL)
    # Reads never depend on the analysis worker.
    assert client.get("/v1/sessions").status_code == 200
    assert client.get("/v1/status").status_code == 200
    wait_for(lambda: bus_events(gateway, "analysis.ready"), 60, message="requeued result")
    assert client.get("/v1/analytics/overview", params=ALL_TIME).json()["meta"]["freshness"] == "fresh"
    assert list(analysis.dispatched.values()) == [2]  # original + one rerun
    services = _services(client)["analysis"]
    assert services["restarts"] == 1 and services["state"] == "ok"
    assert services["pid"] not in (None, pid)
    states = [f.data["state"] for f in bus_events(gateway, "service")
              if f.data["name"] == "analysis"]
    assert "restarting" in states


def test_killed_ingest_worker_interrupts_and_retry_verifies(client_factory, codex_root):
    client, gateway = client_factory(config=fast_config(worker_env={DEBUG_DELAY_ENV: "1500"}))
    source = add_codex(client, codex_root)
    job = run_job(client, "import", [source], phase="auto")
    pid = wait_for(lambda: gateway.supervisor.ingest.worker.pid, 30, message="ingest spawn")
    os.kill(pid, signal.SIGKILL)
    interrupted = wait_job(client, job["id"])
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"]["code"] == "worker_exited" and interrupted["error"]["retryable"]
    wait_for(lambda: _services(client)["ingest"]["restarts"] == 1, 10, message="restart count")
    retried = client.post(f"/v1/app/jobs/{job['id']}/retry")
    assert retried.status_code == 202
    assert retried.json()["phase"] == "auto" and retried.json()["source_ids"] == [source]
    assert wait_job(client, retried.json()["id"])["status"] == "completed"
    verify = wait_job(client, run_job(client, "verify")["id"])
    assert verify["status"] == "completed", verify
    assert verify["results"][0]["integrity"] == "ok" and verify["results"][0]["unparsed"] == 0
    assert client.get("/v1/status").json()["counts"]["sessions"] == 70


def test_timeout_keeps_old_snapshot_and_opens_circuit(client_factory, codex_root):
    config = fast_config(worker_env={DEBUG_DELAY_ENV: "600"})
    client, gateway = client_factory(config=config)
    source = add_codex(client, codex_root)
    _import_head(client, source)
    assert client.get("/v1/analytics/overview", params=ALL_TIME).status_code == 202
    wait_for(lambda: bus_events(gateway, "analysis.ready"), 60, message="first snapshot")
    old = client.get("/v1/analytics/overview", params=ALL_TIME).json()
    window = run_job(client, "import", [source], phase="window")
    assert wait_job(client, window["id"])["status"] == "completed"

    # Shorter than the worker's fixed 0.6 s start-up delay even after two budget doublings
    # (0.1 → 0.2 → 0.4 s).
    config.light_timeout_s = 0.1
    analysis = gateway.supervisor.analysis
    for attempt in range(1, 4):
        stale = client.get("/v1/analytics/overview", params=ALL_TIME)
        assert stale.status_code == 200 and stale.json()["meta"]["freshness"] == "stale"
        assert stale.json()["overview"] == old["overview"]  # the old snapshot keeps serving
        wait_for(lambda n=attempt: len([f for f in bus_events(gateway, "analysis.failed")
                                        if f.data["code"] == "timeout"]) >= n,
                 30, message=f"timeout {attempt}")
        wait_for(lambda: analysis.running is None, 10)
    assert sum(analysis.dispatched.values()) == 4  # 1 success + 3 timeouts
    held = client.get("/v1/analytics/overview", params=ALL_TIME).json()
    assert held["meta"]["freshness"] == "stale" and held["meta"]["circuit"] == "open"
    assert sum(analysis.dispatched.values()) == 4  # circuit open: no fourth attempt

    # Without an older snapshot the open circuit is a retryable 503, never a fake result.
    scoped = {"from_ts": 2_000}
    for _ in range(3):
        first = client.get("/v1/analytics/tools", params=scoped)
        assert first.status_code in (202, 503)
        wait_for(lambda: analysis.running is None and not analysis.pending, 30)
    unavailable = client.get("/v1/analytics/tools", params=scoped)
    assert unavailable.status_code == 503 and unavailable.headers["retry-after"]
    assert unavailable.json()["error"] == {
        "code": "analysis_unavailable", "message": unavailable.json()["error"]["message"],
        "retryable": True}

    # A manual recompute resets the circuit once the budget is sane again.
    config.light_timeout_s = 60
    # Recompute the window this test reads (days=0): without days the overview recompute
    # follows the GET fast path, which would refresh the 7-day window instead.
    assert client.post("/v1/analytics/recompute", json={"sections": ["overview"], "scope": ALL_TIME}
                       ).status_code == 202
    wait_for(lambda: len(bus_events(gateway, "analysis.ready")) >= 2, 60, message="recovered")
    assert client.get("/v1/analytics/overview", params=ALL_TIME).json()["meta"]["freshness"] == "fresh"


def test_hung_worker_is_killed_and_crash_loops_degrade(client_factory, codex_root):
    # stale_s leaves room for a respawned worker to import and send its first heartbeat
    # under load; 1 s made the respawn itself look hung (extra restart, early degraded).
    config = fast_config(stale_s=3.0, max_restarts=2, backoff_s=(0.05, 0.05))
    client, gateway = client_factory(config=config)
    source = add_codex(client, codex_root)
    _import_head(client, source)
    ingest = gateway.supervisor.ingest.worker
    pid = ingest.pid
    os.kill(pid, signal.SIGSTOP)  # No heartbeats: judged hung after stale_s.
    wait_for(lambda: ingest.pid not in (None, pid), 15, message="hung worker replaced")
    assert ingest.restarts_total == 1
    for _ in range(2):
        current = wait_for(lambda: ingest.pid, 15)
        os.kill(current, signal.SIGKILL)
        wait_for(lambda c=current: ingest.pid != c, 15)
    wait_for(lambda: ingest.state == "degraded", 15, message="degraded")
    assert _services(client)["ingest"]["state"] == "degraded"
    assert {"name": "ingest", "state": "degraded"} in [f.data for f in bus_events(gateway,
                                                                                 "service")]
    # Reads keep working while ingest is degraded; a user action retries the worker.
    assert client.get("/v1/sessions").status_code == 200
    job = run_job(client, "import", [source], phase="head")
    assert wait_job(client, job["id"])["status"] == "completed"
    assert ingest.state == "ok"
