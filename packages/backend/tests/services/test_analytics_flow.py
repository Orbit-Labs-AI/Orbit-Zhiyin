"""Snapshot request flow: 202 → analysis.ready → 200 fresh → 304 → stale after publish."""

from __future__ import annotations

import threading

import pytest
from conftest import ALL_TIME, add_codex, bus_events, run_job, wait_for, wait_job
from fastapi.testclient import TestClient

from orbit_backend.api.routes import create_app
from orbit_backend.services.sections import SESSION_SUMMARY_FIELDS

# Wall-clock heartbeats, timeouts and a fixed port: run outside the parallel (xdist) pass, see scripts/check.sh.
pytestmark = pytest.mark.serial

META_KEYS = {"contract", "scope_hash", "data_rev", "inventory_rev", "rules_version", "freshness",
             "computed_at", "source", "duration_ms", "coverage", "selection"}


def _ready(gateway, section, count=1):
    return wait_for(lambda: len([f for f in bus_events(gateway, "analysis.ready")
                                 if f.data["section"] == section]) >= count,
                    90, 0.05, f"analysis.ready {section}")


def test_snapshot_lifecycle_keys_and_merging(client_factory, codex_root, tmp_path):
    client, gateway = client_factory()
    source = add_codex(client, codex_root)
    first = run_job(client, "import", [source], phase="head")
    assert wait_job(client, first["id"])["status"] == "completed"
    rev1 = client.get("/v1/status").json()["data_rev"]

    computing = client.get("/v1/analytics/overview", params=ALL_TIME)
    assert computing.status_code == 202
    meta = computing.json()["meta"]
    assert meta["freshness"] == "computing" and meta["job_id"] and meta["data_rev"] == rev1
    _ready(gateway, "overview")

    fresh = client.get("/v1/analytics/overview", params=ALL_TIME)
    assert fresh.status_code == 200
    body = fresh.json()
    assert body["meta"]["freshness"] == "fresh" and set(body["meta"]) >= META_KEYS
    tag = fresh.headers["etag"]
    assert tag == (f'W/"{body["meta"]["rules_version"]}:{rev1}.0:'
                   f'{body["meta"]["scope_hash"]}:overview"')

    # Same keys and values as the existing create_app() route; only meta is added.
    legacy = TestClient(create_app(home=gateway.home)).get("/v1/analytics/overview").json()
    assert set(body) - {"meta"} == set(legacy)
    # The worker filled the shared read-through cache, so the legacy route hits that same
    # entry: same request key, input fingerprint and compute time. Only per-request fields
    # (hit flag, rows computed on a miss) differ.
    assert body["freshness"]["cache_hit"] is False and legacy["freshness"]["cache_hit"] is True
    stable = ("request_key", "input_fp", "algo_version", "computed_at")
    assert {k: body["freshness"][k] for k in stable} == {k: legacy["freshness"][k] for k in stable}
    assert ({k: v for k, v in body.items() if k not in ("meta", "freshness")}
            == {k: v for k, v in legacy.items() if k != "freshness"})
    assert body["meta"]["coverage"] == legacy["coverage"]  # Passed through, never zero-filled.
    assert body["meta"]["selection"] == legacy["selection"]

    not_modified = client.get("/v1/analytics/overview", params=ALL_TIME, headers={"If-None-Match": tag})
    assert not_modified.status_code == 304 and not_modified.headers["etag"] == tag

    # New data: the previous snapshot is served as stale and a recompute is queued.
    second = run_job(client, "import", [source], phase="window")
    assert wait_job(client, second["id"])["status"] == "completed"
    rev2 = client.get("/v1/status").json()["data_rev"]
    assert rev2 > rev1
    stale = client.get("/v1/analytics/overview", params=ALL_TIME, headers={"If-None-Match": tag})
    assert stale.status_code == 200
    assert stale.json()["meta"]["freshness"] == "stale"
    assert stale.json()["meta"]["data_rev"] == rev1 and stale.json()["meta"]["job_id"]
    _ready(gateway, "overview", 2)
    refreshed = client.get("/v1/analytics/overview", params=ALL_TIME)
    assert refreshed.json()["meta"]["freshness"] == "fresh"
    assert refreshed.json()["meta"]["data_rev"] == rev2
    assert refreshed.headers["etag"] != tag

    # Concurrent requests for one key share a single computation.
    params = {"from_ts": 1_000, "display_timezone": "Asia/Shanghai"}
    responses = []

    def ask():
        responses.append(client.get("/v1/analytics/tools", params=params))

    threads = [threading.Thread(target=ask) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert {r.status_code for r in responses} <= {200, 202}
    jobs = {r.json()["meta"].get("job_id") for r in responses if r.status_code == 202}
    assert len(jobs) <= 1
    scope_hash = responses[0].json()["meta"]["scope_hash"]
    _ready(gateway, "tools")
    analysis = gateway.supervisor.analysis
    dispatched = [n for key, n in analysis.dispatched.items()
                  if key[0] == "tools" and key[1] == scope_hash]
    assert dispatched == [1]

    # wait_ms lets the first screen wait (bounded) instead of polling.
    waited = client.get("/v1/analytics/projects", params={"wait_ms": 3000})
    assert waited.status_code in (200, 202)
    if waited.status_code == 200:
        assert waited.json()["meta"]["source"] == "computed"
    assert client.get("/v1/analytics/projects", params={"wait_ms": 3001}).status_code == 422


def test_session_pages_are_compact_and_details_resolve(client_factory, codex_root):
    client, gateway = client_factory()
    source = add_codex(client, codex_root)
    assert wait_job(client, run_job(client, "import", [source], phase="head")["id"])[
        "status"] == "completed"
    page = client.get("/v1/analytics/sessions", params={"limit": 20, "wait_ms": 3000})
    if page.status_code == 202:
        _ready(gateway, "sessions")
        page = client.get("/v1/analytics/sessions", params={"limit": 20})
    body = page.json()
    assert page.status_code == 200 and body["total"] == 50 and body["next_offset"] == 20
    assert len(body["sessions"]) == 20
    assert set(body["sessions"][0]) == {*SESSION_SUMMARY_FIELDS, "usage", "outcome"}
    # a1a3-B11: rows carry agent, timing and outcome facts.
    first = body["sessions"][0]
    assert first["agent"] == "codex" and isinstance(first["started_at"], int)
    assert first["status"] is not None and "tool_failure_count" in first["outcome"]
    last = client.get("/v1/analytics/sessions", params={"limit": 20, "offset": 40}).json()
    assert len(last["sessions"]) == 10 and last["next_offset"] is None
    # Pages are cached separately by ETag but share one snapshot computation.
    assert page.headers["etag"] != client.get("/v1/analytics/sessions",
                                              params={"limit": 20, "offset": 40}).headers["etag"]

    uid = body["sessions"][0]["session_uid"]
    detail = client.get(f"/v1/analytics/sessions/{uid}", params={"wait_ms": 3000})
    if detail.status_code == 202:
        _ready(gateway, "session")
        detail = client.get(f"/v1/analytics/sessions/{uid}")
    assert detail.status_code == 200 and detail.json()["session"]["session_uid"] == uid
    # Section bodies carry only the boundary count + digest; files are paged separately.
    boundary = detail.json()["sample_boundary"]
    assert "files" not in boundary and "files" not in body["sample_boundary"]
    assert boundary["file_count"] >= 50 and boundary["files_digest"]
    files = client.get("/v1/analytics/sample_files", params={"limit": 7, "wait_ms": 3000})
    if files.status_code == 202:
        _ready(gateway, "sample_files")
        files = client.get("/v1/analytics/sample_files", params={"limit": 7})
    listing = files.json()
    assert files.status_code == 200 and listing["total"] == boundary["file_count"]
    assert len(listing["files"]) == 7 and listing["next_offset"] == 7
    assert listing["sample_boundary"]["files_digest"] == boundary["files_digest"]
    row = detail.json()["session"]
    assert row["models"]["status"] == "available" and row["models"]["models"]
    assert isinstance(row["key_moments"], list) and set(row["signals"]) >= {"correction", "feedback"}
    missing = client.get("/v1/analytics/sessions/not-a-session", params={"wait_ms": 3000})
    if missing.status_code == 202:
        wait_for(lambda: bus_events(gateway, "analysis.failed"), 60)
        missing = client.get("/v1/analytics/sessions/not-a-session")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"

    # Unknown values stay null: usage cost for synthetic sessions is not invented as 0.
    usage = body["sessions"][0]["usage"]
    assert usage["cost_usd"] is None or usage["cost_usd"] > 0


def test_recompute_and_prewarm(client_factory, codex_root):
    client, gateway = client_factory(prewarm_debounce_s=0.2)
    source = add_codex(client, codex_root)
    assert wait_job(client, run_job(client, "import", [source], phase="head")["id"])[
        "status"] == "completed"
    # head publishes only light sections for the default scope (debounced prewarm).
    # Sections are computed lazily one by one, so wait for the expected ones, not a count.
    def ready_sections():
        return {f.data["section"] for f in bus_events(gateway, "analysis.ready")}

    expected = {"overview", "sessions", "tools", "projects"}
    wait_for(lambda: expected <= ready_sections(), 120, 0.1, "prewarm")
    sections = ready_sections()
    assert expected <= sections
    assert not sections & {"text", "tasks"}
    bad = client.post("/v1/analytics/recompute", json={"sections": ["nope"]})
    assert bad.status_code == 422
    queued = client.post("/v1/analytics/recompute",
                         json={"sections": ["instruction"], "scope": {"from_ts": 5}})
    assert queued.status_code == 202 and queued.json()["jobs"][0]["job_id"]
    _ready(gateway, "instruction")


def test_warmup_route_queues_on_the_worker(client_factory, codex_root):
    client, gateway = client_factory()
    assert client.post("/v1/analytics/warmup").status_code == 409  # nothing imported yet
    source = add_codex(client, codex_root)
    assert wait_job(client, run_job(client, "import", [source], phase="head")["id"])[
        "status"] == "completed"
    body = client.post("/v1/analytics/warmup").json()
    assert body["status"] == "queued" and body["queued"] == len(body["job_ids"]) > 0
    wait_for(lambda: {f.data["section"] for f in bus_events(gateway, "analysis.ready")}
             >= {"uiview_facts", "overview"}, 120, 0.1, "warmup")
