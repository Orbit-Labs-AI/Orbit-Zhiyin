"""Runner: ledger, cache, retry/fallback, cancel, daily cap, recovery, artifacts, facets."""

from __future__ import annotations

import json
import time

import pytest
from ai_support import answer_task

from tandem_backend.ai import AIUnavailable
from tandem_backend.ai.engines import EngineResult
from tandem_backend.ai.errors import AIError
from tandem_backend.ai.runner import now_ms
from tandem_backend.ai.service import AIService


def wait_done(svc, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = svc.job(job_id)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} still {job['status']}")


def count(svc, table: str) -> int:
    with svc.appdb.read() as db:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_ok_then_cached(ai_svc):
    submitted = ai_svc.submit("test.echo", {"slots": {"goal": "tidy rules"}})
    assert submitted["status"] in ("queued", "running", "ok") and not submitted["cached"]
    job = wait_done(ai_svc, submitted["job_id"])
    assert job["status"] == "ok" and job["result"] == {"answer": "ok"}
    assert [s["id"] for s in job["stages"]] == ["pack", "draft"]
    assert job["usage"]["input"] > 0
    assert (count(ai_svc, "ai_usage"), count(ai_svc, "ai_cache")) == (1, 1)
    started = time.perf_counter()
    again = ai_svc.submit("test.echo", {"slots": {"goal": "tidy rules"}})
    assert time.perf_counter() - started < 0.05
    assert again["cached"] and again["status"] == "ok"
    assert ai_svc.job(again["job_id"])["result"] == {"answer": "ok"}
    assert len(ai_svc.fake.requests) == 1
    frames, _ = ai_svc.gw.bus.since(0, ["job"])
    assert {f.event for f in frames} == {"ai.job"}
    assert any(f.data.get("stage") == "draft" for f in frames)


def test_invalid_output_retries_once_then_falls_back(ai_svc):
    ai_svc.fake.responses["test.echo"] = {"wrong": 1}
    job = wait_done(ai_svc, ai_svc.submit("test.echo", {"slots": {"goal": "x"}})["job_id"])
    assert job["status"] == "fallback"
    assert job["result"] == {"answer": "fallback:schema_invalid"}
    assert len(ai_svc.fake.requests) == 2
    assert "上一次输出未通过校验" in ai_svc.fake.requests[1].prompt
    assert count(ai_svc, "ai_cache") == 0


def test_task_validate_and_failure_without_fallback(ai_svc):
    ai_svc.register_task(answer_task("test.strict", fallback=None,
                                     validate=lambda out, pack: ["too short"]))
    job = wait_done(ai_svc, ai_svc.submit("test.strict", {"slots": {"goal": "x"}})["job_id"])
    assert job["status"] == "failed" and job["error"] == "schema_invalid"


def test_cancel_running_within_two_seconds(ai_svc):
    def block(req):
        req.cancel.wait(30)
        return {"answer": "late"}

    ai_svc.fake.responses["test.echo"] = block
    job_id = ai_svc.submit("test.echo", {"slots": {"goal": "x"}})["job_id"]
    while ai_svc.job(job_id)["status"] != "running":
        time.sleep(0.01)
    started = time.monotonic()
    assert ai_svc.cancel(job_id)["status"] == "cancelled"
    assert time.monotonic() - started < 2


def test_cancel_real_cli_process(ai_svc, fake_cli):
    fake_cli.mode = "sleep"
    ai_svc.set_consent({"default_engine": "claude_code",
                        "grants": {"claude_code": {"summary": True}}})
    job_id = ai_svc.submit("test.echo", {"slots": {"goal": "x"}})["job_id"]
    deadline = time.monotonic() + 5
    while not fake_cli.calls() and time.monotonic() < deadline:
        time.sleep(0.05)
    started = time.monotonic()
    assert ai_svc.cancel(job_id)["status"] == "cancelled"
    assert time.monotonic() - started < 2


def test_daily_cap(ai_svc):
    with ai_svc.appdb.write() as db:
        db.execute("INSERT INTO ai_usage (job_id, task_id, engine, cost_usd, cost_source, "
                   "status, ts) VALUES ('x', 't', 'fake', 2.5, 'reported', 'ok', ?)", (now_ms(),))
    with pytest.raises(AIError) as error:
        ai_svc.submit("test.echo", {"slots": {"goal": "x"}})
    assert (error.value.status, error.value.code) == (409, "budget_exhausted")
    job_id = ai_svc.submit("test.echo", {"slots": {"goal": "x"}, "override": True})["job_id"]
    assert wait_done(ai_svc, job_id)["status"] == "ok"


def test_restart_marks_interrupted_and_prunes(ai_svc, ai_gw):
    old = now_ms() - 91 * 86400 * 1000
    with ai_gw.appdb.write() as db:
        for job_id, status, created in (("aj_run", "running", now_ms()), ("aj_old", "ok", old)):
            db.execute("INSERT INTO ai_job (job_id, task_id, engine, slot, request, status, "
                       "created_at) VALUES (?, 't', 'fake', 'cheap', '{}', ?, ?)",
                       (job_id, status, created))
        db.execute("INSERT INTO ai_cache (input_digest, task_id, prompt_version, schema_version, "
                   "output, created_at, expires_at) VALUES ('k', 't', '1', '1', '{}', 1, 2)")
    fresh = AIService(ai_gw)
    job = fresh.job("aj_run")
    assert (job["status"], job["error"]) == ("failed", "interrupted")
    with pytest.raises(AIError):
        fresh.job("aj_old")
    assert count(fresh, "ai_cache") == 0
    fresh.close()


