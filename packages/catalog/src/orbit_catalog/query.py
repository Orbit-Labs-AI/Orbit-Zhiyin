"""Read models for the library UI: cards, keyset lists, facets, detail, models and benchmarks.

Pure functions over ``store.reader()``; nothing here writes. Risk fields are static
estimates (see risk.py), never audit results.
"""

import base64
import json
import math
import threading
from collections import OrderedDict

import numpy as np

from .contracts import canonical_json
from .quality import assess as assess_quality
from .risk import allowed_tools, declared_env, scan

SORTS = {"updated": "updated_at", "installs": "installs", "stars": "stars", "name": "name_key"}
PERMISSIVE = {"MIT", "Apache-2.0", "CC0-1.0", "CC-BY-4.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD",
              "Unlicense", "MPL-2.0", "user-generated"}
RESIDENT_TYPES = {"skill", "rule", "subagent", "command"}
CARD = ("i.item_id,i.type,i.name,i.summary,i.author,i.license,i.official,i.agents,i.difficulty,i.risk_level,i.risk,"
        "i.version,i.updated_at,i.installs,i.stars,i.origin,i.url,i.body_policy,i.canonical_of,i.verification,i.body_len,i.latest_version")
README_LIMIT = 250_000
MODEL_FIELDS = ("provider", "model_id", "family", "context_window", "max_output", "input_per_mtok", "output_per_mtok",
                "cache_read_per_mtok", "reasoning", "tool_call", "knowledge_cutoff")
KIND_LABELS = {"skill": "Skill", "hook": "Hook", "plugin": "插件", "subagent": "子代理", "mcp_server": "MCP",
               "rule": "规则", "workflow": "工作流", "command": "命令", "marketplace": "市场", "guide": "指南",
               "output_style": "输出风格", "lsp_server": "LSP"}
AGENT_LABELS = {"claude_code": "Claude Code", "codex": "Codex", "copilot": "Copilot", "gemini": "Gemini CLI",
                "opencode": "OpenCode", "cursor": "Cursor", "openclaw": "OpenClaw"}
SOURCE_LABELS = {"official": "官方", "community": "社区", "local": "本地", "mirror": "镜像"}
VERIFIED = ("repository_and_skill_read", "repository_and_source_read")
_SPDX = {"mit": "MIT", "mit license": "MIT", "apache-2.0": "Apache-2.0", "apache 2.0": "Apache-2.0",
         "apache license 2.0": "Apache-2.0", "apache-2": "Apache-2.0", "apache2": "Apache-2.0",
         "bsd-3-clause": "BSD-3-Clause", "bsd-2-clause": "BSD-2-Clause", "isc": "ISC", "0bsd": "0BSD",
         "cc0-1.0": "CC0-1.0", "cc0": "CC0-1.0", "cc-by-4.0": "CC-BY-4.0", "unlicense": "Unlicense",
         "mpl-2.0": "MPL-2.0", "gpl-3.0": "GPL-3.0", "gpl-2.0": "GPL-2.0", "agpl-3.0": "AGPL-3.0",
         "lgpl-3.0": "LGPL-3.0"}
_CACHE: OrderedDict = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _cached(key, build):
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    value = build()
    with _CACHE_LOCK:
        _CACHE[key] = value
        while len(_CACHE) > 256:
            _CACHE.popitem(last=False)
    return value


def card(row) -> dict:
    summary = row["summary"] or ""
    return {"item_id": row["item_id"], "kind": row["type"], "name": row["name"],
            "summary": summary if len(summary) <= 280 else summary[:279] + "…",
            "author": row["author"], "license": row["license"], "official": bool(row["official"]),
            "agents": json.loads(row["agents"]), "difficulty": row["difficulty"], "risk_level": row["risk_level"],
            "risk": json.loads(row["risk"]), "version": row["version"], "updated_at": row["updated_at"],
            "installs": row["installs"], "stars": row["stars"], "origin": row["origin"], "url": row["url"],
            "body_policy": row["body_policy"], "canonical_of": row["canonical_of"], "quality": assess_quality(row)}


