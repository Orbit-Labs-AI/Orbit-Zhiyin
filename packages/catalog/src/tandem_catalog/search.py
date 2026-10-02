"""Filter first, independent recall routes, RRF, transparent reranking and diversity.

Eligibility is a boolean mask from the in-memory index; the lexical route asks FTS5 for
the top-K chunks once (K doubles only when the mask leaves too few items) and the
semantic route scans an fp16 matrix exactly.
"""

import json
import sqlite3
import threading
from collections import OrderedDict, defaultdict

import numpy as np

from .contracts import Feature, MatchRequest, canonical_json
from .features import lexical_tokens
from .vectors import blocked_scores, normalize_vectors

RANKING_VERSION = "hybrid-rrf60-mmr80-v3"
ROUTE_WEIGHTS = {"remedy": 1.5, "feature": 1.2, "lexical": 1.0, "semantic": 2.0}
STOP_WORDS = set("的 和 为 是 在 与 及 了 把 中 从 到 用 做 对 将 并 要 如何 是否 以及 进行 帮助 and or the of to a in for with on at by an as is".split())
QUERY_ALIASES = {
    "调试": "debug debugging", "排错": "debugging", "根因": "root cause", "重试": "retry",
    "论文": "paper scientific", "引用": "citation citations", "无障碍": "accessibility",
    "网页": "web", "键盘": "keyboard", "性能": "performance", "文档": "document",
    "测试": "testing", "优化": "optimization", "验证": "verification",
}
MAX_TOKENS = 24
MIN_K = 400
MAX_K = 8000
_QUERY_CACHE: OrderedDict = OrderedDict()
_QUERY_LOCK = threading.Lock()


def eligibility(request: MatchRequest) -> tuple[str, list]:
    """SQL form of ``CatalogIndex.mask`` for external exporters (``catalog_item i``); search uses the mask."""
    terms = ["i.status='active'", "i.canonical_of IS NULL", "i.difficulty<=?"]
    args = [request.max_difficulty]
    for values, expression in ((request.types, "i.type IN"), (request.excluded_ids, "i.item_id NOT IN")):
        if values:
            terms.append(expression + " (SELECT value FROM json_each(?))")
            args.append(canonical_json(values))
    if request.source_ids:
        terms.append("EXISTS(SELECT 1 FROM item_source s JOIN catalog_source cs USING(source_id) WHERE s.item_id=i.item_id "
                     "AND s.status='active' AND (cs.enabled=1 OR cs.source_id='local') AND s.source_id IN (SELECT value FROM json_each(?)))")
        args.append(canonical_json(request.source_ids))
    if request.agents:
        compatibility = "EXISTS(SELECT 1 FROM item_agent a WHERE a.item_id=i.item_id AND a.agent IN (SELECT value FROM json_each(?)))"
        if request.purpose == "library":
            compatibility = "(" + compatibility + " OR i.agents='[]')"
        terms.append(compatibility)
        args.append(canonical_json(request.agents))
    if request.language:
        terms.append("i.language='any' OR i.language IN (SELECT value FROM json_each(?))")
        args.append(canonical_json(request.language.split("_or_")))
    if request.purpose == "recommendation":
        curated = "EXISTS(SELECT 1 FROM item_feature f WHERE f.item_id=i.item_id AND f.origin='curated' AND f.feature="
        terms.extend([curated + "'friction' AND f.value=?)", curated + "'scene' AND f.value=?)",
                      curated + "'dimension' AND f.value IN (SELECT value FROM json_each(?)))",
                      "i.verification IN ('repository_and_skill_read','repository_and_source_read')"])
        args.extend([request.problem_type, request.scene,
                     canonical_json([f.value for f in request.features if f.feature == "dimension"])])
    return " AND ".join("(" + term + ")" for term in terms), args


def encode_query(encoder, text: str) -> np.ndarray:
    """Query vectors are LRU-cached per (model, text); match_many pre-warms this in one batch."""
    key = (encoder.model_id, text)
    with _QUERY_LOCK:
        if key in _QUERY_CACHE:
            _QUERY_CACHE.move_to_end(key)
            return _QUERY_CACHE[key]
    vector = normalize_vectors(encoder.encode([text], query=True), 1, encoder.dimensions)[0]
    remember_queries(encoder, [text], vector[None, :])
    return vector


