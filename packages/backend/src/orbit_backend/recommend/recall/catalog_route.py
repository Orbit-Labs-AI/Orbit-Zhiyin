"""Route ②: catalog items whose curated features address an active problem.

The catalog does its own BM25 / feature / remedy / E5 fusion; we only keep
items with problem evidence (a friction feature or the remedy route), plus a
profile query gated on enough evidence sessions. Queries run in parallel with
a per-call timeout so a slow catalog never stalls the engine. Without a
catalog service we fall back to a small BM25 over the bundled legacy seeds.
"""

import json
import math
import re
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from functools import lru_cache

from ..narrate import TRIAL_FALLBACK, TYPE_LABEL, TYPE_ZH, audience_default
from .kb_route import evidence_of, project_of, target_agents
from .sparse import tokenize

# catalog_item.verification values meaning "repository and resource source were read"
# (same set as orbit_catalog.index.VERIFIED; anything else, or a missing field, is unverified).
VERIFIED = ("repository_and_skill_read", "repository_and_source_read")
SUPPORT_VALUES = {"native", "manual", "adaptation_required", "unsupported"}

TYPE_KIND = {"skill": "skill", "plugin": "plugin", "marketplace": "plugin", "mcp_server": "mcp", "hook": "hook",
             "subagent": "subagent", "command": "prompt", "rule": "rule", "workflow": "workflow", "guide": "workflow",
             "output_style": "prompt", "lsp_server": "plugin", "model": "model"}
FAMILY_KIND = {"skills": "skill", "hooks": "hook", "rules_prompts": "prompt", "workflows": "workflow",
               "mcp": "mcp", "plugins": "plugin", "model_configs": "model"}
LEGACY_KIND = {"skill": "skill", "hook": "hook", "prompt": "prompt", "agent": "subagent"}
KIND_DIM = {"rule": "rule", "prompt": "rule", "permission_rule": "hook", "skill": "skill", "hook": "hook",
            "mcp": "mcp", "plugin": "mcp", "subagent": "agent", "model": "model", "workflow": "flow",
            "builtin": "hook", "removal": "rule", "generate": "skill"}
PER_PROBLEM, TIMEOUT_S, MIN_PROFILE_EVIDENCE = 8, 2., 3
MAX_TRIAL = 60
# Evaluation protocol wording (A/B comparisons, statistics) is not a user's trial method.
EVAL_TRIAL = re.compile(r"对照|对比.*前后|统计")
NOT_INSTALLABLE = ("不是可直接安装", "不能直接")


def _user_trial(text: str | None) -> str:
    text = (text or "").strip()
    return text if text and len(text) <= MAX_TRIAL and not EVAL_TRIAL.search(text) else TRIAL_FALLBACK


