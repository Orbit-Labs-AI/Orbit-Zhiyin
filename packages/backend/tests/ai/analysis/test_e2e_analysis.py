"""End to end through the ai runtime (P1): preview payload == what the engine receives (EV-14)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbit_backend.ai.redact import compact

TOKEN = "synthetic-test-token-0123456789abcdef"
BASE = "http://127.0.0.1:8765"


@pytest.fixture
def client(tmp_path, user_home):
    sys.path.insert(0, str(Path(__file__).parents[2] / "services"))
    from synthetic import write_codex_tree
    from orbit_data.service import ImportRequest, ImportService
    from orbit_data.store import Store

    from orbit_backend.ai import service as ai_service
    from orbit_backend.ai.engines import FakeEngine
    from orbit_backend.services.gateway import Gateway

    home = tmp_path / "orbit"
    write_codex_tree(tmp_path / "codex", 12)
    ImportService(Store(home)).import_source(ImportRequest("codex", tmp_path / "codex"))
    gw = Gateway(home, discovery=lambda: [], prewarm_debounce_s=3600.0)
    engine = FakeEngine({"narrate.overview": _narrative, "facet.session": _facets})
    with TestClient(gw.app(token=TOKEN, port=8765), base_url=BASE,
                    headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        ai_service(gw).register_engine("fake", engine)
        r = c.put("/v1/ai/consent", json={"mode": "agent", "default_engine": "fake",
                                          "grants": {"fake": {"summary": True, "snippets": True}}})
        assert r.status_code == 200, r.text
        yield c, gw, engine


def _narrative(request):
    return {"summary": "概览", "findings": [], "next_step": "继续。", "caveats": [], "main_evidence_ids": [],
            "audience": "user"}


def _facets(request):
    lines = request.prompt.split("<sessions>\n", 1)[1].split("\n</sessions>", 1)[0].splitlines()
    items = []
    for line in lines:
        uid = json.loads(line)["ref_id"]
        items.append({"session_uid": uid, "goal": "合成任务", "task_type": "other", "outcome": "unclear",
                      "friction_types": [], "candidates": [], "repeated_instructions": [], "summary": "合成会话",
                      "chunked": False})
    return {"items": items}


def _wait(c, job_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = c.get(f"/v1/ai/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_preview_payload_is_exactly_what_engine_sees(client):
    c, _, engine = client
    preview = c.post("/v1/ai/preview", json={"task_id": "narrate.overview", "engine": "fake"}).json()
    assert preview["preview_digest"].startswith("sha256:")
    job = c.post("/v1/ai/jobs", json={"task_id": "narrate.overview", "engine": "fake",
                                      "preview_digest": preview["preview_digest"]}).json()
    _wait(c, job["job_id"])
    assert engine.requests, "engine was not called"
    assert compact(preview["payload"]) in engine.requests[-1].prompt


def test_facet_job_writes_ai_facet(client):
    c, gw, _ = client
    with gw.reads.read() as db:
        uids = [r[0] for r in db.execute("SELECT session_uid FROM session WHERE kind='main' LIMIT 3")]
    job = c.post("/v1/ai/jobs", json={"task_id": "facet.session", "engine": "fake",
                                      "params": {"session_uids": uids}}).json()
    assert _wait(c, job["job_id"])["status"] == "ok"
    with gw.appdb.read() as db:
        rows = db.execute("SELECT session_uid, status FROM ai_facet").fetchall()
    assert {r[0] for r in rows} == set(uids) and {r[1] for r in rows} == {"ok"}


def test_auto_facet_new_respects_setting_and_skips_faceted(client, monkeypatch):
    from orbit_backend.ai import auto, auto_facet_new

    c, gw, _ = client
    monkeypatch.setattr(auto, "WINDOW_DAYS", 100000)
    assert auto_facet_new(gw) == {"status": "skipped", "reason": "disabled"}
    assert c.put("/v1/ai/consent", json={"settings": {"auto_facet_new": True}}).status_code == 200
    first = auto_facet_new(gw, limit=3)
    assert first["status"] == "submitted" and first["sessions"] == 3
    assert _wait(c, first["job_id"])["status"] == "ok"
    with gw.appdb.read() as db:
        faceted = {r[0] for r in db.execute("SELECT session_uid FROM ai_facet")}
    assert len(faceted) == 3 and not faceted & set(auto.new_session_uids(gw, 50))
    # A failed facet is retried; only status='ok' counts as done.
    retry = sorted(faceted)[0]
    with gw.appdb.write() as db:
        db.execute("UPDATE ai_facet SET status='failed' WHERE session_uid=?", (retry,))
    pending = set(auto.new_session_uids(gw, 50))
    assert retry in pending and not (faceted - {retry}) & pending