def license_spdx(value: str | None) -> str | None:
    """Best-effort SPDX id; non-SPDX markers (repository_specific, proprietary) map to None."""
    if not value:
        return None
    if value == "user-generated":
        return value
    key = value.split("(")[0].strip().casefold()
    return _SPDX.get(key) or (value if value in PERMISSIVE else None)


def source_kind(card: dict, metadata: dict | None = None) -> str:
    if card.get("origin") == "local":
        return "local"
    if (metadata or {}).get("mirror"):
        return "mirror"
    return "official" if card.get("official") else "community"


def labels(card: dict, metadata: dict | None = None) -> dict:
    """Display labels shared by library cards and the detail page (A8-05 src/compat)."""
    kind = source_kind(card, metadata)
    spdx = license_spdx(card.get("license"))
    src = SOURCE_LABELS[kind] + (f" · {spdx}" if spdx and spdx != "user-generated" else "")
    repo = "github.com/" in (card.get("url") or "")
    return {"source_kind": kind, "source_label": src, "license_spdx": spdx,
            "compat_label": " · ".join(AGENT_LABELS.get(a, a) for a in card.get("agents") or []),
            "stars_scope": "repo" if repo else "source", "updated_scope": "repo" if repo else "source"}


def _encode_cursor(values: list) -> str:
    return base64.urlsafe_b64encode(canonical_json(values).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> list:
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except ValueError as exc:
        raise ValueError("invalid_query") from exc
    if not isinstance(values, list):
        raise ValueError("invalid_query")
    return values


def _filters(*, kinds=(), agents=(), license=None, max_risk=None, origin=None, official=None, source_id=None,
             exclude=(), include_duplicates=False, skip=None) -> tuple[list[str], list]:
    where = ["i.status='active'", "i.type NOT IN ('model','benchmark')"] if include_duplicates else ["i.listable=1"]
    args = []
    if kinds and skip != "kind":
        if len(kinds) == 1:
            where.append("i.type=?")
            args.append(kinds[0])
        else:
            where.append("i.type IN (SELECT value FROM json_each(?))")
            args.append(json.dumps(list(kinds)))
    if agents and skip != "agent":
        where.append("i.item_id IN (SELECT item_id FROM item_agent WHERE agent IN (SELECT value FROM json_each(?)))")
        args.append(json.dumps(list(agents)))
    for dim, column, value in (("license", "i.license", license), ("risk_level", "i.risk_level", max_risk),
                               ("origin", "i.origin", origin), ("official", "i.official", official)):
        if value is not None and skip != dim:
            where.append(f"{column}{'<=' if dim == 'risk_level' else '='}?")
            args.append(int(value) if dim == "official" else value)
    if source_id:
        where.append("i.item_id IN (SELECT item_id FROM item_source WHERE source_id=? AND status='active')")
        args.append(source_id)
    if exclude:
        where.append("i.item_id NOT IN (SELECT value FROM json_each(?))")
        args.append(json.dumps(list(exclude)))
    return where, args


def list_items(store, *, kinds=(), agents=(), license=None, max_risk=None, origin=None, official=None, source_id=None,
               exclude=(), sort="updated", order="desc", limit=30, cursor=None, include_duplicates=False) -> dict:
    if sort not in SORTS or order not in ("asc", "desc"):
        raise ValueError("invalid_query")
    column, limit = SORTS[sort], max(1, min(100, int(limit)))
    where, args = _filters(kinds=kinds, agents=agents, license=license, max_risk=max_risk, origin=origin,
                           official=official, source_id=source_id, exclude=exclude, include_duplicates=include_duplicates)
    count_where, count_args = list(where), list(args)
    if cursor:
        values = _decode_cursor(cursor)
        if len(values) != 4 or values[:2] != [sort, order]:
            raise ValueError("invalid_query")
        # Keyset position, not a row id: a deleted anchor row simply continues after its key.
        where.append(f"(i.{column},i.item_id) {'<' if order == 'desc' else '>'} (?,?)")
        args.extend(values[2:])
    direction = order.upper()
    with store.reader() as conn:
        rows = conn.execute(f"SELECT {CARD} FROM catalog_item i WHERE {' AND '.join(where)} "
                            f"ORDER BY i.{column} {direction},i.item_id {direction} LIMIT ?", (*args, limit + 1)).fetchall()
        total = None if cursor else conn.execute(
            f"SELECT count(*) FROM catalog_item i WHERE {' AND '.join(count_where)}", count_args).fetchone()[0]
        generation = store.generation(conn)
    items = [card(r) for r in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        key = {"updated_at": last["updated_at"], "installs": last["installs"], "stars": last["stars"],
               "name_key": last["name"].casefold()}[column]
        next_cursor = _encode_cursor([sort, order, key, last["item_id"]])
    return {"items": items, "next_cursor": next_cursor, "total": total, "generation": generation}


def _facet_masks(index, conn, *, kinds=(), agents=(), license=None, max_risk=None, origin=None, official=None,
                 source_id=None, exclude=(), include_duplicates=False) -> tuple[np.ndarray, dict]:
    """Base eligibility plus one boolean mask per filtered dimension (same semantics as _filters)."""
    from .index import KIND_CODE
    if include_duplicates:
        base = ~np.isin(index.kind, [KIND_CODE["model"], KIND_CODE["benchmark"]])
    else:
        base = index.listable.copy()
    if source_id:
        allowed = np.zeros(len(index), dtype=bool)
        for (item_id,) in conn.execute("SELECT item_id FROM item_source WHERE source_id=? AND status='active'", (source_id,)):
            if item_id in index.pos:
                allowed[index.pos[item_id]] = True
        base &= allowed
    for item_id in exclude:
        if item_id in index.pos:
            base[index.pos[item_id]] = False
    dims = {}
    if kinds:
        dims["kind"] = np.isin(index.kind, [KIND_CODE.get(k, -2) for k in kinds])
    if agents:
        bits = sum(1 << index.agent_bits[a] for a in set(agents) if a in index.agent_bits)
        dims["agent"] = (index.agent_mask & np.uint64(bits)) != 0
    if license is not None:
        dims["license"] = index.license == (index.licenses.index(license) if license in index.licenses else -1)
    if max_risk is not None:
        dims["risk_level"] = index.risk_level <= max_risk
    if origin is not None:
        dims["origin"] = index.local == (origin == "local") if origin in ("local", "remote") else np.zeros(len(index), bool)
    if official is not None:
        dims["official"] = index.official == bool(official)
    return base, dims


def facets(store, **filters) -> dict:
    """Counts per dimension from the in-memory index; each dimension ignores its own filter."""
    from .index import KINDS
    for key in ("sort", "order", "limit", "cursor"):
        filters.pop(key, None)
    with store.reader() as conn:
        index = store.index(conn)

        def build():
            base, dims = _facet_masks(index, conn, **filters)

            def without(skip):
                mask = base.copy()
                for dim, values in dims.items():
                    if dim != skip:
                        mask &= values
                return mask

            def counts(values, mask, labels=None, top=None):
                pairs = [(labels[v] if labels else int(v), int(n)) for v, n in
                         zip(*np.unique(values[mask], return_counts=True), strict=True)]
                pairs.sort(key=lambda p: (-p[1], str(p[0])))
                return [{"value": v, "count": n} for v, n in pairs[:top]]
            result = {"generation": index.generation, "total": int(without(None).sum())}
            result["kind"] = counts(index.kind, without("kind"), KINDS)
            result["license"] = [r for r in counts(index.license, without("license"), index.licenses) if r["value"]][:20]
            result["risk_level"] = counts(index.risk_level, without("risk_level"))
            result["origin"] = [{"value": "local" if r["value"] else "remote", "count": r["count"]}
                                for r in counts(index.local.astype(np.int8), without("origin"))]
            mask = without("official")
            result["official"] = {"true": int((mask & index.official).sum()), "false": int((mask & ~index.official).sum())}
            result["difficulty"] = counts(index.difficulty, without("difficulty"))
            mask = without("agent")
            agents = [{"value": agent, "count": int((mask & ((index.agent_mask >> np.uint64(bit)) & np.uint64(1)).astype(bool)).sum())}
                      for agent, bit in index.agent_bits.items()]
            result["agent"] = sorted((a for a in agents if a["count"]), key=lambda a: (-a["count"], a["value"]))
            return result
        return _cached(("facets", str(store.path), index.generation, canonical_json(filters)), build)


def _cards(conn, item_ids) -> dict:
    if not item_ids:
        return {}
    return {r["item_id"]: card(r) for r in conn.execute(
        f"SELECT {CARD} FROM catalog_item i WHERE i.item_id IN (SELECT value FROM json_each(?))", (json.dumps(list(item_ids)),))}


def _related(store, conn, item_id: str) -> list[dict]:
    related = {}
    for other, relation in conn.execute("SELECT b,relation FROM item_relation WHERE a=? UNION ALL "
                                        "SELECT a,relation FROM item_relation WHERE b=?", (item_id, item_id)):
        related.setdefault(other, (relation, 1.0))
    index = store.index(conn)
    position = index.pos.get(item_id)
    if position is not None and index.item_keys[position]:
        keys = index.item_keys[position]
        shared = np.zeros(len(index), dtype=np.int32)
        for key in keys:
            shared[index.postings[key][0]] += 1
        shared[position] = 0
        shared[~index.listable] = 0
        candidates = np.flatnonzero(shared)
        if len(candidates) > 200:
            candidates = candidates[np.argsort(-shared[candidates], kind="stable")[:200]]
        sizes = np.array([len(index.item_keys[i]) for i in candidates], dtype=np.float64)
        scores = shared[candidates] / (len(keys) + sizes - shared[candidates])
        added = 0
        for j in np.lexsort((candidates, -scores)):
            other = index.ids[candidates[j]]
            if other in related:
                continue
            related[other] = ("similar", round(float(scores[j]), 4))
            added += 1
            if added >= 5:
                break
    cards = _cards(conn, related)
    return [{"card": cards[other], "relation": relation, "score": score}
            for other, (relation, score) in related.items() if other in cards]


def get_item(store, item_id: str) -> dict | None:
    with store.reader() as conn:
        row = conn.execute(f"SELECT {CARD},i.status,i.language,i.latest_version,i.content_hash,i.body_len,i.first_seen,"
                           "i.last_seen,v.doc_sha,v.body_sha FROM catalog_item i JOIN item_version v "
                           "ON v.version_id=i.latest_version WHERE i.item_id=?", (item_id,)).fetchone()
        if row is None:
            return None
        resource = store.load_resource(conn, row["doc_sha"], row["body_sha"])
        result = card(row)
        licensed = row["body_policy"] == "licensed"
        body = resource.body if licensed else None
        manifest, hints = resource.manifest, resource.install
        license_ok = (row["license"] in PERMISSIVE and licensed) or (row["type"] in ("plugin", "mcp_server") and bool(hints))
        children = [r[0] for r in conn.execute("SELECT child_id FROM item_component WHERE parent_id=? ORDER BY child_id", (item_id,))]
        child_cards = _cards(conn, children)
        result.update({
            "status": row["status"], "language": row["language"], "version_id": row["latest_version"],
            "content_hash": row["content_hash"],
            "readme": body[:README_LIMIT] if body else None,
            "readme_policy": "inline" if licensed else "link_only",
            "manifest": manifest, "features": [f.model_dump() for f in resource.features],
            "versions": [dict(r) for r in conn.execute(
                "SELECT version_id,version,commit_sha,content_hash,size,created_at FROM item_version "
                "WHERE item_id=? ORDER BY created_at DESC,rowid DESC LIMIT 5", (item_id,))],
            "permissions": {"flags": result["risk"], "level": row["risk_level"], "estimate": True,
                            "allowed_tools": allowed_tools(manifest), "declared_env": declared_env(manifest)},
            "components": [child_cards[c] for c in children if c in child_cards],
            "related": _related(store, conn, item_id),
            "sources": [dict(r) for r in conn.execute(
                "SELECT source_id,native_id,status,fetched_at FROM item_source WHERE item_id=? ORDER BY source_id,native_id",
                (item_id,))],
            "install": _install(item_id, row, result["agents"], hints, license_ok),
            "resident_tokens_est": math.ceil(row["body_len"] / 4) if row["type"] in RESIDENT_TYPES else None,
            "scan": scan(resource, result["risk"], row["risk_level"]),
            "first_seen": row["first_seen"], "last_seen": row["last_seen"]})
        result.update(labels(result, resource.metadata))
        return result


def _install(item_id: str, row, targets: list, hints: dict, license_ok: bool) -> dict:
    reason = None
    if row["status"] != "active":
        reason = "inactive"
    elif row["type"] == "hook" and not (isinstance(hints, dict) and hints.get("hook")):
        reason = "hook_without_install_declaration"
    elif not license_ok:
        reason = "license_not_permissive" if row["type"] not in ("plugin", "mcp_server") else "no_install_declaration"
    return {"ref": {"source": "catalog_item", "id": item_id}, "targets": targets, "hints": hints,
            "license_ok": license_ok, "installable": reason is None, "reason": reason}


def cards_by_id(store, item_ids: list[str]) -> dict:
    """Batch cards in request order (restore panel for "not interested"); unknown ids are reported."""
    ids = list(dict.fromkeys(item_ids))
    with store.reader() as conn:
        found = _cards(conn, ids)
        generation = store.generation(conn)
    items = [{**found[i], **labels(found[i])} for i in ids if i in found]
    return {"items": items, "missing": [i for i in ids if i not in found], "generation": generation}


# -- models and benchmarks -------------------------------------------------------------
def _model_table(store, conn) -> list[dict]:
    generation = store.generation(conn)

    def build():
        rows = conn.execute("SELECT m.*,i.name,coalesce((SELECT max(c.priority) FROM item_source s JOIN catalog_source c "
                            "USING(source_id) WHERE s.item_id=m.item_id AND s.status='active'),0) AS priority "
                            "FROM model_info m JOIN catalog_item i USING(item_id) WHERE i.status='active'").fetchall()
        counts = dict(conn.execute("SELECT b.canonical_model_id,count(*) FROM benchmark_result b JOIN catalog_item i "
                                   "USING(item_id) WHERE i.status='active' GROUP BY 1").fetchall())
        groups = {}
        for row in sorted(rows, key=lambda r: (-r["priority"], r["source_id"] or "", r["item_id"])):
            groups.setdefault(row["canonical_id"], []).append(row)
        models = []
        for canonical_id, members in groups.items():
            model = {"canonical_id": canonical_id, "name": members[0]["name"]}
            for field in MODEL_FIELDS:
                model[field] = next((m[field] for m in members if m[field] is not None), None)
            for field in ("reasoning", "tool_call"):
                model[field] = None if model[field] is None else bool(model[field])
            aliases = []
            for m in members:
                aliases.extend(a for a in json.loads(m["aliases"]) if a not in aliases)
            model["aliases"] = aliases
            model["modalities"] = next((json.loads(m["modalities"]) for m in members if json.loads(m["modalities"])), [])
            model["sources"] = [{"source_id": m["source_id"], "item_id": m["item_id"], "model_id": m["model_id"]} for m in members]
            model["benchmarks_count"] = counts.get(canonical_id, 0)
            models.append(model)
        return models
    return _cached(("models", str(store.path), generation), build)


def _page(items: list, kind: str, limit: int, cursor: str | None) -> dict:
    offset = 0
    if cursor:
        values = _decode_cursor(cursor)
        if len(values) != 2 or values[0] != kind or not isinstance(values[1], int) or values[1] < 0:
            raise ValueError("invalid_query")
        offset = values[1]
    limit = max(1, min(200, int(limit)))
    end = offset + limit
    return {"items": items[offset:end], "next_cursor": _encode_cursor([kind, end]) if end < len(items) else None,
            "total": len(items)}


def models(store, *, provider=None, q=None, sort="name", limit=50, cursor=None) -> dict:
    if sort not in ("name", "context", "price"):
        raise ValueError("invalid_query")
    with store.reader() as conn:
        rows = _model_table(store, conn)
        generation = store.generation(conn)
    if provider:
        rows = [m for m in rows if m["provider"] == provider]
    if q:
        needle = q.casefold()
        rows = [m for m in rows if needle in m["canonical_id"].casefold() or needle in (m["name"] or "").casefold()
                or any(needle in str(a).casefold() for a in m["aliases"])]
    keys = {"name": lambda m: (m["canonical_id"].casefold(),),
            "context": lambda m: (m["context_window"] is None, -(m["context_window"] or 0), m["canonical_id"]),
            "price": lambda m: (m["input_per_mtok"] is None, m["input_per_mtok"] or 0, m["canonical_id"])}
    return {**_page(sorted(rows, key=keys[sort]), "models:" + sort, limit, cursor), "generation": generation}


def benchmarks(store, *, model=None, benchmark=None, effort=None, harness=None, limit=100, cursor=None) -> dict:
    where, args = ["i.status='active'"], []
    if model:
        where.append("(b.canonical_model_id=? OR b.model_id=?)")
        args.extend([model, model])
    for column, value in (("benchmark", benchmark), ("effort", effort), ("harness", harness)):
        if value:
            where.append(f"b.{column}=?")
            args.append(value)
    with store.reader() as conn:
        rows = conn.execute("SELECT b.*,i.url,EXISTS(SELECT 1 FROM model_info m WHERE m.canonical_id=b.canonical_model_id) "
                            f"AS resolved FROM benchmark_result b JOIN catalog_item i USING(item_id) WHERE {' AND '.join(where)} "
                            "ORDER BY b.benchmark,b.score IS NULL,b.score DESC,b.item_id", args).fetchall()
    items = [{"canonical_model_id": r["canonical_model_id"], "model": r["model_id"], "resolved": bool(r["resolved"]),
              "effort": r["effort"], "harness": r["harness"], "benchmark": r["benchmark"],
              "benchmark_version": r["benchmark_version"], "score": r["score"], "unit": r["unit"],
              "measured_at": r["measured_at"], "source_id": r["source_id"], "url": r["url"]} for r in rows]
    return _page(items, "benchmarks", limit, cursor)


def get_model(store, canonical_id: str) -> dict | None:
    with store.reader() as conn:
        model = next((m for m in _model_table(store, conn) if m["canonical_id"] == canonical_id), None)
    if model is None:
        return None
    return {**model, "benchmarks": benchmarks(store, model=canonical_id, limit=200)["items"]}


# -- A8 library view -------------------------------------------------------------------
LIBRARY_WEIGHTS = {"feature_overlap": 0.5, "friction": 0.3, "trust": 0.2}
LIBRARY_SORTS = ("fit", "pain", "updated", "stars", "name")
ORIGIN_WEIGHT = {"curated": 1.0, "declared": 1.0, "extracted": 0.6}
LIBRARY_KINDS = ("skill", "hook", "plugin", "subagent", "mcp_server", "rule", "workflow", "command")


def trust(row) -> float:
    """0.35 official + 0.25 permissive license + 0.2 source read & verified + 0.2 (1 - risk/3)."""
    value = (0.35 * bool(row["official"]) + 0.25 * (license_spdx(row["license"]) in PERMISSIVE)
             + 0.2 * (row["verification"] in VERIFIED) + 0.2 * (1 - min(3, row["risk_level"]) / 3))
    return round(min(1.0, value), 4)


def _profile_overlap(conn, pairs: dict, ids: list[str] | None) -> dict:
    """item_id -> raw overlap (same formula as features.match_items: Σ w·min(weight,1) / Σ w)."""
    total = sum(p["weight"] for p in pairs.values())
    if not total:
        return {}
    keys = list(pairs)
    scores: dict[str, float] = {}
    for start in range(0, len(keys), 200):
        part = keys[start:start + 200]
        values = ",".join("(?,?,?)" for _ in part)
        id_filter, extra = "", []
        if ids is not None:
            id_filter, extra = " AND f.item_id IN (SELECT value FROM json_each(?))", [json.dumps(ids)]
        sql = (f"WITH q(feature,value,w) AS (VALUES {values}) SELECT f.item_id, sum(s) FROM ("
               f"SELECT f.item_id, q.w*min(max(f.weight),1.0) s FROM q JOIN item_feature f ON f.feature=q.feature "
               f"AND f.value=q.value WHERE 1{id_filter} GROUP BY f.item_id,f.feature,f.value) f GROUP BY f.item_id")
        args = [x for k in part for x in (*k, pairs[k]["weight"])] + extra
        for item_id, score in conn.execute(sql, args):
            scores[item_id] = scores.get(item_id, 0.0) + score / total
    return scores


def library(store, *, profile: dict | None = None, lexical: dict | None = None, tab: str = "for", kinds=(),
            agents=(), q: str = "", sort: str = "fit", exclude=(), limit: int = 20, cursor: str | None = None) -> dict:
    """A8 cards with parts {feature_overlap, friction, trust} and m = round(100 · Σ weight·part).

    ``profile``: {"ok", "n_sessions", "window_days", "scope_hash", "features": [{fid, feature, value,
    weight, sessions, label}]} with features already mapped to catalog (feature, value) pairs.
    ``lexical``: item_id -> retrieval score from hybrid search (seed and, without a profile, the
    relevance part). Without a usable profile no personal reason is produced and friction stays 0.
    """
    if tab not in ("for", "local") or sort not in LIBRARY_SORTS:
        raise ValueError("invalid_query")
    kinds = [k for k in kinds if k] or list(LIBRARY_KINDS)
    if set(kinds) - set(LIBRARY_KINDS):
        raise ValueError("invalid_query")
    limit = max(1, min(50, int(limit)))
    offset = 0
    if cursor:
        values = _decode_cursor(cursor)
        if len(values) != 3 or values[:2] != ["library", sort] or not isinstance(values[2], int) or values[2] < 0:
            raise ValueError("invalid_query")
        offset = values[2]
    profile = profile or {}
    ok = bool(profile.get("ok")) and bool(profile.get("features"))
    pairs: dict = {}
    for f in profile.get("features") or [] if ok else []:
        key = (f["feature"], f["value"])
        if key not in pairs or pairs[key]["weight"] < f["weight"]:
            pairs[key] = f
    friction_profile = {k[1]: f for k, f in pairs.items() if k[0] == "friction"}
    top_friction = max((f["weight"] for f in friction_profile.values()), default=0) or 1
    lexical = lexical or {}
    where, args = _filters(kinds=kinds, agents=agents, exclude=exclude,
                           origin="local" if tab == "local" else None)
    with store.reader() as conn:
        generation = store.generation(conn)
        if tab == "local":
            seed = None  # Every local item is a candidate.
        else:
            overlap_all = _profile_overlap(conn, pairs, None) if pairs else {}
            seed = set(lexical) if q.strip() else set(overlap_all) | set(lexical)
            if not seed and not q.strip():
                # No profile and no query: fall back to a trust/popularity shortlist, never personal.
                seed = {r[0] for r in conn.execute(
                    f"SELECT i.item_id FROM catalog_item i WHERE {' AND '.join(where)} "
                    "ORDER BY i.official DESC,i.stars DESC,i.item_id LIMIT 200", args)}
        sql = (f"SELECT {CARD},i.verification FROM catalog_item i WHERE {' AND '.join(where)}"
               + (" AND i.item_id IN (SELECT value FROM json_each(?))" if seed is not None else ""))
        rows = conn.execute(sql, [*args, *([json.dumps(sorted(seed))] if seed is not None else [])]).fetchall()
        if tab == "local" and q.strip():
            needle = q.strip().casefold()
            rows = [r for r in rows if needle in f"{r['name']} {r['summary']}".casefold()]
        ids = [r["item_id"] for r in rows]
        overlap = (_profile_overlap(conn, pairs, ids) if tab == "local" else
                   {i: overlap_all[i] for i in ids if i in overlap_all}) if pairs else {}
        feats: dict[str, list] = {}
        for start in range(0, len(ids), 500):
            part = ids[start:start + 500]
            for r in conn.execute("SELECT item_id,feature,value,weight,origin,evidence FROM item_feature "
                                  "WHERE item_id IN (SELECT value FROM json_each(?))", (json.dumps(part),)):
                feats.setdefault(r[0], []).append(r)
        hidden = conn.execute("SELECT count(*) FROM catalog_item WHERE listable=1 AND item_id IN "
                              "(SELECT value FROM json_each(?))", (json.dumps(list(exclude)),)).fetchone()[0] if exclude else 0
    window = profile.get("window_days")
    items = []
    for row in rows:
        item_id = row["item_id"]
        friction, matched, why_friction, seen = 0.0, [], [], set()
        for _, feature, value, _weight, origin, evidence in sorted(
                feats.get(item_id, []), key=lambda r: -ORIGIN_WEIGHT.get(r[4], 0.6)):
            entry = pairs.get((feature, value))
            if entry is None or (feature, value) in seen:
                continue
            seen.add((feature, value))
            matched.append({"feature": feature, "value": value, "evidence": evidence, "origin": origin,
                            "sessions": entry.get("sessions"), "label": entry.get("label") or value,
                            "_w": entry["weight"]})
            if feature == "friction":
                # Strongest hit, relative to the user's top friction; extracted text counts 0.6.
                friction = max(friction, min(1.0, entry["weight"] / top_friction * ORIGIN_WEIGHT.get(origin, 0.6)))
        matched.sort(key=lambda m: (m["feature"] != "friction", -m["_w"], m["feature"], m["value"]))
        # Absolute parts: the weighted share of the profile the item covers, or the retrieval
        # score of the query (search.route_strength). Never divided by the best candidate, so
        # a page of weak hits cannot show a high match and one item scores the same in any page.
        fo = overlap.get(item_id, 0.0) if ok else lexical.get(item_id, 0.0)
        parts = {"feature_overlap": round(min(1.0, fo), 4), "friction": round(friction, 4), "trust": trust(row)}
        m = round(100 * sum(LIBRARY_WEIGHTS[k] * v for k, v in parts.items()))
        why = []
        if ok:
            for hit in (h for h in matched if h["feature"] == "friction" and h["sessions"]):
                why_friction.append(f"覆盖你的摩擦：{hit['label']}（近 {window} 天 {hit['sessions']} 个会话）")
            usage = [f"你近 {window} 天在 {h['sessions']} 个会话用到 {h['label']}"
                     for h in matched if h["feature"] != "friction" and h["sessions"]]
            why = (usage[:1] + why_friction[:1] + usage[1:2] + why_friction[1:2])[:2]
        else:
            if lexical.get(item_id):
                why.append("与搜索词匹配")
            if row["official"]:
                why.append("官方维护")
            elif row["risk_level"] == 0:
                why.append("静态估计未发现高风险权限")
            why = why[:2]
        base = card(row)
        info = labels(base)
        items.append({
            "id": item_id, "item_id": item_id, "kind": base["kind"], "kind_label": KIND_LABELS.get(base["kind"], base["kind"]),
            "name": base["name"], "src": info["source_label"], "source_kind": info["source_kind"],
            "license": info["license_spdx"] or base["license"], "author": base["author"], "desc": base["summary"],
            "compat": info["compat_label"], "agents": base["agents"], "m": m, "parts": parts, "why": why,
            "matched_features": [{k: v for k, v in h.items() if k not in ("_w", "label")} for h in matched[:6]],
            "stars": base["stars"], "stars_scope": info["stars_scope"], "updated_at": base["updated_at"],
            "updated_scope": info["updated_scope"], "users": None, "local": base["origin"] == "local",
            "risk_level": base["risk_level"], "quality": base["quality"], "installed": None, "rec": None, "url": base["url"]})
    keys = {"fit": lambda c: (-c["m"], -c["parts"]["friction"], c["id"]),
            "pain": lambda c: (-c["parts"]["friction"], -c["m"], c["id"]),
            "updated": lambda c: (-c["updated_at"], c["id"]), "stars": lambda c: (-c["stars"], c["id"]),
            "name": lambda c: (c["name"].casefold(), c["id"])}
    items.sort(key=keys[sort])
    end = offset + limit
    return {"generation": generation,
            "profile_basis": {"scope_hash": profile.get("scope_hash"), "n_sessions": profile.get("n_sessions", 0),
                              "window_days": window, "ok": ok},
            "weights": dict(LIBRARY_WEIGHTS), "total": len(items),
            "next_cursor": _encode_cursor(["library", sort, end]) if end < len(items) else None,
            "hidden_excluded": hidden, "installed_summary": None, "items": items[offset:end]}
