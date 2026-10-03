"""Notifications that used to vanish: AI job completion and maintenance disk-low (both went
through the package-level ``platform.notify``), plus the ``min_run_s`` completion filter."""

from __future__ import annotations

import shutil
import time
from collections import namedtuple

import pytest
from ai_support import answer_task
from realtime_fixtures import NOW, Orbit

from orbit_backend import platform
from orbit_backend.ai import engines, registry
from orbit_backend.ai.engines import FakeEngine
from orbit_backend.ai.service import AIService, service
from orbit_backend.realtime.service import Realtime


def notes(client, kind):
    return client.get(f"/v1/notifications?state=all&type={kind}").json()["items"]


def wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


@pytest.fixture
def ai_ready(monkeypatch, tmp_path):
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", f"{empty}:/usr/bin:/bin")
    monkeypatch.setattr(engines, "FALLBACK_DIRS", ())
    monkeypatch.setattr(engines, "_help_cache", {})
    monkeypatch.setattr(AIService, "_builder", lambda self: None)
    task = answer_task()
    registry.register(task)
    yield
    registry.unregister(task["task_id"])


def test_ai_job_done_is_stored(gateway_factory, ai_ready):
    client, gw = gateway_factory()
    svc = service(gw)
    svc.register_engine("fake", FakeEngine({"*": {"answer": "ok"}}))
    svc.set_consent({"mode": "agent", "default_engine": "fake",
                     "grants": {"fake": {"summary": True}}})
    preview = client.post("/v1/ai/preview", json={"task_id": "test.echo", "goal": "fix tests",
                                                  "goal_source": "manual"}).json()
    created = client.post("/v1/ai/jobs", json={"task_id": "test.echo", "goal": "fix tests",
                                               "preview_digest": preview["preview_digest"]})
    job_id = created.json()["job_id"]
    items = wait(lambda: notes(client, "ai_job_done"))
    assert items[0]["payload"]["job_id"] == job_id and items[0]["payload"]["status"] == "ok"
    assert items[0]["state"] == "delivered" and "banner" in items[0]["channels"]


def test_package_notify_reaches_the_notifier(gateway_factory):
    client, _ = gateway_factory()
    assert platform.notify({"type": "system", "key": "probe", "title": "probe"}) is not None
    assert [n["title"] for n in notes(client, "system")] == ["probe"]


def test_disk_low_is_stored(gateway_factory, monkeypatch):
    client, gw = gateway_factory()
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10, 9, 1024))
    result = gw.platform.maintenance.run("storage_report")
    assert result["ok"] and result["detail"]["free_bytes"] == 1024
    (item,) = notes(client, "system")
    assert item["title"] == "磁盘空间不足" and item["payload"] == {"free_bytes": 1024}


def test_min_run_policy_validation(gateway_factory):
    client, _ = gateway_factory()
    policy = client.get("/v1/notifications/policy").json()
    assert policy["min_run_s"] == {"just_finished": 600}
    ok = client.put("/v1/notifications/policy", json={"min_run_s": {"done": 0}})
    assert ok.status_code == 200 and ok.json()["min_run_s"]["just_finished"] == 0
    bad = client.put("/v1/notifications/policy", json={"min_run_s": {"just_finished": -1}})
    assert bad.status_code == 422
    assert client.put("/v1/notifications/policy",
                      json={"min_run_s": {"failing": 5}}).status_code == 422


def test_short_runs_finish_quietly(gateway_factory, tmp_path):
    home = tmp_path / "orbit"
    home.mkdir()
    t = Orbit(home)
    for uid, minutes in (("short", 3), ("long", 25)):
        t.session(uid, started=NOW - minutes * 60_000)
        t.event(uid, NOW - 1_000)
    t.db.close()
    client, gw = gateway_factory(home=home)
    clock = {"now": NOW / 1000}
    rt = Realtime(gw, clock=lambda: clock["now"])
    rt.snapshot(now=NOW / 1000)
    snap = rt.snapshot(now=NOW / 1000 + 100)
    assert {s["session_uid"]: s["state"] for s in snap["sessions"]} == {
        "short": "just_finished", "long": "just_finished"}  # the badge state stays
    done = notes(client, "just_finished")
    assert [n["session_uid"] for n in done] == ["long"]