def artifact_task(task_id: str) -> dict:
    def finalize(output, pack, source):
        return {"status": "ok", "result": output, "facets": [
            {"session_uid": "s1", "content_hash": "h1", "prompt_version": "facet@1.1",
             "schema_version": "1.1", "status": "ok", "json": {"goal": "x"}}],
            "artifact": {"kind": "rule", "template_id": "rules/paragraph@1", "name": "r1",
                         "payload": {"text": "always run tests"},
                         "files": [{"path": "CLAUDE.md", "lines": [["+", "always run tests"]]}],
                         "checks": {"lint": {"status": "ok"}}, "personalized": True}}

    return answer_task(task_id, cache_ttl_s=0, finalize=finalize)


def test_artifact_dedup_and_facets(ai_svc):
    ai_svc.register_task(artifact_task("test.gen"))
    first = wait_done(ai_svc, ai_svc.submit("test.gen", {"slots": {"goal": "a"}})["job_id"])
    second = wait_done(ai_svc, ai_svc.submit("test.gen", {"slots": {"goal": "a"}})["job_id"])
    assert first["artifact_id"] and first["artifact_id"] == second["artifact_id"]
    assert count(ai_svc, "ai_artifact") == 1 and len(ai_svc.fake.requests) == 2
    artifact = ai_svc.artifact(first["artifact_id"])
    assert artifact["status"] == "draft" and artifact["personalized"] is True
    assert artifact["files"][0]["lines"] == [["+", "always run tests"]]
    listed = ai_svc.artifacts(kind="rule")
    assert listed[0]["checks"] == {"lint": "ok"}
    assert ai_svc.set_artifact_status(first["artifact_id"], "installed",
                                      install_id="in_1")["install_id"] == "in_1"
    facets = ai_svc.facets(["s1", "s2"])
    assert facets == [{"session_uid": "s1", "status": "ok", "json": {"goal": "x"},
                       "model_id": "fake-cheap", "prompt_version": "facet@1.1"}]


def test_sync_run_for_other_modules(ai_svc):
    result = ai_svc.run("test.echo", slots={"candidates": [1, 2]})
    assert result["status"] == "ok" and result["result"] == {"answer": "ok"}
    ai_svc.fake.responses["test.echo"] = EngineResult(error="engine_error")
    assert ai_svc.run("test.echo", slots={"c": 3})["status"] == "fallback"
    ai_svc.set_consent({"mode": "stats"})
    with pytest.raises(AIUnavailable) as error:
        ai_svc.run("test.echo", slots={"c": 4})
    assert error.value.reason == "ai_disabled"
    assert not ai_svc.runner.waiters and not ai_svc.runner.results


def test_preview_digest_and_budget(ai_svc):
    ai_svc.register_task(answer_task("test.preview", requires_preview=True, input_budget=50))
    req = {"slots": {"goal": "a", "notes": "b"}, "selection": {"items": {"notes": False}}}
    preview = ai_svc.preview("test.preview", req)
    assert preview["payload"] == {"goal": "a"} and preview["engine"] == "fake"
    assert [i["consent"] for i in preview["items"]] == ["granted", "granted"]
    assert preview["preview_digest"].startswith("sha256:") and not preview["over_budget"]
    with pytest.raises(AIError) as error:
        ai_svc.submit("test.preview", req)
    assert error.value.code == "preview_stale"
    ok = ai_svc.submit("test.preview", {**req, "preview_digest": preview["preview_digest"]})
    assert wait_done(ai_svc, ok["job_id"])["status"] == "ok"
    big = {"slots": {"goal": "x" * 1000}}
    assert ai_svc.preview("test.preview", big)["over_budget"]
    with pytest.raises(AIError) as error:
        ai_svc.submit("test.preview", {**big, "preview_digest": ai_svc.preview(
            "test.preview", big)["preview_digest"]})
    assert error.value.status == 413


def test_usage_summary(ai_svc):
    wait_done(ai_svc, ai_svc.submit("test.echo", {"slots": {"goal": "u"}})["job_id"])
    usage = ai_svc.usage(30)
    assert usage["totals"]["calls"] == 1 and usage["by_task"][0]["task_id"] == "test.echo"
    assert usage["by_engine"][0]["engine"] == "fake" and len(usage["by_day"]) == 1
    assert usage["estimate_error"]["n"] == 1 and usage["daily_cap"] == 2.0
    assert json.dumps(usage)


def test_job_reports_telemetry_and_notifies(ai_svc, monkeypatch):
    from tandem_backend import platform

    metrics, notes = [], []
    monkeypatch.setattr(platform, "record", lambda name, value=1.0, **tags:
                        metrics.append((name, tags.get("task"))))
    monkeypatch.setattr(platform, "notify", notes.append)
    job = wait_done(ai_svc, ai_svc.submit("test.echo", {"slots": {"goal": "n"}})["job_id"])
    deadline = time.monotonic() + 2
    while not notes and time.monotonic() < deadline:
        time.sleep(0.01)
    assert {("ai.tokens", "test.echo"), ("ai.job", "test.echo")} <= set(metrics)
    assert notes[0]["type"] == "ai_job_done" and notes[0]["payload"]["job_id"] == job["job_id"]
    notes.clear()
    ai_svc.run("test.echo", slots={"goal": "sync"})  # synchronous callers are not notified
    ai_svc.submit("test.echo", {"slots": {"goal": "bg"}, "params": {"auto": True}})
    time.sleep(0.2)
    assert notes == []