def from_item(item: dict, problem: dict | None, inputs: dict, *, match_basis: str) -> dict:
    """RawCand from a normalised catalog item dict (catalog response row or legacy seed)."""
    kind = item["kind"]
    # Only an explicit support matrix states native/manual: legacy seeds, or a catalog item's declared
    # metadata.agent_support (Orbit KB entries). A catalog row's ``agents`` list is often inferred by
    # the connector, so it stays a hint and undeclared agents are "unknown" (agent_supported →
    # needs_context).
    support = dict(item.get("support") or {})
    risk_flags = list(item.get("risk") or ())
    limitation = item.get("limitation") or ""
    level = 4 if any(word in limitation for word in NOT_INSTALLABLE) else min(4, max(1, int(item.get("difficulty") or 2)))
    label = TYPE_LABEL.get(kind, kind)
    tags = "、".join(list(item.get("tags") or ())[:3])
    if problem:
        mechanism = f"资源库条目：用{label}应对「{TYPE_ZH.get(problem['type'], problem['type'])}」"
        reason = problem.get("reason") or ""
    else:  # Chinese copy for a profile match; the item's own (often English) text stays in capability
        mechanism = (f"按你的使用画像（{tags}）从资源库匹配的{label}，没有对应的会话问题证据" if tags
                     else f"从资源库匹配的{label}，没有对应的会话问题证据")
        reason = f"资源库里与你常用的 {tags} 相关的{label}" if tags else f"资源库里可能适合你的{label}"
    limitation = "；".join(x for x in (limitation, "来自公开资源库，效果未用你的数据验证；安装前请先看来源说明")
                          if x)
    steps = list(item.get("steps") or ()) or ["打开来源，查看说明与许可", "确认适用后按来源说明安装",
                                              "7 天后看效果追踪"]
    return {
        "rec_key": "catalog:" + item["item_id"], "problem": problem, "kind": kind, "dim": KIND_DIM.get(kind, "skill"),
        "level": level, "audience_min": audience_default(kind, level),
        "title": item["name"], "summary": item.get("summary") or "", "match_basis": match_basis,
        "routes": {}, "fusion": 0., "evidence": evidence_of(problem),
        "source": {"origin": "catalog", "item_id": item["item_id"], "url": item.get("url"),
                   "license": item.get("license"), "version": item.get("version_id"),
                   "verified": bool(item.get("verified")), "quality": item.get("quality")},
        "target": {"agents": target_agents(support, inputs), "scope": "project" if project_of(problem) else "user",
                   "project_id": project_of(problem), "path_hint": None,
                   "agents_listed": list(item.get("agents") or ())},
        "track": {"triggered": (problem or {}).get("type") or "使用次数", "mechanical": "调用次数",
                  "guardrail": "会话摩擦率", "follow_days": 7, "extend_days": 28},
        "trial": {"steps": steps, "metric": (problem or {}).get("type") or "使用次数",
                  "follow_days": 7},
        "alternatives": [], "generate": None, "kb": None, "item": item, "agents": support,
        "prior": {"alpha": 2., "beta": 2.},
        "cost": {"setup_minutes": 5., "context_tokens": 500 if kind in ("skill", "mcp", "plugin") else 100,
                 "reversible": True},
        "risk": {"level": ("high" if (item.get("risk_level") or 0) >= 3 else "medium"
                           if (item.get("risk_level") or 0) >= 2 or len(risk_flags) > 1 else "low"), "flags": risk_flags},
        "requirements": {"tools": [], "software": []}, "gates_hint": {"scenes": None, "language": None},
        "unit_minutes": None, "tags": list(item.get("tags") or ()), "file": None,
        "explain_hints": {"reason_template": reason, "mechanism": mechanism,
                          "trial": _user_trial(item.get("trial")), "limitation": limitation,
                          "vars": dict((problem or {}).get("vars") or {})},
    }


def _normalise_catalog(row: dict) -> dict | None:
    kind = TYPE_KIND.get(row.get("type"))
    if not kind or not row.get("item_id"):
        return None
    tags = sorted({f["value"] for f in row.get("matched_features") or () if f.get("feature") != "friction"})
    return {"item_id": row["item_id"], "kind": kind, "name": row.get("name") or row["item_id"],
            "summary": row.get("summary") or "", "url": row.get("url"), "agents": row.get("agents") or [],
            "license": row.get("license"), "difficulty": row.get("difficulty"), "risk": row.get("risk") or [],
            "language": row.get("language"), "content_hash": row.get("content_hash"),
            "version_id": row.get("version_id"),
            # a search row may not carry verification / declared support: None = look it up in catalog_item
            "verified": row["verification"] in VERIFIED if "verification" in row else None,
            "support": declared_support(row.get("agent_support") or row.get("support")),
            "quality": row.get("quality"), "risk_level": row.get("risk_level"),
            "tags": tags, "score": row.get("score", 0.)}


def declared_support(value) -> dict:
    """A catalog item's declared per-agent support (metadata.agent_support), valid levels only."""
    if not isinstance(value, dict):
        return {}
    return {str(agent): level for agent, level in value.items() if level in SUPPORT_VALUES and agent != "generic"}


def item_support(metadata) -> dict:
    """``agent_support`` from a catalog_item.metadata blob (top level or under ``metadata``)."""
    try:
        meta = json.loads(metadata) if isinstance(metadata, (str, bytes)) else dict(metadata or {})
    except (TypeError, ValueError):
        return {}
    if not isinstance(meta, dict):
        return {}
    inner = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    return declared_support(meta.get("agent_support") or inner.get("agent_support"))


