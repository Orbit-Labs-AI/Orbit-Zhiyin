"""Consent: off by default, explicit grants, raw never sendable, revocation cancels jobs."""

from __future__ import annotations

import time

import pytest

from tandem_backend.ai.consent import Consent
from tandem_backend.ai.engines import FakeEngine
from tandem_backend.ai.errors import AIError
from tandem_backend.ai.service import service


def pack(*classes: str) -> dict:
    return {"items": [{"key": c, "data_class": c, "enabled": True} for c in classes]
            + [{"key": "off", "data_class": "raw", "enabled": False}]}


def test_defaults_deny(ai_gw):
    svc = service(ai_gw)
    state = svc.consent()
    assert state["mode"] == "stats" and state["default_engine"] is None
    assert state["settings"] == {"daily_usd_cap": 2.0, "auto_facet_new": False, "slots": {}}
    assert all(not v for grants in state["grants"].values() for v in grants.values())
    assert [c["id"] for c in state["data_classes"]] == ["summary", "snippets", "rules", "raw"]
    with pytest.raises(AIError) as error:
        svc.submit("anything", {})
    assert error.value.code in ("unknown_task", "ai_disabled")


def test_grant_missing_and_raw(ai_gw):
    consent = Consent(ai_gw.appdb)
    assert consent.missing("claude_code", pack("summary", "snippets")) == ["snippets", "summary"]
    consent.update({"grants": {"claude_code": {"summary": True, "snippets": True}}})
    assert consent.missing("claude_code", pack("summary", "snippets")) == []
    assert consent.missing("claude_code", pack("raw")) == ["raw"]
    with pytest.raises(AIError) as error:
        consent.update({"grants": {"claude_code": {"raw": True}}})
    assert error.value.code == "consent_forbidden"
    revoked = consent.update({"grants": {"claude_code": {"snippets": False}}})
    assert revoked == [("claude_code", "snippets")]
    with ai_gw.appdb.read() as db:
        log = db.execute("SELECT engine, data_class, granted FROM ai_consent_log "
                         "ORDER BY id").fetchall()
    assert [tuple(r) for r in log] == [("claude_code", "summary", 1),
                                       ("claude_code", "snippets", 1),
                                       ("claude_code", "snippets", 0)]
    with pytest.raises(AIError):
        consent.update({"mode": "turbo"})
    with pytest.raises(AIError):
        consent.update({"settings": {"daily_usd_cap": -1}})


def test_revoke_cancels_running_and_queued(ai_svc):
    def block(req):
        req.cancel.wait(10)
        return {"answer": "late"}

    ai_svc.fake.responses["test.echo"] = block
    first = ai_svc.submit("test.echo", {"slots": {"goal": "a"}})
    second = ai_svc.submit("test.echo", {"slots": {"goal": "b"}})
    deadline = time.monotonic() + 5
    while ai_svc.job(first["job_id"])["status"] != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ai_svc.job(second["job_id"])["status"] == "queued"
    state = ai_svc.set_consent({"grants": {"fake": {"summary": False}}})
    assert set(state["cancelled_jobs"]) == {first["job_id"], second["job_id"]}
    assert ai_svc.job(first["job_id"])["status"] == "cancelled"
    assert ai_svc.job(second["job_id"])["status"] == "cancelled"
    with pytest.raises(AIError) as error:
        ai_svc.submit("test.echo", {"slots": {"goal": "c"}})
    assert error.value.code == "consent_required" and error.value.extra["missing"] == ["summary"]


def test_stats_mode_blocks_everything(ai_svc):
    ai_svc.set_consent({"mode": "stats"})
    with pytest.raises(AIError) as error:
        ai_svc.submit("test.echo", {"slots": {"goal": "a"}})
    assert (error.value.status, error.value.code) == (403, "ai_disabled")
    assert isinstance(ai_svc.engine("fake"), FakeEngine)
