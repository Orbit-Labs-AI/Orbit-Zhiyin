"""ASK-02 / ASK-05 / ASK-07: persona answer formatting and the studio handoff."""

from __future__ import annotations

import pytest

from orbit_backend import privacy_rules
from orbit_backend.ai import ask

PROFILE = {"n_sessions": 12, "tags": [
    {"id": "tool:shell", "label": "常用终端", "weight": 1.0, "n": 40},
    {"id": "habit:verify", "label": "先跑测试", "weight": 0.62, "n": 9}]}


@pytest.fixture(autouse=True)
def unbound_rules(user_home):
    privacy_rules.bind(None)


def answer(monkeypatch, profile, index=0):
    monkeypatch.setattr(ask, "features_profile", lambda _scope: profile)
    return ask.preset_answer("persona", index, reads=None)


def test_persona_without_type_code_says_insufficient(monkeypatch):
    body = answer(monkeypatch, PROFILE)
    assert "{'" not in body["answer"] and "样本不足，暂不判断类型" in body["answer"]
    assert "· 常用终端 100%" in body["answer"] and "· 先跑测试 62%" in body["answer"]
    assert body["next"] == "none" and "handoff" not in body


def test_persona_with_code_lists_evidence(monkeypatch):
    body = answer(monkeypatch, {**PROFILE, "code": "VPLR", "label": "验证型"})
    assert body["answer"].startswith("判定为「验证型」") and "{'" not in body["answer"]


def test_persona_dict_weights_and_empty_profile(monkeypatch):
    body = answer(monkeypatch, {"code": "X", "weights": {"终端": 0.5}})
    assert "· 终端 50%" in body["answer"]
    empty = answer(monkeypatch, {})
    assert "画像还没生成" in empty["answer"]


def test_studio_answer_carries_handoff(monkeypatch):
    monkeypatch.setitem(ask._ANSWERS, ("persona", 2), lambda q, _uid: (
        "你的盲点主要在「测试」。\n\n建议：\n· 先联系 alice@example.com 再改 /Users/alice/app", "studio"))
    body = ask.preset_answer("persona", 2, reads=None)
    handoff = body["handoff"]
    assert handoff["goal_source"] == "ask" and handoff["refs"] == body["refs"]
    assert handoff["goal"] == "先联系 [email] 再改 ~/app"
    assert len(handoff["goal"]) <= 200


def test_handoff_falls_back_to_first_sentence():
    text = "把只读命令放进允许列表。" + "含写操作仍需确认。" * 40
    handoff = ask.handoff(text, [{"kind": "metric", "id": "m"}])
    assert handoff["goal"] == "把只读命令放进允许列表。"
    assert ask.handoff("x" * 500, [])["goal"] == "x" * 200