def remember_queries(encoder, texts: list[str], vectors: np.ndarray) -> None:
    with _QUERY_LOCK:
        for text, vector in zip(texts, vectors, strict=True):
            _QUERY_CACHE[(encoder.model_id, text)] = vector
            _QUERY_CACHE.move_to_end((encoder.model_id, text))
        while len(_QUERY_CACHE) > 256:
            _QUERY_CACHE.popitem(last=False)


def match_expression(text: str, prefix: bool = False) -> str | None:
    # Bilingual lexical expansion keeps offline search useful. It does not create
    # inferred profile features or promote broad topic matches into a separate route.
    own = [t for t in dict.fromkeys(lexical_tokens(text)) if t not in STOP_WORDS]
    expanded = " ".join(value for key, value in QUERY_ALIASES.items() if key in text)
    tokens = list(dict.fromkeys(own + [t for t in lexical_tokens(expanded) if t not in STOP_WORDS]))[:MAX_TOKENS]
    if not tokens:
        return None
    stem = next((t for t in reversed(own) if len(t) >= 3 and t in tokens), None) if prefix else None
    return " OR ".join('"' + t.replace('"', '""') + '"' + ("*" if t == stem else "") for t in tokens)


def _lexical(conn, index, mask, text, limit, prefix):
    match = match_expression(text, prefix)
    if not match:
        return [], {}
    k = max(limit * 4, MIN_K)
    while True:
        try:
            rows = conn.execute("SELECT rowid,bm25(chunk_fts,4.0,1.0) AS s FROM chunk_fts WHERE chunk_fts MATCH ? "
                                "ORDER BY s,rowid LIMIT ?", (match, k)).fetchall()
        except sqlite3.OperationalError:
            # An FTS syntax edge must cost only this route, not the feature/remedy/semantic recall.
            return None, {}
        owners = index.items_of([r[0] for r in rows])
        hits, passages = [], {}
        for (rowid, score), owner in zip(rows, owners, strict=True):
            if owner < 0 or not mask[owner]:
                continue
            item_id = index.ids[owner]
            if item_id in passages:
                continue
            hits.append((item_id, -score))
            passages[item_id] = rowid
            if len(hits) >= limit:
                break
        if len(hits) >= limit or len(rows) < k or k >= MAX_K:
            return hits, passages
        k *= 2


def _features(index, mask, features, limit, curated_only=False):
    if not features:
        return [], set()
    wanted = {}
    for f in features:
        wanted[(f.feature, f.value)] = f.weight
    scores = np.zeros(len(index), dtype=np.float64)
    hit = np.zeros(len(index), dtype=bool)
    for key, query_weight in wanted.items():
        if key not in index.postings:
            continue
        idx, weight, curated = index.postings[key]
        if curated_only:
            idx, weight = idx[curated], weight[curated]
        scores[idx] += np.minimum(1.0, weight) * query_weight
        hit[idx] = True
    hit &= mask
    candidates = np.flatnonzero(hit)
    denominator = sum(wanted.values())
    ranked = sorted(((index.ids[i], float(scores[i] / denominator)) for i in candidates), key=lambda x: (-x[1], x[0]))
    return ranked[:limit], set(wanted)


def _semantic(conn, index, mask, encoder, text, limit):
    query = encode_query(encoder, text)
    matrix, owners, rowids = index.matrix(conn, encoder.model_id, encoder.dimensions)
    eligible = mask[owners] if len(owners) else np.zeros(0, dtype=bool)
    scanned = int(eligible.sum())
    if not scanned:
        return [], {}, 0
    scores = blocked_scores(matrix, query)
    rows = np.flatnonzero(eligible & (scores > 0))
    # <=4 embed chunks per item, so the top 4*limit rows always hold `limit` distinct items.
    if len(rows) > limit * 4:
        rows = rows[np.argpartition(-scores[rows], limit * 4)[:limit * 4]]
    best = {}
    for row in rows[np.argsort(-scores[rows], kind="stable")]:
        item_id = index.ids[owners[row]]
        if item_id not in best:
            best[item_id] = (float(scores[row]), int(row))
    hits = sorted(((item_id, score) for item_id, (score, _) in best.items()), key=lambda x: (-x[1], x[0]))[:limit]
    return hits, {item_id: int(rowids[best[item_id][1]]) for item_id, _ in hits}, scanned


