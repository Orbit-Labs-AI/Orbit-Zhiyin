"""v1 tasks through /v1/ai/jobs (FakeEngine, input-digest cache) and GET /v1/ai/narratives."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orbit_backend.services import routes_ai
from orbit_backend.services.gateway import install_error_handlers

CLUSTERS = {"key": "scan-1", "clusters": [
    {"cluster_id": "0", "top_terms": ["css"], "summaries": ["调样式"]},
    {"cluster_id": "1", "top_terms": ["pytest"], "summaries": ["修测试"]}]}
NAMES = {"clusters": [{"cluster_id": "0", "name": "前端样式", "kind": "task", "confidence": "high"},
                      {"cluster_id": "1", "name": "测试修复", "kind": "task", "confidence": "medium"}]}


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


def submit(client, task_id: str, slots: dict) -> dict:
    created = client.post("/v1/ai/jobs", json={"task_id": task_id, "slots": slots})
    assert created.status_code == 202, created.text
    return wait_job(client, created.json()["job_id"])


def test_topic_names_job_cache_and_narrative(client, ai_svc):
    ai_svc.fake.responses["cluster.topic_names"] = NAMES
    job = submit(client, "cluster.topic_names", {"topic_clusters": CLUSTERS})
    assert job["status"] == "ok" and job["result"]["clusters"][0]["name"] == "前端样式"
    assert job["result"]["source"] == "ai" and job["result"]["key"] == "scan-1"
    calls = len(ai_svc.fake.requests)
    again = submit(client, "cluster.topic_names", {"topic_clusters": CLUSTERS})
    assert len(ai_svc.fake.requests) == calls and again["cached"] and again["result"]["source"] == "cache"
    body = client.get("/v1/ai/narratives", params={"kind": "topic_names"}).json()
    assert body["job_id"] == again["job_id"] and body["result"]["clusters"][1]["name"] == "测试修复"
    assert client.get("/v1/ai/narratives", params={"kind": "topic_names", "key": "scan-1"}).json()["job_id"]
    other = client.get("/v1/ai/narratives", params={"kind": "topic_names", "key": "scan-2"}).json()
    assert other["job_id"] is None and other["source"] == "template"


def test_invalid_output_falls_back_through_runner(client, ai_svc):
    ai_svc.fake.responses["narrate.persona"] = {"headline": "x"}
    profile = {"key": "DP", "code": "DP", "type_name": "规划型",
               "observations": [{"label": "先写计划", "sessions": 12}]}
    job = submit(client, "narrate.persona", {"persona": profile})
    assert job["status"] == "fallback" and job["result"]["headline"] == "规划型"
    assert job["result"]["source"] == "template" and len(ai_svc.fake.requests) == 2


def test_narratives_l0_when_ai_off(client, ai_svc):
    ai_svc.set_consent({"mode": "stats"})
    assert client.post("/v1/ai/jobs", json={"task_id": "narrate.weekly"}).json()["error"]["code"] == "ai_disabled"
    for kind in ("weekly", "persona", "session_review", "failure_names", "feedback", "failure_cause",
                 "topic_names", "overview"):
        body = client.get("/v1/ai/narratives", params={"kind": kind}).json()
        assert body["status"] == "fallback" and body["source"] == "template" and body["job_id"] is None, kind
    review = client.get("/v1/ai/narratives", params={"kind": "session_review", "session_uid": "s1"}).json()
    assert review["result"]["lessons"] == [] and review["result"]["source"] == "template"
    bad = client.get("/v1/ai/narratives", params={"kind": "nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unknown_kind"


def test_gateway_serves_narratives(tmp_path, ai_env):
    from orbit_backend.services.gateway import Gateway

    token = "synthetic-test-token-0123456789abcdef"
    gateway = Gateway(tmp_path / "gw", discovery=lambda: [], prewarm_debounce_s=3600.0)
    try:  # No lifespan: AI is off by default, so the page gets the L0 template.
        client = TestClient(gateway.app(token=token, port=8765), base_url="http://127.0.0.1:8765",
                            headers={"Authorization": f"Bearer {token}"})
        body = client.get("/v1/ai/narratives?kind=weekly&days=7").json()
        assert body["source"] == "template" and [s["id"] for s in body["result"]["sections"]] == [
            "overview", "problems", "effects"]
    finally:
        if getattr(gateway, "_ai", None) is not None:
            gateway._ai.close()
        gateway.close()


def test_fresh_job_skips_the_cache_and_replaces_it(client, ai_svc):
    """「重新生成」 posts fresh=true: a new model call even when an identical request is cached,
    and the new output becomes the cached one."""
    ai_svc.fake.responses["cluster.topic_names"] = NAMES
    submit(client, "cluster.topic_names", {"topic_clusters": CLUSTERS})
    calls = len(ai_svc.fake.requests)
    renamed = {"clusters": [{**NAMES["clusters"][0], "name": "样式调整"}, NAMES["clusters"][1]]}
    ai_svc.fake.responses["cluster.topic_names"] = renamed
    created = client.post("/v1/ai/jobs", json={"task_id": "cluster.topic_names", "fresh": True,
                                               "slots": {"topic_clusters": CLUSTERS}})
    assert created.status_code == 202 and created.json()["cached"] is False
    job = wait_job(client, created.json()["job_id"])
    assert len(ai_svc.fake.requests) == calls + 1
    assert job["result"]["source"] == "ai" and job["result"]["clusters"][0]["name"] == "样式调整"
    again = submit(client, "cluster.topic_names", {"topic_clusters": CLUSTERS})
    assert again["cached"] and again["result"]["clusters"][0]["name"] == "样式调整"


def test_narrative_binds_scope_even_when_key_is_omitted(client, ai_svc):
    ai_svc.fake.responses["cluster.topic_names"] = NAMES
    submitted = client.post("/v1/ai/jobs", json={"task_id": "cluster.topic_names",
                            "slots": {"topic_clusters": CLUSTERS}, "scope": {"source_ids": ["allowed"]}})
    job = wait_job(client, submitted.json()["job_id"])
    assert job["status"] == "ok"
    assert ai_svc.narrative("topic_names", scope={"source_ids": ["allowed"]})["job_id"] == job["job_id"]
    for scope in ({"source_ids": []}, {"source_ids": ["other"]}, None):
        assert ai_svc.narrative("topic_names", scope=scope)["job_id"] is None


def test_narrative_rejects_changed_pack_digest(client, ai_svc, monkeypatch):
    ai_svc.fake.responses["cluster.topic_names"] = NAMES
    job = submit(client, "cluster.topic_names", {"topic_clusters": CLUSTERS})
    original = ai_svc._pack

    def changed(task, req):
        current = original(task, req)
        return {**current, "content": {**current["content"], "data_revision": "new-import"},
                "preview_digest": "sha256:new-import"}

    monkeypatch.setattr(ai_svc, "_pack", changed)
    body = ai_svc.narrative("topic_names", key="scan-1")
    assert body["job_id"] is None and body["source"] == "template"
    assert ai_svc.job(job["job_id"])["status"] == "ok"  # historical job remains inspectable


def test_relative_window_fingerprint_ignores_only_same_day_label_drift(monkeypatch):
    import importlib

    from orbit_backend.ai import registry
    from orbit_backend.ai.service import narrative_input_fingerprint

    module = importlib.import_module("orbit_backend.ai.service")
    day = 86_400_000
    monkeypatch.setattr(module, "now_ms", lambda: day * 20000 + 1000)
    task = registry.get("narrate.weekly")
    first = {"content": {"snapshot": {"key": f"{day * 19970 + 1000}:{day * 20000 + 1000}:",
             "window": {"start_ms": day * 19970 + 1000, "end_ms": day * 20000 + 1000},
             "metrics": {"sessions": 2}}}}
    later = {"content": {"snapshot": {"key": f"{day * 19970 + 5000}:{day * 20000 + 5000}:",
             "window": {"start_ms": day * 19970 + 5000, "end_ms": day * 20000 + 5000},
             "metrics": {"sessions": 2}}}}
    assert narrative_input_fingerprint(task, first, {}) == narrative_input_fingerprint(task, later, {})
    assert narrative_input_fingerprint(task, first, {"end_ms": day * 20000}) != narrative_input_fingerprint(
        task, later, {"end_ms": day * 20000})
    later["content"]["snapshot"]["metrics"]["sessions"] = 3
    assert narrative_input_fingerprint(task, first, {}) != narrative_input_fingerprint(task, later, {})


def test_stale_narrative_rebuilds_at_most_one_history_pack(client, ai_svc, monkeypatch):
    ai_svc.fake.responses["cluster.topic_names"] = NAMES
    for _ in range(3):
        submit(client, "cluster.topic_names", {"topic_clusters": CLUSTERS})
    original = ai_svc._pack
    calls = []

    def changed(task, req):
        calls.append(req)
        current = original(task, req)
        return {**current, "content": {**current["content"], "data_revision": "new-import"}}

    monkeypatch.setattr(ai_svc, "_pack", changed)
    assert ai_svc.narrative("topic_names")["job_id"] is None
    assert len(calls) == 2  # one history candidate plus the current L0 fallback


def test_overview_filters_are_part_of_the_prompt_and_fingerprint():
    """Agent subset / project / 「全部」 views each get their own narrative: the filter is in the
    prompt (cache key) and in the stored input fingerprint, and agents resolve to sources."""
    import sqlite3

    from orbit_backend.ai.pack import _Ctx, agent_sources
    from orbit_backend.ai.service import narrative_input_fingerprint
    from orbit_backend.ai.tasks_analysis import NARRATE_TASK, narrate_prompt

    content = {"metrics": {"sessions": 3}, "friction": {}, "candidates": []}
    every = {"scope": {"days": 30}, "content": content}
    codex = {"scope": {"days": 30, "agent_ids": ["codex"], "source_ids": ["src-c"]}, "content": content}
    assert narrate_prompt(every) != narrate_prompt(codex)
    assert '"agent_ids":["codex"]' in narrate_prompt(codex) and "src-c" not in narrate_prompt(codex)
    assert narrative_input_fingerprint(NARRATE_TASK, every, {"days": 30}) != \
        narrative_input_fingerprint(NARRATE_TASK, codex, {"days": 30, "agent_ids": ["codex"]})
    assert narrative_input_fingerprint(NARRATE_TASK, every, {"start_ms": 1}) != \
        narrative_input_fingerprint(NARRATE_TASK, every, {"start_ms": 1, "project_id": "p"})

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE source (source_id TEXT, agent TEXT)")
    conn.executemany("INSERT INTO source VALUES (?, ?)",
                     [("a1", "claude_code"), ("c1", "codex"), ("c2", "codex")])
    assert agent_sources(conn, ["codex"]) == ["c1", "c2"]
    assert agent_sources(conn, ["codex"], ["c2", "a1"]) == ["c2"]
    assert agent_sources(None, ["codex"]) == []
    ctx = _Ctx(conn, NARRATE_TASK, None, None, {"days": 7, "agent_ids": ["claude_code"]}, None, None, {}, {})
    assert ctx.scope["source_ids"] == ["a1"] and "source_id IN" in ctx.where()[0]


def test_persona_from_the_page_profile_uses_its_axes(client, ai_svc):
    """The A2 page sends its own profile (axes D/I/M/V): an I tradeoff passes, an axis the
    profile does not have fails the check and falls back."""
    profile = {"key": "ui:30", "code": "DIMV", "type_name": "FX 类型",
               "axes": {k: {"letter": k, "value": 60} for k in "DIMV"}, "rates": {"sessions": 12}}
    ok = {"headline": "FX 类型的协作方式", "traits": [{"text": "会话多", "metric": "rates.sessions", "value_ref": 12}],
          "tradeoffs": [{"axis": "I", "text": "边做边想，少写计划。"}], "blind_spots": [], "caveats": []}
    ai_svc.fake.responses["narrate.persona"] = ok
    job = submit(client, "narrate.persona", {"persona": profile})
    assert job["status"] == "ok" and job["result"]["tradeoffs"][0]["axis"] == "I"
    ai_svc.fake.responses["narrate.persona"] = {**ok, "tradeoffs": [{"axis": "P", "text": "先写计划。"}]}
    created = client.post("/v1/ai/jobs", json={"task_id": "narrate.persona", "fresh": True,
                                               "slots": {"persona": profile}})
    bad = wait_job(client, created.json()["job_id"])
    assert bad["status"] == "fallback" and bad["result"]["source"] == "template"
