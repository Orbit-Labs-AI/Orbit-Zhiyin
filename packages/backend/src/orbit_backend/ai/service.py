"""``AIService``: the one entry point other modules and the routes use.

Recommend / install call ``service(gw).run(...)``; AI never imports them. Context packs
come from ``orbit_backend.ai.pack.build``; ``fallback_pack`` (a minimal pack from the
request's slots / goal) is only used when ``_builder`` is patched to return None in tests.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import engines as engines_mod
from . import prices, registry
from .capabilities import Capabilities
from .consent import ALLOWED, Consent
from .errors import AIError, AIUnavailable
from .runner import Runner, cache_key, canonical_json, now_ms

PREFERENCE = {"agent": ("claude_code", "codex", "api_key", "fake"),
              "api": ("api_key", "claude_code", "codex", "fake"),
              "stats": ("claude_code", "codex", "api_key", "fake")}
ARTIFACT_JSON = ("slots", "payload", "files", "checks", "evidence")
_lock = threading.Lock()


def pack_digest(task_id: str, prompt_version: str, goal, content: dict) -> str:
    raw = canonical_json({"task": task_id, "pv": prompt_version, "goal": goal,
                          "content": content})
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def fallback_pack(task: dict, req: dict) -> dict:
    """Minimal C3 pack from the request's slots / goal (test seam, see ``_builder``)."""
    goal = req.get("goal")
    content = req.get("slots") or {"goal": {"text": goal, "source": req.get("goal_source")}}
    chosen = ((req.get("selection") or {}).get("items") or {})
    items, sent = [], {}
    for key, value in content.items():
        text = json.dumps(value, ensure_ascii=False, indent=1)
        enabled = bool(chosen.get(key, True))
        items.append({"key": key, "label": key, "desc": "", "data_class": "summary",
                      "enabled": enabled, "tokens": len(text) // 4 + 1, "redaction_hits": 0,
                      "preview": text.splitlines()[:8]})
        if enabled:
            sent[key] = value
    return {"task_id": task["task_id"], "goal": goal, "goal_source": req.get("goal_source"),
            "items": items, "content": sent, "refs": {}, "numbers": [],
            "total_tokens": sum(i["tokens"] for i in items if i["enabled"]),
            "redaction_hits": 0, "batches": None,
            "preview_digest": pack_digest(task["task_id"], task["prompt_version"], goal, sent)}


def _local_midnight_ms() -> int:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(today.timestamp() * 1000)


def _loads(value):
    return None if value is None else json.loads(value)