def _matched_features(conn, item_ids, wanted, query_weights):
    """Audit rows for the matched keys (curated first, then the larger weight)."""
    result = defaultdict(dict)
    if not wanted or not item_ids:
        return {}
    for row in conn.execute("SELECT * FROM item_feature WHERE item_id IN (SELECT value FROM json_each(?))",
                            (json.dumps(item_ids),)):
        key = row["feature"], row["value"]
        if key not in wanted:
            continue
        old = result[row["item_id"]].get(key)
        curated = row["origin"] == "curated"
        if old is None or (curated and old["origin"] != "curated") or (
                curated == (old["origin"] == "curated") and row["weight"] > old["weight"]):
            result[row["item_id"]][key] = {**dict(row), "query_weight": query_weights[key]}
    return {item_id: list(values.values()) for item_id, values in result.items()}


def _passages(store, conn, index, rowids: dict) -> dict:
    """item_id -> passage dict; text is recomputed from the stored version (contentless FTS)."""
    result = {}
    for item_id, rowid in rowids.items():
        if not 0 <= rowid < len(index.chunk_ordinal):
            continue
        ordinal = int(index.chunk_ordinal[rowid])
        row = conn.execute("SELECT field,heading FROM resource_chunk WHERE item_id=? AND ordinal=? AND chunk_rowid=?",
                           (item_id, ordinal, rowid)).fetchone()
        texts = store.chunk_texts(conn, item_id) if row else []
        if ordinal < len(texts):
            result[item_id] = {"chunk_id": str(rowid), "field": row["field"], "heading": row["heading"],
                               "text": texts[ordinal], "start": None}
    return result


def _query_features(request: MatchRequest) -> list[Feature]:
    features = list(request.features)
    if request.problem_type:
        features.append(Feature(feature="friction", value=request.problem_type))
    return features


def query_text(request: MatchRequest) -> str:
    return request.text or " ".join(f.value for f in _query_features(request))


def search(store, request: MatchRequest, encoder=None) -> dict:
    response = {"contract": "catalog-match-v1", "ranking_version": RANKING_VERSION,
                "purpose": request.purpose, "problem_id": request.problem_id,
                "score_meaning": "retrieval_relevance_not_effectiveness", "effect_status": "unmeasured",
                "items": [], "gates": [], "routes": {}, "vector": {"status": "not_configured"}}
    if request.purpose == "recommendation":
        for name, value in (("problem", request.problem_id and request.problem_type), ("profile_evidence", request.profile_evidence_ids),
                            ("problem_evidence", request.evidence_ids), ("scene", request.scene),
                            ("compatibility", request.agents), ("language", request.language)):
            if not value:
                response["gates"].append("missing_" + name)
        if response["gates"]:
            return response
    query_features = _query_features(request)
    text = query_text(request)
    with store.reader() as conn:
        index = store.index(conn)
        response["generation"] = index.generation
        mask = index.mask(request, conn)
        routes, passages = {}, {}
        routes["feature"], wanted = _features(index, mask, query_features, request.per_route)
        routes["lexical"], passages = _lexical(conn, index, mask, text, request.per_route, request.prefix)
        if routes["lexical"] is None:
            routes["lexical"] = []
            response["degraded"] = ["lexical:OperationalError"]
        if request.problem_type:
            friction = [Feature(feature="friction", value=request.problem_type)]
            routes["remedy"], _ = _features(index, mask, friction, request.per_route, curated_only=True)
        if encoder and (request.model_id is None or request.model_id == encoder.model_id) and text:
            model = conn.execute("SELECT * FROM embedding_model WHERE model_id=?", (encoder.model_id,)).fetchone()
            if model and model["descriptor"] != canonical_json(encoder.descriptor):
                raise ValueError("embedding_model_identity_conflict")
            if model:
                total = int(mask[index.embed_items].sum()) if len(index.embed_items) else 0
                routes["semantic"], semantic_passages, scanned = _semantic(conn, index, mask, encoder, text, request.per_route)
                passages.update({k: v for k, v in semantic_passages.items() if k not in passages})
                response["vector"] = {"status": "ready" if scanned == total else "partial", "model_id": encoder.model_id,
                                      "indexed_chunks": scanned, "eligible_chunks": total, "algorithm": "exact_cosine_fp16"}
            else:
                response["vector"] = {"status": "not_indexed", "model_id": encoder.model_id}
        elif request.model_id:
            response["vector"] = {"status": "model_not_loaded", "model_id": request.model_id}
        response["routes"] = {route: len(hits) for route, hits in routes.items()}
        response["items"] = _rank(store, conn, index, request, routes, passages, wanted, query_features)
    return response


