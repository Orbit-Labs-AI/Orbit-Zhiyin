"""Recommendation runs: reuse by inputs digest, else build a slate and persist it.

``inputs_digest`` covers scope, data/inventory revisions, rules, engine and KB versions,
catalog generation and the memory revision (labels/exposures). An unchanged digest is a
single indexed lookup; a changed memory only reruns the engine on the cached RecInputs.
The engine (``.engine.build_slate``) is optional: without it the legacy analysis cards are
mapped into the same candidate shape.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time
import uuid

from . import inputs as rec_inputs
from . import outcomes, store

LEGACY_ENGINE = "legacy-v1"
KEEP_RUNS = 20
KEEP_PASSED = 30
KEEP_GATED = 50
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

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


def _timed(name: str):
    try:
        from ..platform import timed  # type: ignore[attr-defined]
    except ImportError:
        return contextlib.nullcontext()
    return timed(name)


def _catalog_generation(catalog):
    value = getattr(catalog, "generation", None)
    try:
        value = value() if callable(value) else value
    except Exception:  # noqa: BLE001 - catalog is optional
        return None
    return value if isinstance(value, int) else None


def inputs_digest(inputs: dict, engine_version: str, kb_version, catalog_generation,
                  memory_rev: str) -> str:
    from ..services.sections import rules_digest

    payload = [inputs["scope_hash"], inputs["data_rev"], inputs["inventory_rev"],
               rules_digest(), engine_version, kb_version, catalog_generation, memory_rev]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()
                          ).hexdigest()[:32]


def run(gw, scope_dict: dict, *, force: bool = False, wait_ms: int = 0,
        settings: dict | None = None) -> dict:
    data, freshness, job_id = rec_inputs.fetch(gw, scope_dict, wait_ms=wait_ms)
    if data is None:
        return {"run_id": None, "status": freshness, "reused": False, "freshness": freshness,
                "job_id": job_id}
    h = data["scope_hash"]
    with _lock(h):
        now = now_ms()
        with gw.appdb.read() as conn:
            memory = store.memory(conn, now, settings or getattr(gw, "rec_settings", None))
            memory_rev = store.memory_rev(conn)
            previous = store.latest_run(conn, h)
        build, engine_version = _engine()
        catalog = getattr(gw, "catalog", None)
        same = previous is not None and previous["engine_version"] == engine_version
        kb_version = previous["kb_version"] if same else None
        generation = _catalog_generation(catalog)
        if generation is None and same:
            generation = previous["catalog_generation"]
        digest = inputs_digest(data, engine_version, kb_version, generation, memory_rev)
        if not force:
            with gw.appdb.read() as conn:
                found = store.find_run(conn, h, digest)
            if found is not None:
                return {"run_id": found["run_id"], "status": found["status"], "reused": True,
                        "freshness": freshness, "job_id": job_id}
        started = time.perf_counter()
        with _timed("recommend.run"):
            try:
                slate = build(data, memory, catalog=catalog)
            except Exception as error:  # noqa: BLE001 - keep serving legacy cards
                if build is legacy_slate:
                    raise
                slate = legacy_slate(data, memory)
                slate["diagnostics"].append({"source": "engine", "status": "failed",
                                             "reason": f"{type(error).__name__}: {error}"})
        duration = int((time.perf_counter() - started) * 1000)
        kb_version = slate.get("kb_version", kb_version)
        generation = slate.get("catalog_generation", generation)
        # Digest with the versions the slate actually used, so the next call reuses it.
        digest = inputs_digest(data, engine_version, kb_version, generation, memory_rev)
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