def enrich(catalog, items: list[dict], diagnostics: list) -> None:
    """Fill verification and declared agent support that the search rows left out from catalog_item.

    The catalog's search result omits ``verification`` and the KB-declared ``agent_support``; without
    them every crawled item failed the source_verified gate. One read of catalog_item covers all
    items; when it is unavailable, they stay unverified (False) and a diagnostic says why."""
    missing = sorted({it["item_id"] for it in items if it.get("verified") is None or not it.get("support")})
    found: dict[str, tuple] = {}
    if missing:
        try:
            with catalog.store.connect(True) as conn:
                for row in conn.execute("SELECT item_id, verification, metadata FROM catalog_item WHERE item_id IN "
                                        "(SELECT value FROM json_each(?))", (json.dumps(missing),)):
                    found[row[0]] = (row[1], row[2])
        except (AttributeError, sqlite3.Error, OSError) as exc:
            diagnostics.append({"source": "catalog.verification", "status": "unavailable",
                                "reason": type(exc).__name__})
    for it in items:
        verification, metadata = found.get(it["item_id"], (None, None))
        if it.get("verified") is None:
            it["verified"] = verification in VERIFIED
        if not it.get("support"):
            it["support"] = item_support(metadata)


@lru_cache(maxsize=1)
def legacy_items() -> tuple[dict, ...]:
    """Bundled reviewed seeds as normalised item dicts (loaded once per process)."""
    from ..catalog import load_catalog

    output = []
    for it in load_catalog(include_legacy=True).items:
        kind = LEGACY_KIND.get(it.legacy_kind) or FAMILY_KIND.get(it.family, "skill")
        tags = sorted({*it.trigger.tags, *it.capability.tags, *it.target_task.tags})
        text = " ".join([it.identity.name, it.capability.text, it.target_task.text, it.trigger.text,
                         *tags, *it.trigger.rule_ids])
        output.append({"item_id": it.identity.id, "kind": kind, "name": it.identity.name,
                       "summary": it.capability.text, "url": it.source.url, "license": it.source.license,
                       "support": {k: v for k, v in it.compatibility.agents.items() if k != "generic"},
                       "difficulty": 2, "risk": list(it.risk_permission.required_permissions),
                       "verified": it.source.status == "verified", "tags": tags, "rule_ids": list(it.trigger.rule_ids),
                       "steps": list(it.action.setup_steps), "trial": it.action.trial,
                       "limitation": "；".join(it.action.limitations), "text": text})
    return tuple(output)


def bm25(query: str, docs: dict[str, str], *, k1: float = 1.2, b: float = .75) -> list[tuple[str, float]]:
    terms = set(tokenize(query))
    bags = {uid: Counter(tokenize(text)) for uid, text in docs.items()}
    if not terms or not bags:
        return []
    avg = sum(sum(bag.values()) for bag in bags.values()) / len(bags) or 1.
    df = Counter(term for bag in bags.values() for term in bag)
    scores = []
    for uid, bag in bags.items():
        norm = k1 * (1 - b + b * sum(bag.values()) / avg)
        score = sum(math.log1p((len(bags) - df[t] + .5) / (df[t] + .5)) * bag[t] * (k1 + 1) / (bag[t] + norm)
                    for t in terms & bag.keys())
        if score > 0:
            scores.append((uid, round(score, 6)))
    return sorted(scores, key=lambda row: (-row[1], row[0]))


def _task_words(inputs: dict) -> str:
    counts = Counter(word for task in inputs.get("tasks") or () for word in (*task.get("domain", ()), *task.get("task_type", ())))
    return " ".join(word for word, _ in counts.most_common(6))


def _fallback(problems, inputs) -> tuple[list[tuple[str, float]], dict[str, dict]]:
    items = {item["item_id"]: item for item in legacy_items()}
    docs = {uid: item["text"] for uid, item in items.items()}
    from ..problems import RULE_TO_PROBLEM

    best: dict[str, tuple[float, dict]] = {}
    for problem in problems:
        query = " ".join([problem["reason"], problem["type"], *map(str, problem["vars"].values())])
        for uid, score in bm25(query, docs):
            types = {RULE_TO_PROBLEM.get(rule) for rule in items[uid]["rule_ids"]}
            if problem["type"] not in types:
                continue  # same evidence bar as the real catalog: the seed must target this problem
            raw = score
            if raw > best.get(uid, (0, None))[0]:
                best[uid] = (raw, problem)
    rows, payload = [], {}
    for uid, (raw, problem) in sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0])):
        cand = from_item(items[uid], problem, inputs, match_basis="catalog_feature")
        rows.append((cand["rec_key"], raw))
        payload[cand["rec_key"]] = cand
    return rows, payload