def _rank(store, conn, index, request, routes, passage_rows, wanted, query_features):
    parts, fusion = defaultdict(dict), defaultdict(float)
    max_rrf = sum(ROUTE_WEIGHTS[r] / 61 for r, hits in routes.items() if hits)
    for route, hits in routes.items():
        for rank, (item_id, score) in enumerate(hits, 1):
            contribution = ROUTE_WEIGHTS[route] / (60 + rank)
            fusion[item_id] += contribution
            parts[item_id][route] = {"rank": rank, "raw_score": score, "rrf_contribution": contribution}
    if not fusion:
        return []
    ids = sorted(fusion)
    rows = {r["item_id"]: r for r in conn.execute("SELECT * FROM catalog_item WHERE item_id IN (SELECT value FROM json_each(?))",
                                                  (json.dumps(ids),))}
    query_weights = {}
    for f in query_features:
        query_weights[(f.feature, f.value)] = f.weight
    matched = _matched_features(conn, [i for i in ids if "feature" in parts[i]], wanted, query_weights)
    candidates = []
    for item_id in ids:
        row = rows.get(item_id)
        if row is None:  # Deleted between the index snapshot and this read.
            continue
        rrf = fusion[item_id]
        coverage = parts[item_id].get("feature", {}).get("raw_score", 0.0)
        quality = 1.0 if row["body_policy"] == "licensed" else 0.5
        risk = json.loads(row["risk"])
        penalty = min(0.1, len(risk) * 0.02)
        relevance = max(0.0, 0.75 * rrf / max_rrf + 0.15 * coverage + 0.1 * quality - penalty)
        position = index.pos.get(item_id)
        candidates.append({"item_id": item_id, "type": row["type"], "name": row["name"], "summary": row["summary"],
                           "url": row["url"], "agents": json.loads(row["agents"]), "license": row["license"],
                           "difficulty": row["difficulty"], "last_seen": row["last_seen"], "version_id": row["latest_version"],
                           "content_hash": row["content_hash"], "score": relevance, "score_parts": {"routes": parts[item_id],
                           "rrf_normalized": rrf / max_rrf, "feature_coverage": coverage, "content_quality": quality, "risk_penalty": penalty},
                           "matched_features": matched.get(item_id, []), "risk": risk, "risk_level": row["risk_level"],
                           "passage": passage_rows.get(item_id),
                           "evidence_ids": request.evidence_ids, "profile_evidence_ids": request.profile_evidence_ids,
                           "effect_status": "unmeasured",
                           "_keys": index.item_keys[position] if position is not None else frozenset()})
    selected = _mmr(candidates, request.limit)
    texts = _passages(store, conn, index, {item["item_id"]: item["passage"] for item in selected if item["passage"] is not None})
    for rank, item in enumerate(selected, 1):
        item.pop("_keys")
        item["passage"] = texts.get(item["item_id"])
        item["rank"] = rank
    return selected


def _similarity(left, right):
    if left["content_hash"] == right["content_hash"]:
        return 1.0
    a, b = left["_keys"], right["_keys"]
    return len(a & b) / len(a | b) if a | b else 0.0


def _mmr(candidates, limit):
    """Greedy MMR (0.8 relevance, 0.2 redundancy); max similarity is updated incrementally."""
    selected, seen_hashes = [], set()
    redundancy = {c["item_id"]: 0.0 for c in candidates}
    remaining = list(candidates)
    while remaining and len(selected) < limit:
        best = min(remaining, key=lambda c: (-(0.8 * c["score"] - 0.2 * redundancy[c["item_id"]]), c["item_id"]))
        remaining.remove(best)
        if best["content_hash"] in seen_hashes:
            continue
        best["diversity_score"] = 0.8 * best["score"] - 0.2 * redundancy[best["item_id"]]
        selected.append(best)
        seen_hashes.add(best["content_hash"])
        for c in remaining:
            redundancy[c["item_id"]] = max(redundancy[c["item_id"]], _similarity(c, best))
    return selected
