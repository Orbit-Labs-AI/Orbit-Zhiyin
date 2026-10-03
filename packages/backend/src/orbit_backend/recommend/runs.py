"""Recommendation runs: reuse by inputs digest, else build a slate and persist it.

``inputs_digest`` covers scope, data/inventory revisions, rules, engine and KB versions,
catalog generation and the memory revision (labels/exposures). An unchanged digest is a
single indexed lookup; a changed memory only reruns the engine on the cached RecInputs.
The engine (``.engine.build_slate``) is optional: without it the legacy analysis cards are
mapped into the same candidate shape.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
import uuid
from pathlib import Path

from . import inputs as rec_inputs
from . import outcomes, store

LEGACY_ENGINE = "legacy-v1"
KEEP_RUNS = 20
KEEP_PASSED = 30
KEEP_GATED = 50
RERANK_TOP = 10
RERANK_TIMEOUT_S = 30
DEFAULT_SETTINGS = {"ai_generate": False, "level": None}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

# Cards per surface (route default ``limit``); A7 lists, the others show a top slice.
SURFACE_LIMIT = {"A7": 30, "A1": 3, "lite": 3, "menubar": 1, "widget": 1, "palette": 10,
                 "ask": 5, "hud": 1}

KIND_MAP = {"prompt": "prompt", "skill": "skill", "hook": "hook", "plugin": "plugin",
            "mcp": "mcp", "model_config": "model", "workflow": "workflow", "agent": "subagent",
            "subagent": "subagent", "rule": "rule", "permission_rule": "permission_rule"}
DIM_MAP = {"rule": "rule", "prompt": "rule", "skill": "skill", "hook": "hook",
           "permission_rule": "hook", "builtin": "hook", "mcp": "mcp", "plugin": "mcp",
           "subagent": "agent", "model": "model", "workflow": "flow", "removal": "flow",
           "generate": "skill"}
UI_TYPE = {"rule": "规则", "prompt": "Prompt", "skill": "Skill", "hook": "Hook",
           "permission_rule": "Hook", "mcp": "MCP", "plugin": "插件", "subagent": "子代理",
           "model": "模型与思考", "workflow": "工作流", "removal": "移除", "builtin": "内置功能",
           "generate": "生成"}
ICON = {"rule": "rule", "skill": "book", "hook": "bolt", "mcp": "puzzle", "agent": "bot",
        "model": "gauge", "flow": "branch"}


def now_ms() -> int:
    return int(time.time() * 1000)


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _engine():
    try:
        from . import engine  # type: ignore[attr-defined]
    except ImportError:
        return legacy_slate, LEGACY_ENGINE
    build = getattr(engine, "build_slate", None)
    if build is None:
        return legacy_slate, LEGACY_ENGINE
    return build, getattr(engine, "ENGINE_VERSION", "rec-engine-v2")


def _record(ms: float, **tags) -> None:
    try:
        from ..platform import record
    except ImportError:
        return
    record("recommend.run", ms, **tags)


def _catalog_state(catalog) -> tuple[int | None, int]:
    """(generation, active items) of a CatalogService; (None, 0) when unreadable."""
    try:
        with catalog.store.connect(True) as conn:
            generation = conn.execute(
                "SELECT value FROM catalog_meta WHERE key='generation'").fetchone()
            items = conn.execute("SELECT count(*) FROM catalog_item WHERE status='active'"
                                 ).fetchone()[0]
    except Exception:  # noqa: BLE001 - catalog is optional
        return None, 0
    return (int(generation[0]) if generation else None), int(items)


def _embedding_generation(catalog) -> int:
    try:
        with catalog.store.connect(True) as conn:
            row = conn.execute("SELECT value FROM catalog_meta WHERE key='embedding_generation'").fetchone()
        return int(row[0]) if row else 0
    except Exception:  # An older/optional catalog has no independent vector revision.
        return 0


def catalog_service(gw):
    """The gateway's CatalogService over ``home/catalog.db`` (created lazily, cached on gw).
    None while the file is missing, so recall falls back to the bundled seeds."""
    explicit = getattr(gw, "catalog", None)
    if explicit is not None:
        return explicit
    home = getattr(gw, "home", None)
    path = Path(home) / "catalog.db" if home is not None else None
    if path is None or not path.exists():
        return None
    with _locks_guard:
        svc = getattr(gw, "_rec_catalog", None)
        if svc is None:
            try:
                from orbit_catalog.service import CatalogService

                svc = CatalogService(path)
            except Exception:  # noqa: BLE001 - a broken catalog must not break recommendations
                return None
            gw._rec_catalog = svc
    return svc


def settings_for(gw) -> dict:
    """Recommendation settings: ``platform_kv['recommend']`` (``gw.rec_settings`` overrides)."""
    platform = getattr(gw, "platform", None)
    stored = platform.settings.get("recommend", {}) if platform is not None else {}
    return {**DEFAULT_SETTINGS, **(stored or {}), **(getattr(gw, "rec_settings", None) or {})}


def ai_enabled(gw) -> bool:
    """AI consent leaves model calls on (mode != stats)."""
    try:
        from ..ai.consent import Consent

        return Consent(gw.appdb).settings()["mode"] != "stats"
    except Exception:  # noqa: BLE001 - no AI module / app.db tables: generation stays off
        return False


def _features():
    """Module-level features API once routes_features bound a FeatureService, else None."""
    try:
        from .. import features
    except ImportError:
        return None
    return features if getattr(features, "_service", None) is not None else None


def _accepts_features(build) -> bool:
    try:
        params = inspect.signature(build).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "features" or p.kind is p.VAR_KEYWORD for p in params)


def ai_rerank(gw, slate: dict, scope: dict) -> None:
    """rerank.fit (AI-12): sets ``display_rank`` / ``ai_fit`` on ranked cards; never touches
    priority or rank. Silently skipped when AI is unavailable."""
    from ..ai import AIUnavailable, service

    ranked = sorted((c for c in slate.get("candidates") or [] if c.get("rank")),
                    key=lambda c: c["rank"])[:RERANK_TOP]
    if len(ranked) < 2:
        return
    problems = [{k: p.get(k) for k in ("problem_id", "type", "key", "sessions", "weekly_count")}
                for p in slate.get("problems") or [] if p.get("status") == "active"]
    slots = {"candidates": [{"candidate_id": c["rec_key"], "title": c.get("title"),
                             "kind": c.get("kind"),
                             "problem": (c.get("problem") or {}).get("key"),
                             "reason": ((c.get("explain") or {}).get("reason") or "")[:120]}
                            for c in ranked],
             "friction": {"problems": problems}}
    try:
        result = service(gw).run("rerank.fit", slots=slots, scope=scope, timeout=RERANK_TIMEOUT_S)
    except AIUnavailable as error:
        slate["diagnostics"].append({"source": "rerank.fit", "status": "unavailable",
                                     "reason": str(error)})
        return
    except Exception as error:  # Optional enrichment cannot fail the whole recommendation run.
        slate.setdefault("diagnostics", []).append({"source": "rerank.fit", "status": "failed",
                                                     "reason": type(error).__name__})
        return
    body = result.get("result") if isinstance(result, dict) else None
    if not isinstance(body, dict):
        slate.setdefault("diagnostics", []).append({"source": "rerank.fit", "status": "failed",
                                                     "reason": "invalid_result"})
        return
    ids = {c["rec_key"] for c in ranked}
    order = list(dict.fromkeys(key for key in body.get("order") or [] if isinstance(key, str) and key in ids))
    order += [c["rec_key"] for c in ranked if c["rec_key"] not in order]
    fits = {i.get("candidate_id"): i for i in body.get("items") or []
            if isinstance(i, dict) and isinstance(i.get("candidate_id"), str) and i["candidate_id"] in ids}
    position = {key: i for i, key in enumerate(order, 1)}
    for cand in ranked:
        cand["display_rank"] = position.get(cand["rec_key"], len(order) + cand["rank"])
        item = fits.get(cand["rec_key"])
        if item:
            cand["ai_fit"] = {"fit": item.get("fit"), "explain": item.get("explain"),
                              "reasons": item.get("reasons") or [], "job_id": result.get("job_id")}


def _mark_generate(slate: dict, enabled: bool) -> None:
    """Generation cards carry the AI task id the workshop runs (generate.rule/hook/skill)."""
    try:
        from ..ai import registry
    except ImportError:
        registry = None
    for cand in slate.get("candidates") or []:
        gen = cand.get("generate")
        if gen and gen.get("task_id"):
            known = registry is not None and registry.get(gen["task_id"]) is not None
            gen["available"] = bool(enabled and known)


def inputs_digest(inputs: dict, engine_version: str, kb_version, catalog_generation,
                  memory_rev: str, embedding_generation: int = 0) -> str:
    from ..services.sections import rules_digest

    payload = [inputs["scope_hash"], inputs["data_rev"], inputs["inventory_rev"],
               rules_digest(), engine_version, kb_version, catalog_generation, memory_rev, embedding_generation]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()
                          ).hexdigest()[:32]


def run(gw, scope_dict: dict, *, force: bool = False, wait_ms: int = 0,
        settings: dict | None = None) -> dict:
    data, freshness, job_id = rec_inputs.fetch(gw, scope_dict, wait_ms=wait_ms)
    if data is None:
        return {"run_id": None, "status": freshness, "reused": False, "freshness": freshness,
                "job_id": job_id}
    h = data["scope_hash"]
    started = time.perf_counter()
    with _lock(h):
        now = now_ms()
        settings = dict(settings or settings_for(gw))
        settings["ai_generate"] = bool(settings.get("ai_generate")) and ai_enabled(gw)
        with gw.appdb.read() as conn:
            memory = store.memory(conn, now, settings)
            memory_rev = store.memory_rev(conn)
            previous = store.latest_run(conn, h)
        build, engine_version = _engine()
        catalog = catalog_service(gw)
        generation, items = _catalog_state(catalog) if catalog is not None else (None, 0)
        if not items:
            # Empty catalog (fresh install, before the first sync): the bundled seeds recall
            # better than nothing, and the slate reports no generation — so neither may the
            # digest, or every GET rebuilds the run and invalidates candidate ids.
            catalog, generation = None, None
        embedding_generation = _embedding_generation(catalog) if catalog is not None else 0
        same = previous is not None and previous["engine_version"] == engine_version
        kb_version = previous["kb_version"] if same else None
        if generation is None and same:
            generation = previous["catalog_generation"]
        # AI on/off changes the slate (generation cards, display order), so it keys the run.
        settings_key = hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode()).hexdigest()[:16]
        memory_rev = f"{memory_rev}:settings:{settings_key}"
        digest = inputs_digest(data, engine_version, kb_version, generation, memory_rev, embedding_generation)
        if not force:
            with gw.appdb.read() as conn:
                found = store.find_run(conn, h, digest)
            if found is not None:
                _record((time.perf_counter() - started) * 1000, outcome="reused")
                return {"run_id": found["run_id"], "status": found["status"], "reused": True,
                        "freshness": freshness, "job_id": job_id}
        features = _features() if _accepts_features(build) else None
        extra = {"features": features} if features is not None else {}
        try:
            slate = build(data, memory, catalog=catalog, **extra)
        except Exception as error:  # noqa: BLE001 - keep serving legacy cards
            if build is legacy_slate:
                raise
            slate = legacy_slate(data, memory)
            slate["diagnostics"].append({"source": "engine", "status": "failed",
                                         "reason": f"{type(error).__name__}: {error}"})
        if memory["settings"]["ai_generate"]:
            from .expert import enrich
            try:
                enrich(gw, slate, data, memory, catalog, scope_dict)
            except Exception as error:
                slate.setdefault("diagnostics", []).append({"source": "recommend.expert", "status": "failed",
                                                             "reason": type(error).__name__})
            ai_rerank(gw, slate, scope_dict)
        _mark_generate(slate, memory["settings"]["ai_generate"])
        duration = int((time.perf_counter() - started) * 1000)
        # Only versions the slate actually reports override the lookup ones, so the stored
        # digest equals the one the next call computes from ``previous``.
        if slate.get("kb_version") is not None:
            kb_version = slate["kb_version"]
        # The catalog generation the lookup read from catalog_meta is authoritative: the
        # slate's comes from whichever catalog.match answered (absent when none ran, or a
        # lagging index snapshot), and storing that made every GET rebuild the run.
        if generation is None and slate.get("catalog_generation") is not None:
            generation = slate["catalog_generation"]
        # Digest with the versions the slate actually used, so the next call reuses it.
        digest = inputs_digest(data, engine_version, kb_version, generation, memory_rev, embedding_generation)
        run_id = uuid.uuid4().hex[:16]
        cands = slate.get("candidates") or []
        passed = [c for c in cands if (c.get("gates") or {}).get("passed", True)][:KEEP_PASSED]
        gated = [c for c in cands if not (c.get("gates") or {}).get("passed", True)][:KEEP_GATED]
        row = {"run_id": run_id, "scope_hash": h, "scope": scope_dict, "inputs_digest": digest,
               "data_rev": str(data.get("data_rev")), "inventory_rev": data.get("inventory_rev"),
               "engine_version": slate.get("engine_version", engine_version),
               "kb_version": kb_version, "catalog_generation": generation,
               "memory_rev": memory_rev, "status": slate.get("status", "ready"),
               "problems": slate.get("problems") or [], "routes": slate.get("routes") or {},
               "diagnostics": (slate.get("diagnostics") or []) + (data.get("diagnostics") or []),
               "created_at": now, "duration_ms": duration}
        with gw.appdb.write() as conn:
            store.insert_run(conn, row, passed + gated)
            store.prune(conn, h, KEEP_RUNS)
            outcomes.refresh(conn, data, now)
    _record(duration, outcome="built", status=row["status"])
    return {"run_id": run_id, "status": row["status"], "reused": False, "freshness": freshness,
            "job_id": job_id}


# -- legacy fallback ----------------------------------------------------------------------

def legacy_slate(inputs: dict, memory: dict | None = None, *, catalog=None) -> dict:
    """Map the analysis' legacy cards into Cand shape (used when the engine is missing)."""
    cands = []
    for rank, card in enumerate(inputs.get("legacy_cards") or [], start=1):
        resource_id = card.get("resource_id")
        if not resource_id:
            continue
        kind = KIND_MAP.get(card.get("kind"), "rule")
        dim = DIM_MAP.get(kind, "rule")
        uids = list(dict.fromkeys(e.get("session_uid") for e in card.get("evidence") or []
                                  if e.get("session_uid")))[:50]
        compat = card.get("compatibility") or "unknown"
        reason = card.get("reason") or ""
        steps = list(card.get("setup_steps") or [])
        cands.append({
            "rec_key": f"legacy:{resource_id}", "problem": None, "kind": kind, "dim": dim,
            "level": 2, "audience_min": 0, "title": card.get("name") or resource_id,
            "summary": card.get("summary") or "", "match_basis": card.get("match_basis"),
            "routes": {"legacy": {"rank": rank, "raw": card.get("priority_score")}},
            "fusion": 0.0,
            "gates": {"passed": True, "checks": {}, "reasons": []},
            "score": {"benefit": None, "confidence": None, "p_effective": None, "fit": None,
                      "cost": None, "risk": None, "personal": 1.0, "decay": 1.0,
                      "priority": float(card.get("priority_score") or 0)},
            "rank": rank,
            "evidence": {"session_uids": uids, "signal_ids": [card["signal_id"]]
                         if card.get("signal_id") else [],
                         "counts": {"sessions": len(uids),
                                    "events": len(card.get("evidence") or [])}},
            "explain": {"reason": reason, "mechanism": card.get("capability") or "",
                        "capability": card.get("capability") or "", "trial": card.get("trial"),
                        "limitation": card.get("limitations"), "source": "template"},
            "trial": {"steps": steps, "metric": None, "follow_days": 7},
            "track": {"triggered": None, "mechanical": None, "guardrail": None,
                      "follow_days": 7, "extend_days": 28},
            "target": {"agents": [card["target_agent"]] if card.get("target_agent") else [],
                       "scope": "user", "project_id": None, "path_hint": None},
            "source": {"origin": "legacy", "item_id": resource_id, "url": card.get("url"),
                       "license": None, "version": card.get("verified_sha")},
            "alternatives": [], "generate": None,
            "ui": {"dim": dim, "type": UI_TYPE.get(kind, kind), "icon": ICON.get(dim, "rule"),
                   "lvl": 2, "aud": 0, "title": card.get("name") or resource_id, "gain": "",
                   "why": reason, "ev": f"{len(uids)} 个会话", "evq": {"session_uids": uids},
                   "compat": compat, "primary": "预览并安装", "target": "", "file": [],
                   "steps": steps, "track": []},
        })
    status = "ready" if cands else ("insufficient_evidence" if not inputs.get("signals")
                                    else "no_matching")
    return {"engine_version": LEGACY_ENGINE, "kb_version": None, "catalog_generation": None,
            "status": status, "problems": [], "candidates": cands,
            "routes": {"legacy": len(cands)},
            "diagnostics": [{"source": "engine", "status": "missing",
                             "reason": "recommend.engine not installed; legacy cards"}]}
