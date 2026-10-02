"""HTTP surface of /v1/ai against FakeEngine, plus one gateway-level smoke test."""

from __future__ import annotations

import sys
import time

import pytest
from ai_support import answer_task
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tandem_backend.ai.service import AIService, fallback_pack
from tandem_backend.services import routes_ai
from tandem_backend.services.gateway import install_error_handlers


@pytest.fixture
def client(ai_svc, ai_gw):
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_ai.router(ai_gw))
    return TestClient(app)


def wait_job(client, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(f"/v1/ai/jobs/{job_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_engines_and_consent(client):
    body = client.get("/v1/ai/engines").json()
    assert body["mode"] == "agent" and body["default_engine"] == "fake"
    engines = {e["id"]: e for e in body["engines"]}
    assert engines["fake"]["available"] and engines["fake"]["consent"]["summary"] is True
    assert engines["claude_code"]["available"] is False  # PATH has no CLI in tests.
    assert set(engines["fake"]) >= {"id", "name", "available", "version", "logged_in", "flags",
                                    "slots", "consent", "quota", "checked_at"}
    assert client.get("/v1/ai/engines?refresh=1").status_code == 200
    state = client.get("/v1/ai/consent").json()
    assert set(state) == {"mode", "default_engine", "grants", "data_classes", "settings"}
    updated = client.put("/v1/ai/consent", json={
        "grants": {"fake": {"snippets": True}}, "settings": {"daily_usd_cap": 3}}).json()
    assert updated["grants"]["fake"]["snippets"] and updated["settings"]["daily_usd_cap"] == 3
    assert updated["cancelled_jobs"] == []
    raw = client.put("/v1/ai/consent", json={"grants": {"fake": {"raw": True}}})
    assert raw.status_code == 400 and raw.json()["error"]["code"] == "consent_forbidden"
    assert client.put("/v1/ai/consent", json={"mode": "turbo"}).status_code == 422


def test_preview_job_lifecycle(client):
    preview = client.post("/v1/ai/preview", json={"task_id": "test.echo", "goal": "fix tests",
                                                  "goal_source": "manual"}).json()
    assert preview["payload"] == {"goal": {"text": "fix tests", "source": "manual"}}
    assert preview["items"][0]["consent"] == "granted" and preview["stages"] == ["pack", "draft"]
    assert set(preview) >= {"total_tokens", "input_budget", "over_budget", "est_cost_usd",
                            "est_calls", "redaction_hits", "preview_digest"}
    created = client.post("/v1/ai/jobs", json={"task_id": "test.echo", "goal": "fix tests",
                                               "preview_digest": preview["preview_digest"]})
    assert created.status_code == 202
    body = created.json()
    assert set(body) == {"job_id", "status", "cached", "estimate"}
    job = wait_job(client, body["job_id"])
    assert job["status"] == "ok" and job["result"] == {"answer": "ok"}
    assert set(job) >= {"stages", "progress", "log", "usage", "artifact_id", "error", "cached",
                        "created_at", "finished_at"}
    assert client.get("/v1/ai/jobs?limit=5").json()[0]["job_id"] == body["job_id"]
    assert client.post(f"/v1/ai/jobs/{body['job_id']}/cancel").json()["status"] == "ok"
    assert client.get("/v1/ai/jobs/nope").status_code == 404
    usage = client.get("/v1/ai/usage?days=7").json()
    assert usage["totals"]["calls"] == 1 and "today_cost_usd" in usage


def test_job_error_codes(client, ai_svc, monkeypatch):
    def post(**body):
        return client.post("/v1/ai/jobs", json={"task_id": "test.echo", **body})

    assert post(task_id="nope").json()["error"]["code"] == "unknown_task"
    unavailable = post(engine="codex")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["reason"] == "not_installed"
    ai_svc.register_task(answer_task("test.p", requires_preview=True, input_budget=10))
    stale = client.post("/v1/ai/jobs", json={"task_id": "test.p", "preview_digest": "sha256:0"})
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "preview_stale")
    big = {"task_id": "test.p", "slots": {"goal": "x" * 400}}
    digest = client.post("/v1/ai/preview", json=big).json()["preview_digest"]
    assert client.post("/v1/ai/jobs", json={**big, "preview_digest": digest}).status_code == 413

    def snippets_pack(self, task, req):
        pack = fallback_pack(task, req)
        pack["items"][0]["data_class"] = "snippets"
        return pack

    monkeypatch.setattr(AIService, "_pack", snippets_pack)
    missing = post(goal="g")
    assert missing.status_code == 403
    assert missing.json()["error"] == {"code": "consent_required", "message": "需要先授权这些数据类",
                                       "retryable": False, "missing": ["snippets"]}
    monkeypatch.undo()
    ai_svc.set_consent({"settings": {"daily_usd_cap": 0}})
    assert post(goal="g").json()["error"]["code"] == "budget_exhausted"
    assert post(goal="g", override=True).status_code == 202
    ai_svc.set_consent({"mode": "stats"})
    disabled = post(goal="g")
    assert (disabled.status_code, disabled.json()["error"]["code"]) == (403, "ai_disabled")


def test_artifacts_and_facets(client, ai_svc):
    from test_runner import artifact_task

    ai_svc.register_task(artifact_task("test.gen"))
    job = wait_job(client, client.post("/v1/ai/jobs", json={"task_id": "test.gen"}).json()[
        "job_id"])
    listed = client.get("/v1/ai/artifacts?kind=rule&status=draft").json()
    assert listed[0]["artifact_id"] == job["artifact_id"]
    assert set(listed[0]) == {"artifact_id", "kind", "name", "title", "status", "personalized",
                              "created_at", "checks"}
    full = client.get(f"/v1/ai/artifacts/{job['artifact_id']}").json()
    assert full["payload"] == {"text": "always run tests"} and full["kind"] == "rule"
    patched = client.patch(f"/v1/ai/artifacts/{job['artifact_id']}",
                           json={"status": "archived", "name": "renamed"}).json()
    assert (patched["status"], patched["name"]) == ("archived", "renamed")
    assert client.patch(f"/v1/ai/artifacts/{job['artifact_id']}",
                        json={"status": "installed"}).status_code == 422
    assert client.get("/v1/ai/artifacts/af_missing").status_code == 404
    facets = client.get("/v1/ai/facets?session_uid=s1&session_uid=s9").json()
    assert [f["session_uid"] for f in facets] == ["s1"]


def test_ask_routes(client, ai_svc, monkeypatch):
    import types

    module = types.ModuleType("tandem_backend.ai.ask")
    module.presets = lambda context, **kw: [{"q": f"{context}-1"}]
    module.preset_answer = lambda context, index, **kw: {"answer": "a", "refs": [], "next": "none",
                                                         "source": "template"}
    monkeypatch.setitem(sys.modules, "tandem_backend.ai.ask", module)
    import tandem_backend.ai as ai_pkg
    monkeypatch.setattr(ai_pkg, "ask", module, raising=False)
    assert client.get("/v1/ai/ask/presets?context=overview").json() == [{"q": "overview-1"}]
    answer = client.post("/v1/ai/ask", json={"context": "overview", "preset_index": 0}).json()
    assert answer["source"] == "template"
    ai_svc.register_task(answer_task("ask.question"))
    asked = client.post("/v1/ai/ask", json={"context": "overview", "question": "为什么？"}).json()
    assert asked["job_id"].startswith("aj_")
    assert client.post("/v1/ai/ask", json={"context": "overview"}).status_code == 422
    monkeypatch.setitem(sys.modules, "tandem_backend.ai.ask", None)
    monkeypatch.delattr(ai_pkg, "ask", raising=False)
    assert client.get("/v1/ai/ask/presets").status_code == 501


def test_gateway_mounts_ai_routes(tmp_path, ai_env):
    from tandem_backend.services.gateway import Gateway

    token = "synthetic-test-token-0123456789abcdef"
    gateway = Gateway(tmp_path / "gw", discovery=lambda: [], prewarm_debounce_s=3600.0)
    try:  # No lifespan: the supervisor is not started, only the routes are exercised.
        client = TestClient(gateway.app(token=token, port=8765), base_url="http://127.0.0.1:8765",
                            headers={"Authorization": f"Bearer {token}"})
        assert client.get("/v1/ai/consent").json()["mode"] == "stats"
        assert client.get("/v1/ai/engines").status_code == 200
        response = client.post("/v1/ai/jobs", json={"task_id": "x"})
        assert response.json()["error"]["code"] == "unknown_task"
    finally:
        gateway._ai.close()
        gateway.close()
