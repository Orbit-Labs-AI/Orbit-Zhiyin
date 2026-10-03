"""``GET /v1/shell/onboarding``: first-run source estimates and the four-stage progress
(OB-03 来源与估计, OB-05/OB-06 进度与揭晓入口).

Sources are enumerated exactly like ``/v1/app/discovery`` (file names and ``stat`` only,
never file bodies). ``est_sessions`` counts top-level transcript files and is an estimate.
Starting the analysis stays on ``POST /v1/app/sources`` + ``POST /v1/app/jobs``.
"""

from __future__ import annotations

import math
from pathlib import Path

from . import cached_section, default_scope, has_db, main_where, now_ms, reader

FACET_BATCH = 8  # ai/tasks_analysis batches eight sessions per facet call.
ACTIVE = ("queued", "running")
STAGES = (("backfill", "导入历史会话"), ("stats", "统计分析"), ("semantic", "语义分析"),
          ("persona", "协作画像"))


def scan(agent: str, root: str) -> dict:
    """Count transcripts under one root (names and mtimes only)."""
    from orbit_data.discovery import inputs

    files = transcripts = 0
    earliest = latest = None
    try:
        for item in inputs(agent, Path(root)):
            if item.role not in ("transcript", "subagent_transcript"):
                continue
            files += 1
            if item.role != "transcript":
                continue
            transcripts += 1
            try:
                mtime = int(item.path.stat().st_mtime * 1000)
            except OSError:
                continue
            earliest = mtime if earliest is None else min(earliest, mtime)
            latest = mtime if latest is None else max(latest, mtime)
    except (OSError, ValueError):
        return {"files": None, "est_sessions": None, "earliest_mtime": None,
                "latest_mtime": None, "status": "permission_denied"}
    return {"files": files, "est_sessions": transcripts, "earliest_mtime": earliest,
            "latest_mtime": latest, "status": "available" if files else "empty"}


def sources(gw) -> list[dict]:
    from orbit_data.contract import uid

    configured = gw.state.snapshot()["sources"]
    roots = {(s["agent"], s["root"]) for s in [*gw.discovery(), *configured.values()]}
    out = []
    for agent, root in sorted(roots):
        key = uid("source", agent, root)
        out.append({"id": key, "agent": agent, "root": root, **scan(agent, root),
                    "enabled": configured.get(key, {}).get("enabled", False),
                    "estimate": True})
    return out


def _import_job(gw) -> dict | None:
    return next((j for j in gw.state.jobs() if j.get("kind") == "import"), None)


def _stage_note(progress: dict) -> str | None:
    """「解析会话记录 · Codex · 第 1/2 个来源 …」: the stage name and the worker's detail."""
    from orbit_data.progress import STAGES

    stage = progress.get("stage")
    if not stage:
        return None
    label = progress.get("label") or STAGES.get(stage, (stage,))[0]
    return f"{label} · {progress['detail']}" if progress.get("detail") else label


def _backfill(job: dict | None) -> dict:
    stage = {"id": "backfill", "label": STAGES[0][1], "status": "pending", "done": None,
             "total": None, "unit": None, "note": None}
    if job is None:
        return stage
    progress = job.get("progress") or {}
    status = job.get("status")
    stage.update(done=progress.get("completed"), total=progress.get("total"),
                 unit=progress.get("unit"), note=_stage_note(progress)
                 or job.get("current_phase") or job.get("phase"))
    if status in ACTIVE:
        stage["status"] = "running"
    elif status in ("completed", "partial"):
        stage["status"] = "done"
        if stage["total"] is not None:
            stage["done"] = stage["total"]
    else:
        stage["status"] = "error"
        stage["note"] = ((job.get("error") or {}).get("code")) or status
    return stage


def _main_sessions(gw, start: int | None) -> int:
    if not has_db(gw):
        return 0
    where, args = main_where(gw)
    if start is not None:
        where += " AND s.started_at >= ?"
        args.append(start)
    try:
        with reader(gw)() as db:
            return db.execute(f"SELECT COUNT(*) FROM session s WHERE {where}", args).fetchone()[0]
    except Exception:  # noqa: BLE001 - a pending projection counts as nothing yet.
        return 0