def recall(problems: list[dict], inputs: dict, catalog=None, *,
           diagnostics: list | None = None, meta: dict | None = None) -> tuple[list[tuple[str, float]], dict[str, dict]]:
    """Return (rows, payload); ``meta['generation']`` / ``meta['vector']`` describe the catalog state."""
    diagnostics = diagnostics if diagnostics is not None else []
    meta = meta if meta is not None else {}
    active = sorted((p for p in problems if p["status"] == "active"),
                    key=lambda p: (-p["weekly_count"], p["key"]))[:PER_PROBLEM]
    try:
        if catalog is None:
            raise LookupError("catalog_not_configured")
        from orbit_catalog.contracts import Feature, MatchRequest
    except (ImportError, LookupError) as exc:
        diagnostics.append({"source": "catalog", "status": "fallback", "reason": str(exc) or type(exc).__name__})
        meta["vector"] = {"status": "not_configured"}
        return _fallback(active, inputs)

    # every agent the user actually runs, so resources for a secondary agent are not filtered out
    top_agent = sorted(a for a, n in (inputs.get("agents") or {}).items() if n and n > 0)
    words = _task_words(inputs)
    queries: list[tuple[dict | None, object]] = []
    for problem in active:
        features = [Feature(feature="dimension", value=problem["dimension"])] if problem["dimension"] else []
        queries.append((problem, MatchRequest(purpose="library", text=(problem["reason"] + " " + words)[:8000],
                                              problem_type=problem["type"], features=features, agents=top_agent,
                                              language=problem["language"], limit=10, per_route=100)))
    profile = inputs.get("profile") or {}
    strong = {tag for tag, n in (profile.get("evidence_sessions") or {}).items() if n >= MIN_PROFILE_EVIDENCE}
    profile_terms = [t for t in (*sorted(profile.get("tags") or {}, key=lambda t: -(profile["tags"][t])),
                                 *(profile.get("languages") or ()), *(profile.get("frameworks") or ()),
                                 *(profile.get("tools") or ())) if t in strong][:12]
    if profile_terms:
        queries.append((None, MatchRequest(purpose="library", text=" ".join(profile_terms), agents=top_agent,
                                           limit=10, per_route=100)))
    rows: dict[str, float] = {}
    profile_rows: dict[str, float] = {}
    profile_payload: dict[str, dict] = {}
    payload: dict[str, dict] = {}
    kept: list[tuple[dict | None, dict, float]] = []
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="orbit-rec-catalog")
    # 2 s per call; four run at once, so the whole batch gets one deadline per wave.
    deadline = time.monotonic() + TIMEOUT_S * math.ceil(len(queries) / 4)
    try:
        futures = [(problem, pool.submit(catalog.match, request)) for problem, request in queries]
        for problem, future in futures:
            label = problem["key"] if problem else "profile"
            try:
                response = future.result(timeout=max(.01, deadline - time.monotonic()))
            except FutureTimeout:
                diagnostics.append({"source": "catalog", "status": "timeout", "reason": label})
                continue
            except Exception as exc:  # one bad query must not drop the others
                diagnostics.append({"source": "catalog", "status": "failed", "reason": f"{label}: {type(exc).__name__}"})
                continue
            if "generation" in response:
                meta["generation"] = response["generation"]
            meta.setdefault("vector", response.get("vector") or {"status": "unknown"})
            for row in response.get("items") or ():
                item = _normalise_catalog(row)
                if item is None:
                    continue
                if problem is not None:
                    friction = any(f.get("feature") == "friction" and f.get("value") == problem["type"]
                                   for f in row.get("matched_features") or ())
                    remedy = "remedy" in ((row.get("score_parts") or {}).get("routes") or {})
                    if not (friction or remedy):
                        continue
                kept.append((problem, item, float(row.get("score") or 0.) + 1e-6))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    enrich(catalog, [item for _, item, _ in kept], diagnostics)
    for problem, item, raw in kept:
        key = "catalog:" + item["item_id"]
        if problem is not None:
            if raw > rows.get(key, 0):
                rows[key] = raw
                payload[key] = from_item(item, problem, inputs, match_basis="catalog_feature")
        else:
            profile_rows[key] = max(profile_rows.get(key, 0), raw)
            profile_payload.setdefault(key, from_item(item, None, inputs, match_basis="profile"))
    diagnostics.append({"source": "catalog.vector", "status": (meta.get("vector") or {}).get("status", "unknown"),
                        "reason": (meta.get("vector") or {}).get("reason", "")})
    meta["profile_payload"] = profile_payload
    meta["profile_rows"] = sorted(profile_rows.items(), key=lambda row: (-row[1], row[0]))
    return sorted(rows.items(), key=lambda row: (-row[1], row[0])), payload
