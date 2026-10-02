"""B15: malformed AI preview / ask requests are 422s, not silently-empty answers; B14 tag labels."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tandem_backend.ai import ask
from tandem_backend.ai.errors import AIError
from tandem_backend.services import routes_ai
from tandem_backend.services.gateway import install_error_handlers


@pytest.fixture
def client(ai_svc, ai_gw):
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(routes_ai.router(ai_gw))
    return TestClient(app)


def _code(response) -> str:
    return response.json()["error"]["code"]


def test_ask_rejects_unknown_context_index_and_scope(client):
    bogus = client.get("/v1/ai/ask/presets?context=bogus")
    assert bogus.status_code == 422 and _code(bogus) == "invalid_context"
    assert client.get("/v1/ai/ask/presets?context=tools").status_code == 200
    index = client.post("/v1/ai/ask", json={"context": "persona", "preset_index": 9})
    assert index.status_code == 422 and _code(index) == "invalid_preset"
    scope = client.post("/v1/ai/ask", json={"context": "overview", "preset_index": 0, "scope": {"days": -5}})
    assert scope.status_code == 422 and _code(scope) == "invalid_scope"


@pytest.mark.parametrize("scope", [{"days": -5}, {"days": 0}, {"days": "7"}, {"start_ms": 10, "end_ms": 5},
                                   {"project_id": ""}])
def test_preview_rejects_bad_scope(client, scope):
    response = client.post("/v1/ai/preview", json={"task_id": "test.echo", "goal": "x", "scope": scope})
    assert response.status_code == 422 and _code(response) == "invalid_scope"


def test_generate_preview_needs_a_goal(client):
    for goal in (None, "", "   "):
        body = {"task_id": "generate.skill", "goal_source": "manual"} | ({"goal": goal} if goal is not None else {})
        response = client.post("/v1/ai/preview", json=body)
        assert response.status_code == 422 and _code(response) == "goal_required"
    ok = client.post("/v1/ai/preview", json={"task_id": "generate.skill", "goal": "统一提交前检查",
                                             "goal_source": "manual", "scope": {"days": 7, "agent": "x"}})
    assert ok.status_code == 200


def test_direct_calls_raise_ai_errors():
    with pytest.raises(AIError) as err:
        ask.presets("bogus", reads=None)
    assert err.value.status == 422


def test_persona_tags_read_as_labels(monkeypatch):
    profile = {"tags": [{"id": "cmd:xxx;", "ns": "cmd", "label": "xxx;", "weight": 1.0},
                        {"id": "cmd:xxx", "ns": "cmd", "label": "xxx", "weight": 0.9},
                        {"id": "cmd:b1&&", "ns": "cmd", "label": "b1&&", "weight": 0.5}]}
    monkeypatch.setattr(ask, "features_profile", lambda scope: profile)
    answer = ask.preset_answer("persona", 0, reads=None)["answer"]
    assert "{" not in answer and ";" not in answer and "&" not in answer
    assert "· xxx 100%" in answer and "· b1 50%" in answer and answer.count("xxx") == 1
    monkeypatch.setattr(ask, "features_profile", lambda scope: {**profile, "code": "T1", "label": "当前类型"})
    assert ask.preset_answer("persona", 0, reads=None)["answer"].startswith("样本不足")