class AIService:
    def __init__(self, gw):
        self.gw = gw
        self.appdb = gw.appdb
        self.home = Path(gw.home)
        self._engines: dict = engines_mod.default_engines(self.home)
        self.consent_store = Consent(self.appdb)
        self.caps = Capabilities(self.appdb, self.home)
        self.runner = Runner(self)
        self.runner.recover()

    # -- plumbing ------------------------------------------------------------------------
    def register_engine(self, engine_id: str, engine) -> None:
        self._engines[engine_id] = engine
        self.caps.forget(engine_id)

    def engine(self, engine_id: str):
        return self._engines[engine_id]

    def publish(self, data: dict) -> None:
        bus = getattr(self.gw, "bus", None)
        if bus is not None:
            bus.publish("job", "ai.job", data)

    def model_for(self, engine_id: str, slot: str) -> str | None:
        override = (self.consent_store.settings()["slots"].get(engine_id) or {}).get(slot)
        if override:
            return override
        info = self.caps.get({engine_id: self._engines[engine_id]}).get(engine_id) or {}
        return (info.get("slots") or {}).get(slot)

    def close(self) -> None:
        self.runner.close()

    # -- engines and consent -------------------------------------------------------------
    def engines(self, refresh: bool = False) -> dict:
        settings = self.consent_store.settings()
        infos = self.caps.get(self._engines, refresh)
        grants = self.consent_store.grants(self._engines)
        keys = ("id", "name", "available", "version", "logged_in", "flags", "slots", "quota",
                "checked_at")
        return {"mode": settings["mode"], "default_engine": settings["default_engine"],
                "engines": [{**{k: info.get(k) for k in keys}, "id": engine_id,
                             "consent": grants.get(engine_id, {})}
                            for engine_id, info in infos.items()]}

    def consent(self) -> dict:
        return self.consent_store.state(self._engines)

    def set_consent(self, patch: dict) -> dict:
        revoked = self.consent_store.update(patch)
        engines = {engine for engine, _ in revoked}
        if self.consent_store.settings()["mode"] == "stats":
            engines = None  # AI switched off: stop everything.
        cancelled = []
        if engines is None or engines:
            for job_id in self.runner.active():
                row = self._job_row(job_id)
                if row and (engines is None or row["engine"] in engines):
                    self.runner.cancel(job_id)
                    cancelled.append(job_id)
        return {**self.consent(), "cancelled_jobs": cancelled}

    def _pick_engine(self, requested: str | None, task: dict) -> tuple[str | None, str | None]:
        """``(engine_id, None)`` or ``(candidate_or_None, reason)``."""
        settings = self.consent_store.settings()
        infos = self.caps.get(self._engines)

        def reason(engine_id: str) -> str | None:
            info = infos.get(engine_id)
            if info is None or not info.get("available"):
                return "not_installed"
            return "not_logged_in" if info.get("logged_in") is False else None

        chosen = requested or settings["default_engine"]
        if chosen:
            if chosen not in self._engines or chosen not in task["engines"]:
                return chosen, "not_installed"
            return chosen, reason(chosen)
        order = [e for e in PREFERENCE[settings["mode"]] if e in self._engines]
        order += [e for e in self._engines if e not in order]
        for engine_id in order:
            if engine_id in task["engines"] and reason(engine_id) is None:
                return engine_id, None
        return None, "not_installed" if not order else reason(order[0]) or "not_installed"

    # -- packs, preview and jobs ---------------------------------------------------------
    def _task(self, task_id: str) -> dict:
        task = registry.get(task_id)
        if task is None:
            raise AIError(400, "unknown_task", f"未知 AI 任务：{task_id}")
        return task

    def _builder(self):
        """The context-pack builder. pack is part of this package, so an import error (e.g. a
        missing jieba) surfaces instead of silently degrading every task to the goal-only
        ``fallback_pack``; tests that want the minimal pack patch this to return None."""
        from .pack import build

        return build

    def _pack(self, task: dict, req: dict) -> dict:
        build = self._builder()
        if build is None:
            return fallback_pack(task, req)
        reads = getattr(self.gw, "reads", None)
        return build(task, reads=reads.read if reads is not None else None, appdb=self.appdb,
                     home=self.home, scope=req.get("scope"), selection=req.get("selection"),
                     goal=req.get("goal"), goal_source=req.get("goal_source"),
                     params=req.get("params") or {}, slots=req.get("slots"))

    def _estimate(self, task: dict, pack: dict, engine_id: str | None) -> dict:
        calls = len(pack.get("batches") or []) or 1
        tokens = pack.get("total_tokens", 0) + len(task["system"]) // 4
        model = self.model_for(engine_id, task["slot"]) if engine_id in self._engines else None
        cost = prices.estimate(tokens, task["out_budget"] * calls, model)
        return {"tokens": tokens, "cost_usd": cost, "calls": calls}

    def _validate(self, task: dict, req: dict) -> None:
        """Request checks shared by preview and submit (B15): a bad scope or a missing goal is a
        422, not an empty pack that looks like "no data"."""
        from . import queries  # lazy: keeps the pack modules out of gateway start-up

        try:
            queries.check_scope(req.get("scope"))
        except ValueError as error:
            raise AIError(422, "invalid_scope", str(error)) from None
        manual = req.get("goal_source") in (None, "manual")
        if task["task_id"].startswith("generate.") and manual and not str(req.get("goal") or "").strip() \
                and not (req.get("slots") or {}).get("goal"):
            raise AIError(422, "goal_required", "请先写下要解决的问题（goal 不能为空）")

    def preview(self, task_id: str, req: dict) -> dict:
        task = self._task(task_id)
        self._validate(task, req)
        engine_id, _ = self._pick_engine(req.get("engine"), task)
        pack = self._pack(task, req)
        grants = self.consent_store.grants().get(engine_id or "", {})
        items = []
        for item in pack.get("items", []):
            data_class = item.get("data_class", "summary")
            ok = (engine_id is not None and engine_id in
                  ALLOWED.get(data_class, ()) and grants.get(data_class, False))
            items.append({**item, "consent": "granted" if ok else "missing"})
        estimate = self._estimate(task, pack, engine_id)
        return {"task_id": task_id, "engine": engine_id, "items": items,
                "total_tokens": pack.get("total_tokens", 0),
                "input_budget": task["input_budget"],
                "over_budget": pack.get("total_tokens", 0) > task["input_budget"],
                "est_cost_usd": estimate["cost_usd"], "est_calls": estimate["calls"],
                "redaction_hits": pack.get("redaction_hits", 0),
                "preview_digest": pack.get("preview_digest"), "payload": pack.get("content", {}),
                "stages": task["stages"]}

    def _data_identity(self) -> dict:
        """Published revision the job reads (stored with the request, never sent to engines),
        so consumers can tell a narrative written before the latest import (ai/narratives)."""
        revisions = getattr(self.gw, "revisions", None)
        rev = revisions.snapshot() if revisions is not None else {}
        return {"data_rev": rev.get("data_rev"), "inventory_rev": rev.get("inventory_rev")}

    def submit(self, task_id: str, req: dict, *, waiter: bool = False,
               skip_preview: bool = False) -> dict:
        task = self._task(task_id)
        self._validate(task, req)
        settings = self.consent_store.settings()
        if settings["mode"] == "stats":
            raise AIError(403, "ai_disabled", "AI 未开启（设置 → AI 引擎）")
        engine_id, reason = self._pick_engine(req.get("engine"), task)
        if reason is not None or engine_id is None:
            raise AIError(503, "engine_unavailable", "AI 引擎不可用",
                          reason=reason or "not_installed", engine=engine_id)
        pack = self._pack(task, req)
        if task["requires_preview"] and not skip_preview and \
                req.get("preview_digest") != pack.get("preview_digest"):
            raise AIError(409, "preview_stale", "预览已过期，请重新预览后再提交")
        if pack.get("total_tokens", 0) > task["input_budget"] * 1.1:
            raise AIError(413, "over_budget", "上下文超出预算，请取消部分条目",
                          total_tokens=pack.get("total_tokens"),
                          input_budget=task["input_budget"])
        missing = self.consent_store.missing(engine_id, pack)
        if missing:
            raise AIError(403, "consent_required", "需要先授权这些数据类", missing=missing)
        if not req.get("override") and self.today_cost() >= settings["daily_usd_cap"]:
            raise AIError(409, "budget_exhausted", "今日 AI 花费已达上限",
                          daily_cap=settings["daily_usd_cap"])
        job_id = "aj_" + uuid.uuid4().hex[:16]
        slot = (req.get("params") or {}).get("slot") or task["slot"]
        template = req.get("template") or "v1"
        with self.appdb.write() as db:
            db.execute(
                "INSERT INTO ai_job (job_id, task_id, engine, slot, template, goal, goal_source, "
                "request, preview_digest, status, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
                (job_id, task_id, engine_id, slot, template, pack.get("goal", req.get("goal")),
                 pack.get("goal_source", req.get("goal_source")),
                 json.dumps({**req, "_data": self._data_identity()}, ensure_ascii=False,
                            default=str), pack.get("preview_digest"),
                 now_ms()))
        if waiter:
            self.runner.waiters.add(job_id)
        job = {"job_id": job_id, "task": task, "pack": pack, "engine": engine_id,
               "template": template, "params": req.get("params") or {}, "slot": slot,
               "goal": pack.get("goal"), "goal_source": pack.get("goal_source"),
               "preview_digest": pack.get("preview_digest")}
        inline = task["run"] is None and task["cache_ttl_s"] != 0 and self._cached(task, pack)
        self.runner.enqueue(job, inline=inline)
        row = self._job_row(job_id)
        return {"job_id": job_id, "status": row["status"], "cached": bool(row["cached"]),
                "estimate": self._estimate(task, pack, engine_id)}

    def _cached(self, task: dict, pack: dict) -> bool:
        key = cache_key(task["task_id"], task["prompt_version"], task["schema_version"],
                        task["system"], task["build_prompt"](pack))
        with self.appdb.read() as db:
            return db.execute("SELECT 1 FROM ai_cache WHERE input_digest = ? AND (expires_at "
                              "IS NULL OR expires_at > ?)", (key, now_ms())).fetchone() is not None

    def run(self, task_id: str, slots: dict | None = None, scope: dict | None = None,
            engine: str | None = None, timeout: float = 60) -> dict:
        """Synchronous TaskResult for other modules; raises ``AIUnavailable(reason)``."""
        req = {"slots": slots, "scope": scope, "engine": engine}
        try:
            submitted = self.submit(task_id, req, waiter=True, skip_preview=True)
        except AIError as error:
            raise AIUnavailable(error.code) from None
        job_id = submitted["job_id"]
        done = self.runner.done.get(job_id)
        try:
            if done is not None and not done.wait(timeout):
                self.runner.cancel(job_id)
                raise AIUnavailable("timeout")
            with self.runner.lock:
                result = self.runner.results.pop(job_id, None)
        finally:
            with self.runner.lock:
                self.runner.waiters.discard(job_id)
                self.runner.done.pop(job_id, None)
                self.runner.states.pop(job_id, None)
        if result is None:
            row = self._job_row(job_id)
            raise AIUnavailable(row["status"] if row else "failed")
        return {**result, "job_id": job_id}

    def cancel(self, job_id: str) -> dict:
        if self._job_row(job_id) is None:
            raise AIError(404, "not_found", "作业不存在")
        self.runner.cancel(job_id)
        return {"job_id": job_id, "status": self._job_row(job_id)["status"]}

    def _job_row(self, job_id: str):
        with self.appdb.read() as db:
            return db.execute("SELECT * FROM ai_job WHERE job_id = ?", (job_id,)).fetchone()

    def job(self, job_id: str) -> dict:
        row = self._job_row(job_id)
        if row is None:
            raise AIError(404, "not_found", "作业不存在")
        with self.appdb.read() as db:
            usage = db.execute("SELECT COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE("
                               "cache_read_tokens, 0) + COALESCE(cache_write_tokens, 0)), 0), "
                               "COALESCE(SUM(output_tokens), 0), SUM(cost_usd) FROM ai_usage "
                               "WHERE job_id = ?", (job_id,)).fetchone()
        return {**self._job_summary(row), "stages": json.loads(row["stages"]),
                "log": json.loads(row["log"]), "result": _loads(row["result"]),
                "usage": {"input": usage[0], "output": usage[1], "cost_usd": usage[2]}}

    @staticmethod
    def _job_summary(row) -> dict:
        return {"job_id": row["job_id"], "task_id": row["task_id"], "engine": row["engine"],
                "template": row["template"], "goal": row["goal"],
                "goal_source": row["goal_source"], "status": row["status"],
                "stage": row["stage"], "progress": [row["progress_n"], row["progress_total"]],
                "artifact_id": row["artifact_id"], "error": row["error"],
                "cached": bool(row["cached"]), "created_at": row["created_at"],
                "finished_at": row["finished_at"]}

    def jobs(self, limit: int = 50) -> list[dict]:
        with self.appdb.read() as db:
            rows = db.execute("SELECT * FROM ai_job ORDER BY created_at DESC LIMIT ?",
                              (limit,)).fetchall()
        return [self._job_summary(row) for row in rows]

    # -- artifacts, facets, usage --------------------------------------------------------
    def artifacts(self, kind: str | None = None, status: str | None = None,
                  limit: int = 50) -> list[dict]:
        sql, args = "SELECT * FROM ai_artifact WHERE 1 = 1", []
        if kind:
            sql, args = sql + " AND kind = ?", [*args, kind]
        if status:
            sql, args = sql + " AND status = ?", [*args, status]
        with self.appdb.read() as db:
            rows = db.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
        result = []
        for row in rows:
            checks = json.loads(row["checks"]) or {}
            result.append({"artifact_id": row["artifact_id"], "kind": row["kind"],
                           "name": row["name"], "title": row["title"], "status": row["status"],
                           "personalized": bool(row["personalized"]),
                           "created_at": row["created_at"],
                           "checks": {k: (v.get("status") if isinstance(v, dict) else v)
                                      for k, v in checks.items()}})
        return result

    def artifact(self, artifact_id: str) -> dict:
        with self.appdb.read() as db:
            row = db.execute("SELECT * FROM ai_artifact WHERE artifact_id = ?",
                             (artifact_id,)).fetchone()
        if row is None:
            raise AIError(404, "not_found", "产物不存在")
        body = dict(row)
        for key in ARTIFACT_JSON:
            body[key] = json.loads(body[key])
        body["personalized"] = bool(body["personalized"])
        return body

    def set_artifact_status(self, artifact_id: str, status: str | None = None,
                            install_id: str | None = None, name: str | None = None) -> dict:
        self.artifact(artifact_id)
        fields = {k: v for k, v in (("status", status), ("install_id", install_id),
                                    ("name", name)) if v is not None}
        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            with self.appdb.write() as db:
                db.execute(f"UPDATE ai_artifact SET {assignments}, updated_at = ? "
                           "WHERE artifact_id = ?", (*fields.values(), now_ms(), artifact_id))
        return self.artifact(artifact_id)

    def facets(self, session_uids: list[str]) -> list[dict]:
        if not session_uids:
            return []
        marks = ",".join("?" * len(session_uids))
        with self.appdb.read() as db:
            rows = db.execute(f"SELECT session_uid, status, json, model_id, prompt_version FROM "
                              f"ai_facet WHERE session_uid IN ({marks}) ORDER BY created_at DESC",
                              session_uids).fetchall()
        return [{**dict(row), "json": _loads(row["json"])} for row in rows]

    def narrative(self, kind: str, key: str | None = None, params: dict | None = None,
                  scope: dict | None = None) -> dict:
        """Latest kept result of a narrate / cluster / classify task; else its L0 fallback
        computed now (AI off, never run, or no result for ``key``)."""
        from .tasks_v1 import NARRATIVE_KINDS

        task_id = NARRATIVE_KINDS.get(kind)
        if task_id is None:
            raise AIError(400, "unknown_kind", f"未知叙述类型：{kind}",
                          kinds=sorted(NARRATIVE_KINDS))
        task = self._task(task_id)
        with self.appdb.read() as db:
            rows = db.execute("SELECT job_id, status, result, finished_at FROM ai_job WHERE "
                              "task_id = ? AND status IN ('ok', 'fallback') AND result IS NOT NULL "
                              "ORDER BY finished_at DESC LIMIT 50", (task_id,)).fetchall()
        for row in rows:
            result = _loads(row["result"]) or {}
            if key is None or result.get("key") == key:
                return {"kind": kind, "task_id": task_id, "key": result.get("key"),
                        "status": row["status"], "source": result.get("source"),
                        "job_id": row["job_id"], "finished_at": row["finished_at"],
                        "result": result}
        pack = self._pack(task, {"params": params or {}, "scope": scope})
        output = task["fallback"](pack, "no_job") if task["fallback"] else None
        if output is None:
            raise AIError(404, "not_found", "还没有这类 AI 结果")
        done = task["finalize"](output, pack, "fallback") if task["finalize"] else None
        result = (done or {}).get("result", output)
        return {"kind": kind, "task_id": task_id, "key": result.get("key"), "status": "fallback",
                "source": "template", "job_id": None, "finished_at": None, "result": result}

    def today_cost(self) -> float:
        """Today's spend for the daily cap. Calls without a list price (codex, unknown model
        IDs; cost_usd NULL) are counted at ``prices.CONSERVATIVE`` per token instead of $0, so
        an unpriced engine can never bypass the cap."""
        with self.appdb.read() as db:
            known, tokens_in, tokens_out = db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0), "
                "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN COALESCE(input_tokens, 0) + "
                "COALESCE(cache_read_tokens, 0) + COALESCE(cache_write_tokens, 0) END), 0), "
                "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN COALESCE(output_tokens, 0) END), 0) "
                "FROM ai_usage WHERE ts >= ?", (_local_midnight_ms(),)).fetchone()
        return known + prices.conservative(tokens_in, tokens_out)

    def usage(self, days: int = 30) -> dict:
        since = now_ms() - days * 86400 * 1000
        aggregate = ("COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
                     "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                     "ROUND(COALESCE(SUM(cost_usd), 0), 6) AS cost_usd, "
                     # Calls that used tokens but have no price: cost_usd above excludes them,
                     # so the UI must show them as "未计价" rather than read $0 as free.
                     "COALESCE(SUM(cost_usd IS NULL AND COALESCE(input_tokens, 0) + "
                     "COALESCE(output_tokens, 0) > 0), 0) AS unknown_calls")
        with self.appdb.read() as db:
            totals = dict(db.execute(f"SELECT {aggregate} FROM ai_usage WHERE ts >= ?",
                                     (since,)).fetchone())

            def grouped(expr: str, name: str) -> list[dict]:
                return [dict(r) for r in db.execute(
                    f"SELECT {expr} AS {name}, {aggregate} FROM ai_usage WHERE ts >= ? "
                    f"GROUP BY 1 ORDER BY 1", (since,))]

            by_day = grouped("date(ts / 1000, 'unixepoch', 'localtime')", "day")
            by_task = grouped("task_id", "task_id")
            by_engine = grouped("engine", "engine")
            pairs = db.execute("SELECT est_input_tokens, COALESCE(input_tokens, 0) + COALESCE("
                               "cache_read_tokens, 0) + COALESCE(cache_write_tokens, 0) FROM "
                               "ai_usage WHERE ts >= ? AND est_input_tokens > 0", (since,)).fetchall()
        ratios = [abs(est - actual) / actual for est, actual in pairs if actual]
        return {"totals": totals, "by_day": by_day, "by_task": by_task, "by_engine": by_engine,
                "estimate_error": {"median_abs_ratio": round(statistics.median(ratios), 4)
                                   if ratios else None, "n": len(ratios)},
                "today_cost_usd": round(self.today_cost(), 6),
                "daily_cap": self.consent_store.settings()["daily_usd_cap"]}


def service(gw) -> AIService:
    """Lazy per-gateway singleton (stored on ``gw._ai``)."""
    existing = getattr(gw, "_ai", None)
    if existing is not None:
        return existing
    with _lock:
        existing = getattr(gw, "_ai", None)
        if existing is None:
            existing = AIService(gw)
            gw._ai = existing
    return existing


__all__ = ["AIService", "AIUnavailable", "fallback_pack", "pack_digest", "service"]
