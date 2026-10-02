"""api/insights.py mounted on a standalone FastAPI app (no routes.py, no store)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from signal_fixtures import Session, bundle, retry_session

from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.service import analyze_context
from tandem_backend.api.insights import build_router
from tandem_backend.models import stable_id


def corpus():
    sessions = [retry_session(f"r{i}", project="p1") for i in range(3)]
    chat = Session("c0", project="p2")
    chat.user("请解释这个函数")
    chat.reply()
    chat.user("不对，我说的是另一个函数")
    return [*sessions, chat]


@pytest.fixture
def client():
    data = bundle(corpus())
    pid = stable_id("tool_env_failure", "retry_loop:pytest", "all", "all")

    def get_result(scope):
        context = AnalysisContext.select(data, scope)
        return context, analyze_context(context, False, with_recommendations=False)

    def get_labels(scope):
        return [{"target_kind": "problem", "target_id": pid, "label": "dismissed"}]

    app = FastAPI()
    app.include_router(build_router(get_result, get_labels=get_labels))
    return TestClient(app)


def test_metrics_endpoint(client):
    r = client.get("/v1/analytics/metrics", params={
        "metric": ["sessions", "retry_loop_session_rate"], "group_by": "project", "bucket": "day"})
    assert r.status_code == 200
    body = r.json()["metrics"]
    assert body["sessions"]["overall"]["value"] == 4
    assert {g["key"]: g["value"] for g in body["sessions"]["groups"]} == {"p1": 3, "p2": 1}
    rate = body["retry_loop_session_rate"]["overall"]
    assert rate["n"] == 3 and rate["status"] == "insufficient" and rate["value"] is None
    scoped = client.get("/v1/analytics/metrics", params={"metric": "sessions", "project_ids": "p1"})
    assert scoped.json()["metrics"]["sessions"]["overall"]["value"] == 3


@pytest.mark.parametrize("params", [
    {"metric": "nope"}, {"group_by": "hour"}, {"bucket": "month"},
    {"display_timezone": "Mars/Base"}, {"from_ts": 10, "until_ts": 5},
])
def test_metrics_endpoint_rejects_bad_parameters(client, params):
    assert client.get("/v1/analytics/metrics", params=params).status_code == 422


def test_signals_endpoint(client):
    r = client.get("/v1/analytics/signals", params={"kind": "retry_loop"})
    assert r.status_code == 200
    rows = r.json()["signals"]
    assert {s["session_uid"] for s in rows} == {"r0", "r1", "r2"}
    assert all(s["kind"] == "retry_loop" for s in rows)
    assert r.json()["summary"]["c0"]["correction"] == 1
    assert client.get("/v1/analytics/signals", params={"kind": "nope"}).status_code == 422


def test_problems_endpoint_reads_labels(client):
    r = client.get("/v1/analytics/problems")
    assert r.status_code == 200 and "candidates" not in r.json()
    [problem] = [p for p in r.json()["problems"] if p["scope"] == "all"]
    assert problem["key"] == "retry_loop:pytest" and problem["status"] == "dismissed"
    assert problem["session_uids"] == ["r0", "r1", "r2"]
    full = client.get("/v1/analytics/problems", params={"include_candidates": True}).json()
    assert "candidates" in full
    assert client.get("/v1/analytics/problems", params={"until_ts": "x"}).status_code == 422


def test_session_facts_endpoint(client):
    r = client.get("/v1/analytics/sessions/r0/facts")
    assert r.status_code == 200
    body = r.json()
    assert body["facts"]["signals_summary"]["retry_loop"] == 1
    assert [m["kind"] for m in body["key_moments"]["moments"]][0] == "goal"
    assert [s["kind"] for s in body["signals"]] == ["retry_loop"]
    assert client.get("/v1/analytics/sessions/missing/facts").status_code == 404
    excluded = client.get("/v1/analytics/sessions/r0/facts", params={"project_ids": "p2"})
    assert excluded.status_code == 404


def test_tool_calls_endpoint(client):
    r = client.get("/v1/analytics/tools/Bash/calls", params={"limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 9 and len(body["items"]) == 2
    assert {"session_uid", "event_uid", "exit_code", "duration_ms", "argument_summary"} <= set(body["items"][0])
    assert client.get("/v1/analytics/tools/Nope/calls").status_code == 404
    assert client.get("/v1/analytics/tools/Bash/calls", params={"limit": 51}).status_code == 422
    assert client.get("/v1/analytics/tools/Bash/calls", params={"limit": 0}).status_code == 422