def _facets_done(gw) -> int:
    try:
        with gw.appdb.read() as db:
            return db.execute("SELECT COUNT(DISTINCT session_uid) FROM ai_facet "
                              "WHERE status = 'ok'").fetchone()[0]
    except Exception:  # noqa: BLE001 - ai_facet not created yet.
        return 0


def _consent_mode(gw) -> str:
    from ..ai.consent import Consent

    try:
        return Consent(gw.appdb).settings()["mode"]
    except Exception:  # noqa: BLE001
        return "stats"


def _lite_recs(gw, sessions: int) -> dict | None:
    from dataclasses import asdict

    from ..recommend import store
    from ..services.routes_analytics import analytics_scope
    from ..services.snapshots import scope_hash

    h = scope_hash(asdict(analytics_scope()), {})
    try:
        with gw.appdb.read() as conn:
            top = store.top_get(conn, "lite", h)
            if top:
                count = len(top["rec_keys"])
            else:
                run = store.latest_run(conn, h)
                if run is None:
                    return None
                count = len(store.candidates(conn, run["run_id"], limit=3))
    except Exception:  # noqa: BLE001 - no recommend tables yet.
        return None
    return {"count": count, "starter": sessions < 10}


def build(gw) -> dict:
    from .reveal import persona_summary

    settings = gw.state.snapshot()["settings"]
    found = sources(gw)
    job = _import_job(gw)
    stages = [_backfill(job)]
    backfill_done = stages[0]["status"] == "done" or gw.revisions.snapshot()["data_rev"] \
        is not None

    days = settings.get("default_range_days") or 30
    scope = default_scope(gw, days)
    fresh = [cached_section(gw, name, scope)[1] for name in ("overview", "tools")]
    ready = sum(f in ("fresh", "stale") for f in fresh)
    stages.append({"id": "stats", "label": STAGES[1][1],
                   "status": "done" if ready == 2 else "running" if backfill_done else "pending",
                   "done": ready, "total": 2,
                   "note": "部分数字来自上一版数据" if "stale" in fresh else None})

    mode = _consent_mode(gw)
    recent = settings.get("recent_days") or 90
    total = _main_sessions(gw, now_ms() - int(recent) * 86_400_000)
    facets = min(_facets_done(gw), total)
    remaining = max(0, total - facets)
    calls = math.ceil(remaining / FACET_BATCH)
    semantic = {"enabled": mode != "stats", "mode": mode, "est_calls": calls,
                "note": (f"仅统计模式：不调用模型；开启后约 {calls} 次调用" if mode == "stats"
                         else f"约 {calls} 次模型调用（每次 {FACET_BATCH} 个会话）")}
    stages.append({"id": "semantic", "label": STAGES[2][1],
                   "status": "skipped" if mode == "stats" else "done"
                   if total and not remaining else "pending",
                   "done": facets, "total": total, "note": semantic["note"]})

    persona = persona_summary(gw, scope) if has_db(gw) else None
    if persona is None or persona["reason"] == "persona_unavailable":
        p_status = "skipped" if persona else "pending"
    elif persona["reason"] == "computing":
        p_status = "running" if backfill_done else "pending"
    else:
        p_status = "done"
    stages.append({"id": "persona", "label": STAGES[3][1], "status": p_status,
                   "done": None, "total": None,
                   "note": None if persona is None else persona["reason"]})

    active = job is not None and job.get("status") in ACTIVE
    state = "importing" if active else "ready" if (settings.get("onboarded") or backfill_done) \
        else "onboarding"
    return {
        "state": state,
        "settings": {"onboarded": bool(settings.get("onboarded")),
                     "onboarding_step": settings.get("onboarding_step"),
                     "recent_days": settings.get("recent_days")},
        "sources": found,
        "totals": {"files": sum(s["files"] or 0 for s in found),
                   "est_sessions": sum(s["est_sessions"] or 0 for s in found)},
        "progress": {"job_id": job.get("id") if job else None,
                     "status": job.get("status") if job else "idle", "stages": stages},
        "semantic": semantic, "persona": persona,
        "recs": _lite_recs(gw, _main_sessions(gw, None)) if has_db(gw) else None,
    }
