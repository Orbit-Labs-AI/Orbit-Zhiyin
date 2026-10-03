"""generate.hook through the real ai runtime (P1): FakeEngine returns hook slots and a draft row
lands in ai_artifact."""

from __future__ import annotations

import json

import pytest
from fakectx import hook_pack

from orbit_backend.ai.engines import FakeEngine
from orbit_backend.ai.service import service
from orbit_backend.services.gateway import Gateway

HOOK = {"matcher": "Bash", "threshold": 3, "message": "测试已连续失败，先看错误输出再重试。", "command_heads": ["pnpm test"]}


@pytest.fixture
def gw(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    gateway = Gateway(tmp_path / "orbit", discovery=lambda: [], prewarm_debounce_s=3600.0)
    yield gateway
    gateway.close()


def test_generate_hook_writes_draft_artifact(gw):
    svc = service(gw)
    engine = FakeEngine({"generate.hook": HOOK})
    svc.register_engine("fake", engine)
    svc.set_consent({"mode": "agent", "default_engine": "fake",
                     "grants": {"fake": {"summary": True, "snippets": True, "rules": True}}})
    result = svc.run("generate.hook", slots=hook_pack()["content"], engine="fake", timeout=30)
    assert result["artifact"]["kind"] == "hook"
    with gw.appdb.read() as db:
        rows = db.execute("SELECT kind, template_id, status, files FROM ai_artifact").fetchall()
    assert len(rows) == 1
    kind, template_id, status, files = rows[0]
    assert (kind, template_id, status) == ("hook", "retry-breaker", "draft")
    assert any(f["target"].startswith("claude.user_settings#/hooks/") for f in json.loads(files))
