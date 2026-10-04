"""Job runner: one serial queue per engine, ``RunContext`` (contract C2) and persistence.

``ctx.call()`` = cache → engine → JSON Schema + task validate → one retry with the errors
appended → ``ai_usage`` row. Jobs write their stages, log (≤200 lines) and progress to
``ai_job`` and publish ``ai.job`` frames on the ``job`` topic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from contextlib import AbstractContextManager

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .. import platform
from .engines import EngineRequest, EngineResult
from .errors import CallFailed, Cancelled

log = logging.getLogger(__name__)

LOG_LINES = 200
JOB_RETENTION_MS = 90 * 86400 * 1000
CACHE_ROWS = 2000
# truncated/refused: the same request would hit the same max_tokens / safety decline again.
NO_RETRY = ("not_logged_in", "budget_exceeded", "timeout", "truncated", "refused")


def now_ms() -> int:
    return int(time.time() * 1000)


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def cache_key(task_id: str, prompt_version: str, schema_version: str, system: str,
              prompt: str, engine: str, model: str | None) -> str:
    """The engine and model answer the request too: another model is a new call, not a hit."""
    raw = canonical_json([task_id, prompt_version, schema_version, system, prompt, engine, model])
    return hashlib.sha256(raw.encode()).hexdigest()


def schema_errors(output, schema: dict) -> list[str]:
    try:
        validator = Draft202012Validator(schema)
        return [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
                for e in list(validator.iter_errors(output))[:10]]
    except SchemaError as error:
        return [f"schema: {error.message}"]


class RunContext:
    def __init__(self, runner: Runner, job: dict):
        self.runner = runner
        self.job_id = job["job_id"]
        self.task = job["task"]
        self.pack = job["pack"]
        self.template = job.get("template") or "v1"
        self.engine = job["engine"]
        self.home = runner.svc.home
        self.params = job.get("params") or {}
        self.slot = job.get("slot") or self.task["slot"]
        self.override_budget = bool(job.get("override_budget"))
        self.cancel_event = job["cancel"]
        self.fresh = bool(job.get("fresh"))  # 「重新生成」: read no cached output
        self.stages: list[dict] = []
        self.lines: list[str] = []
        self.n = self.total = 0
        self.tokens = self.calls = self.cache_hits = 0
        self.model_id: str | None = None
        self.started: dict[str, float] = {}

    def granted(self, data_class: str) -> bool:
        """Whether this job's engine may receive ``data_class`` (tasks that pick their own
        queries at run time, like ask.question, check this before sending results)."""
        return self.runner.svc.consent_store.granted(self.engine, data_class)

    # -- model calls ---------------------------------------------------------------------
    def call(self, *, system=None, prompt=None, schema=None, slot=None, validate=None,
             task_id=None) -> dict:
        task = self.task
        task_id = task_id or task["task_id"]
        system = task["system"] if system is None else system
        prompt = task["build_prompt"](self.pack) if prompt is None else prompt
        schema = schema or task["schema"]
        validate = validate or task["validate"]
        slot = slot or self.slot
        ttl = task["cache_ttl_s"]
        model = self.runner.svc.model_for(self.engine, slot)
        key = cache_key(task_id, task["prompt_version"], task["schema_version"], system, prompt,
                        self.engine, model)
        if ttl != 0 and not self.fresh:
            cached = self.runner.cache_get(key)
            if cached is not None:
                errors = schema_errors(cached, schema)
                if not errors and validate is not None:
                    errors = list(validate(cached, self.pack) or [])
                if not errors:
                    if self.cancelled():
                        raise Cancelled()
                    self.cache_hits += 1
                    return cached
                self.log("缓存未通过当前证据校验，重新生成")
        engine = self.runner.svc.engine(self.engine)
        attempt_prompt, last = prompt, "schema_invalid"
        for attempt in range(2):
            if self.cancelled():
                raise Cancelled()
            request = EngineRequest(
                system=system, prompt=attempt_prompt, schema=schema, model=model,
                max_budget_usd=task["max_budget_usd"], timeout_s=task["timeout_s"],
                cancel=self.cancel_event, task_id=task_id, job_id=self.job_id, slot=slot,
                max_tokens=task["out_budget"])
            with self.runner.svc.call_budget(task["max_budget_usd"], override=self.override_budget):
                if self.cancelled():
                    raise Cancelled()
                try:
                    result = engine.call(request)
                except Exception as error:  # A broken engine must not kill the worker thread.
                    log.exception("engine %s failed", self.engine)
                    result = EngineResult(error="engine_error", detail=type(error).__name__)
                self.calls += 1
                self.model_id = result.model_id or self.model_id
                self.tokens += sum(result.usage.values())
                errors = []
                if result.error is None:
                    errors = schema_errors(result.output, schema)
                    if not errors and validate is not None:
                        errors = list(validate(result.output, self.pack) or [])
                status = result.error or ("invalid" if errors else "ok")
                self.runner.record_usage(self, task_id, result, system, attempt_prompt, status)
            if result.error == "cancelled" or self.cancelled():
                raise Cancelled()
            if result.error in NO_RETRY:
                raise CallFailed(result.error, result.detail)
            if result.error is None and not errors:
                if ttl != 0:
                    self.runner.cache_put(key, task, result.output, result.model_id, ttl)
                return result.output
            last = result.error or "schema_invalid"
            self.log(f"第 {attempt + 1} 次输出未通过：{'; '.join(errors[:3]) or last}")
            if errors:
                attempt_prompt = (prompt + "\n\n上一次输出未通过校验，请修正：\n- "
                                  + "\n- ".join(errors[:10]))
        raise CallFailed(last)

    # -- progress ------------------------------------------------------------------------
    def stage(self, stage_id: str, status: str, message: str | None = None) -> None:
        entry = next((s for s in self.stages if s["id"] == stage_id), None)
        if entry is None:
            entry = {"id": stage_id, "status": status, "duration_ms": None}
            self.stages.append(entry)
        entry["status"] = status
        if message:
            entry["message"] = message
        if status == "running":
            self.started[stage_id] = time.monotonic()
        elif stage_id in self.started:
            entry["duration_ms"] = int((time.monotonic() - self.started.pop(stage_id)) * 1000)
        else:
            entry["duration_ms"] = entry["duration_ms"] or 0
        if message:
            self.lines.append(f"[{stage_id}] {message}")
            self.lines = self.lines[-LOG_LINES:]
        self.runner.update(self.job_id, stage=stage_id, stages=self.stages, log=self.lines)
        self.runner.emit(self, stage_id, status, message)

    def log(self, line: str) -> None:
        self.lines.append(str(line))
        self.lines = self.lines[-LOG_LINES:]
        self.runner.update(self.job_id, log=self.lines)
        self.runner.emit(self, None, None, str(line))

    def progress(self, n: int, total: int) -> None:
        self.n, self.total = n, total
        self.runner.update(self.job_id, progress_n=n, progress_total=total)
        self.runner.emit(self, None, None, None)

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def reads(self) -> AbstractContextManager:
        return self.runner.svc.gw.reads.read()

    def read_app(self) -> AbstractContextManager:
        return self.runner.svc.appdb.read()


def default_run(ctx: RunContext, pack: dict) -> dict | None:
    task = ctx.task
    ctx.stage("pack", "ok")
    ctx.stage("draft", "running")
    try:
        output = ctx.call()
        source = "cache" if ctx.calls == 0 and ctx.cache_hits else "ai"
        ctx.stage("draft", "ok")
    except CallFailed as error:
        ctx.stage("draft", "failed", error.reason)
        output = task["fallback"](pack, error.reason) if task["fallback"] else None
        if output is None:
            return {"status": "failed", "result": {"error": error.reason}, "artifact": None,
                    "facets": None}
        source = "fallback"
    if task["finalize"]:
        result = task["finalize"](output, pack, source)
        if result is not None:
            return result
    return {"status": "fallback" if source == "fallback" else "ok", "result": output,
            "artifact": None, "facets": None}


class Runner:
    def __init__(self, svc):
        self.svc = svc
        self.appdb = svc.appdb
        self.lock = threading.Lock()
        self.queues: dict[str, queue.Queue] = {}
        self.states: dict[str, str] = {}
        self.cancels: dict[str, threading.Event] = {}
        self.done: dict[str, threading.Event] = {}
        self.results: dict[str, dict] = {}
        self.waiters: set[str] = set()

    # -- lifecycle -----------------------------------------------------------------------
    def recover(self) -> None:
        """Mark jobs left by a previous process as interrupted, then prune old rows."""
        now = now_ms()
        with self.appdb.write() as db:
            db.execute("UPDATE ai_job SET status = 'failed', error = 'interrupted', "
                       "finished_at = ? WHERE status IN ('queued', 'running')", (now,))
            db.execute("DELETE FROM ai_job WHERE created_at < ? AND artifact_id IS NULL",
                       (now - JOB_RETENTION_MS,))
            db.execute("DELETE FROM ai_cache WHERE expires_at IS NOT NULL AND expires_at <= ?",
                       (now,))
            db.execute("DELETE FROM ai_cache WHERE input_digest NOT IN (SELECT input_digest "
                       "FROM ai_cache ORDER BY COALESCE(last_hit_at, created_at) DESC LIMIT ?)",
                       (CACHE_ROWS,))

    def close(self) -> None:
        with self.lock:
            for job_id, state in self.states.items():
                if state in ("queued", "running"):
                    self.cancels[job_id].set()
            for q in self.queues.values():
                q.put(None)
            self.queues.clear()

    # -- queueing ------------------------------------------------------------------------
    def enqueue(self, job: dict, inline: bool = False) -> None:
        job_id = job["job_id"]
        job["cancel"] = threading.Event()
        with self.lock:
            self.states[job_id] = "queued"
            self.cancels[job_id] = job["cancel"]
            self.done[job_id] = threading.Event()
            if not inline:
                q = self.queues.get(job["engine"])
                if q is None:
                    q = self.queues[job["engine"]] = queue.Queue()
                    threading.Thread(target=self._worker, args=(q,), daemon=True,
                                     name=f"orbit-ai-{job['engine']}").start()
                q.put(job)
        if inline:
            self._execute(job)

    def _worker(self, q: queue.Queue) -> None:
        while (job := q.get()) is not None:
            try:
                self._execute(job)
            except Exception:  # Persistence failures must not stop the queue.
                log.exception("AI job %s crashed", job.get("job_id"))

    def cancel(self, job_id: str, wait_s: float = 2.5) -> str | None:
        with self.lock:
            state = self.states.get(job_id)
            event, done = self.cancels.get(job_id), self.done.get(job_id)
            if state == "queued":
                self.states[job_id] = "cancelled"
        if state == "queued":
            event.set()
            self.update(job_id, status="cancelled", finished_at=now_ms())
            self.svc.publish({"job_id": job_id, "status": "cancelled"})
            self._finish(job_id)
        elif state == "running":
            event.set()
            done.wait(wait_s)
        return state

    def active(self, engine: str | None = None) -> list[str]:
        with self.appdb.read() as db:
            sql = "SELECT job_id FROM ai_job WHERE status IN ('queued', 'running')"
            args: tuple = ()
            if engine is not None:
                sql, args = sql + " AND engine = ?", (engine,)
            return [row[0] for row in db.execute(sql, args)]

    # -- execution -----------------------------------------------------------------------
    def _execute(self, job: dict) -> None:
        job_id = job["job_id"]
        with self.lock:
            if self.states.get(job_id) != "queued":
                return
            self.states[job_id] = "running"
        self.update(job_id, status="running", started_at=now_ms())
        ctx = RunContext(self, job)
        self.emit(ctx, None, None, None, status="running")
        result, error = None, None
        t0 = time.monotonic()
        try:
            run = ctx.task["run"] or default_run
            result = run(ctx, job["pack"])
            status = (result or {}).get("status") or "failed"
            if status == "failed":
                error = ((result or {}).get("result") or {}).get("error") or "failed"
        except Cancelled:
            status = "cancelled"
        except Exception as exc:
            log.exception("AI job %s failed", job_id)
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        if ctx.cancelled() and status != "failed":
            status = "cancelled"
        artifact_id = None
        result = result or {}
        with self.appdb.write() as db:
            if result.get("artifact"):
                artifact_id = self._save_artifact(db, job, result["artifact"],
                                                  draft=status == "cancelled")
            for facet in result.get("facets") or []:
                self._save_facet(db, job_id, facet, ctx.model_id)
            cached = int(ctx.calls == 0 and ctx.cache_hits > 0)
            db.execute(
                "UPDATE ai_job SET status = ?, result = ?, error = ?, cached = ?, "
                "artifact_id = ?, finished_at = ?, stages = ?, log = ? WHERE job_id = ?",
                (status, None if "result" not in result else json.dumps(
                    result.get("result"), ensure_ascii=False, default=str),
                 error, cached, artifact_id, now_ms(), json.dumps(ctx.stages, ensure_ascii=False),
                 json.dumps(ctx.lines, ensure_ascii=False), job_id))
        with self.lock:
            self.states[job_id] = status
            if job_id in self.waiters:
                self.results[job_id] = {"status": status, "result": result.get("result") or {},
                                        "artifact": result.get("artifact"),
                                        "facets": result.get("facets"),
                                        "artifact_id": artifact_id, "error": error}
        self.emit(ctx, None, None, error, status=status)
        self._report(ctx, job, status, error, artifact_id, time.monotonic() - t0)
        self._finish(job_id)

    def _report(self, ctx: RunContext, job: dict, status: str, error, artifact_id,
                elapsed_s: float) -> None:
        """Platform telemetry for every job; a notification only for jobs a person started
        (not ``run()`` callers waiting synchronously, not background ``params.auto`` runs)."""
        task_id = ctx.task["task_id"]
        platform.record("ai.job", elapsed_s * 1000, task=task_id, engine=ctx.engine,
                        status=status)
        if status == "cancelled" or job["job_id"] in self.waiters or ctx.params.get("auto"):
            return
        title = ctx.task.get("title") or task_id
        platform.notify({"type": "ai_job_done", "key": f"ai_job_done:{job['job_id']}",
                         "title": f"AI 任务{'完成' if status != 'failed' else '失败'}：{title}",
                         "body": error or "", "severity": "attention" if status == "failed"
                         else "info",
                         "payload": {"job_id": job["job_id"], "task_id": task_id,
                                     "status": status, "artifact_id": artifact_id}})

    def _finish(self, job_id: str) -> None:
        with self.lock:
            self.cancels.pop(job_id, None)
            done = self.done.get(job_id) if job_id in self.waiters else self.done.pop(job_id, None)
            if job_id not in self.waiters:
                self.states.pop(job_id, None)
        if done is not None:
            done.set()

    def _save_artifact(self, db, job: dict, artifact: dict, draft: bool) -> str:
        body = {key: artifact.get(key) for key in ("kind", "template_id", "payload", "files")}
        content_hash = artifact.get("content_hash") or "sha256:" + hashlib.sha256(
            canonical_json(body).encode()).hexdigest()
        row = db.execute("SELECT artifact_id FROM ai_artifact WHERE content_hash = ?",
                         (content_hash,)).fetchone()
        now = now_ms()
        if row is not None:
            db.execute("UPDATE ai_artifact SET updated_at = ? WHERE artifact_id = ?",
                       (now, row[0]))
            return row[0]
        artifact_id = "af_" + uuid.uuid4().hex[:16]
        status = "draft" if draft else artifact.get("status") or "draft"

        def dumps(key: str, default):
            return json.dumps(artifact.get(key, default), ensure_ascii=False, default=str)

        db.execute(
            "INSERT INTO ai_artifact (artifact_id, job_id, kind, template_id, name, title, goal, "
            "goal_source, slots, payload, files, checks, evidence, personalized, content_hash, "
            "preview_digest, status, install_id, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (artifact_id, job["job_id"], artifact["kind"], artifact.get("template_id") or "custom",
             artifact.get("name") or artifact["kind"], artifact.get("title"),
             artifact.get("goal", job.get("goal")),
             artifact.get("goal_source", job.get("goal_source")), dumps("slots", {}),
             dumps("payload", {}), dumps("files", []), dumps("checks", {}),
             dumps("evidence", []), int(bool(artifact.get("personalized", False))),
             content_hash, artifact.get("preview_digest", job.get("preview_digest")), status,
             now, now))
        return artifact_id

    @staticmethod
    def _save_facet(db, job_id: str, facet: dict, model_id: str | None) -> None:
        body = facet.get("json")
        db.execute(
            "INSERT INTO ai_facet VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(session_uid, "
            "prompt_version, schema_version) DO UPDATE SET content_hash = excluded.content_hash, "
            "model_id = excluded.model_id, status = excluded.status, json = excluded.json, "
            "job_id = excluded.job_id, created_at = excluded.created_at",
            (facet["session_uid"], facet.get("prompt_version") or "1",
             facet.get("schema_version") or "1", facet.get("content_hash") or "",
             facet.get("model_id") or model_id, facet.get("status") or "ok",
             None if body is None else json.dumps(body, ensure_ascii=False), job_id, now_ms()))

    # -- persistence helpers -------------------------------------------------------------
    def update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        values = [json.dumps(v, ensure_ascii=False) if k in ("stages", "log") else v
                  for k, v in fields.items()]
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.appdb.write() as db:
            db.execute(f"UPDATE ai_job SET {assignments} WHERE job_id = ?", (*values, job_id))

    def emit(self, ctx: RunContext, stage, stage_status, message, status: str = "running"):
        self.svc.publish({"job_id": ctx.job_id, "task_id": ctx.task["task_id"],
                          "status": status, "stage": stage, "stage_status": stage_status,
                          "progress": [ctx.n, ctx.total], "tokens": ctx.tokens,
                          "message": message})

    def record_usage(self, ctx: RunContext, task_id: str, result: EngineResult, system: str,
                     prompt: str, status: str) -> None:
        usage = result.usage
        with self.appdb.write() as db:
            db.execute(
                "INSERT INTO ai_usage (job_id, task_id, engine, model_id, input_tokens, "
                "cache_read_tokens, cache_write_tokens, output_tokens, est_input_tokens, "
                "cost_usd, cost_source, latency_ms, status, ts) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ctx.job_id, task_id, ctx.engine, result.model_id, usage.get("input"),
                 usage.get("cache_read"), usage.get("cache_write"), usage.get("output"),
                 (len(system) + len(prompt)) // 4, result.cost_usd, result.cost_source,
                 result.latency_ms, status, now_ms()))
        tags = {"task": task_id, "engine": ctx.engine}
        platform.record("ai.tokens", sum(usage.values()), **tags)
        if result.cost_usd:
            platform.record("ai.cost_usd", result.cost_usd, **tags)

    def cache_get(self, key: str) -> dict | None:
        now = now_ms()
        with self.appdb.read() as db:
            row = db.execute("SELECT output FROM ai_cache WHERE input_digest = ? AND "
                             "(expires_at IS NULL OR expires_at > ?)", (key, now)).fetchone()
        if row is None:
            return None
        with self.appdb.write() as db:
            db.execute("UPDATE ai_cache SET hits = hits + 1, last_hit_at = ? "
                       "WHERE input_digest = ?", (now, key))
        return json.loads(row[0])

    def cache_put(self, key: str, task: dict, output: dict, model_id, ttl) -> None:
        now = now_ms()
        expires = None if ttl is None else now + int(ttl * 1000)
        with self.appdb.write() as db:
            db.execute("INSERT INTO ai_cache (input_digest, task_id, prompt_version, "
                       "schema_version, output, model_id, created_at, expires_at) VALUES "
                       "(?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(input_digest) DO UPDATE SET "
                       "output = excluded.output, model_id = excluded.model_id, "
                       "created_at = excluded.created_at, expires_at = excluded.expires_at",
                       (key, task["task_id"], task["prompt_version"], task["schema_version"],
                        json.dumps(output, ensure_ascii=False), model_id, now, expires))
