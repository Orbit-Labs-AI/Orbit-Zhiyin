"""Filter first, independent recall routes, RRF, transparent reranking and diversity."""

import json
from collections import defaultdict

import numpy as np

from .contracts import Feature, MatchRequest, Resource, canonical_json
from .features import extract, lexical_tokens
from .vectors import normalize_vectors

RANKING_VERSION = "hybrid-rrf60-mmr80-v1"
ROUTE_WEIGHTS = {"remedy": 1.5, "feature": 1.2, "lexical": 1.0, "semantic": 1.0}


def eligibility(request: MatchRequest) -> tuple[str, list]:
    terms = ["i.status='active'", "i.difficulty<=?",
             "EXISTS(SELECT 1 FROM item_source s JOIN catalog_source cs USING(source_id) "
             "WHERE s.item_id=i.item_id AND s.status='active' AND cs.enabled=1)"]
    args = [request.max_difficulty]
    for values, expression in ((request.types, "i.type IN"), (request.excluded_ids, "i.item_id NOT IN")):
        if values:
            terms.append(expression + " (SELECT value FROM json_each(?))")
            args.append(canonical_json(values))
    if request.source_ids:
        terms.append("EXISTS(SELECT 1 FROM item_source s JOIN catalog_source cs USING(source_id) WHERE s.item_id=i.item_id "
                     "AND s.status='active' AND cs.enabled=1 AND s.source_id IN (SELECT value FROM json_each(?)))")
        args.append(canonical_json(request.source_ids))
    if request.agents:
        compatibility = "EXISTS(SELECT 1 FROM json_each(i.agents) WHERE value IN (SELECT value FROM json_each(?)))"
        if request.purpose == "library":
            compatibility = "(" + compatibility + " OR json_array_length(i.agents)=0)"
        terms.append(compatibility)
        args.append(canonical_json(request.agents))
    if request.language:
        terms.append("i.language='any' OR i.language IN (SELECT value FROM json_each(?))")
        args.append(canonical_json(request.language.split("_or_")))
    if request.purpose == "recommendation":
        terms.extend([
            "EXISTS(SELECT 1 FROM item_feature f WHERE f.item_id=i.item_id AND f.feature='friction' AND f.value=? AND f.origin='curated')",
            "EXISTS(SELECT 1 FROM item_feature f WHERE f.item_id=i.item_id AND f.feature='scene' AND f.value=? AND f.origin='curated')",
            "EXISTS(SELECT 1 FROM item_feature f WHERE f.item_id=i.item_id AND f.feature='dimension' AND f.origin='curated' "
            "AND f.value IN (SELECT value FROM json_each(?)))",
            "json_extract(i.metadata,'$.metadata.verification') IN ('repository_and_skill_read','repository_and_source_read')",
        ])
        args.extend([request.problem_type, request.scene,
                     canonical_json([f.value for f in request.features if f.feature == "dimension"])])
    return " AND ".join("(" + term + ")" for term in terms), args


def _lexical(conn, where, args, text, limit):
    tokens = list(dict.fromkeys(lexical_tokens(text)))[:80]
    if not tokens:
        return [], {}
    match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
    rows = conn.execute("SELECT c.*,bm25(chunk_fts,0,0,3,1) AS lexical_score FROM chunk_fts "
                        "JOIN resource_chunk c ON c.chunk_id=chunk_fts.chunk_id JOIN catalog_item i ON i.item_id=c.item_id "
                        "WHERE chunk_fts MATCH ? AND " + where + " ORDER BY lexical_score,c.chunk_id", [match, *args])
    hits, passages = [], {}
    for row in rows:
        if row["item_id"] in passages:
            continue
        hits.append((row["item_id"], -row["lexical_score"]))
        passages[row["item_id"]] = dict(row)
        if len(hits) >= limit:
            break
    return hits, passages


def _features(conn, where, args, features, limit):
    if not features:
        return [], {}
    wanted = {(f.feature, f.value): f.weight for f in features}
    query = canonical_json([{"feature": k, "value": v, "weight": weight} for (k, v), weight in wanted.items()])
    rows = conn.execute("SELECT f.*,json_extract(q.value,'$.weight') AS query_weight FROM item_feature f "
                        "JOIN catalog_item i USING(item_id) JOIN json_each(?) q "
                        "ON f.feature=json_extract(q.value,'$.feature') AND f.value=json_extract(q.value,'$.value') "
                        "WHERE " + where, [query, *args]).fetchall()
    matched = defaultdict(dict)
    for row in rows:
        key = row["feature"], row["value"]
        old = matched[row["item_id"]].get(key)
        if old is None or row["weight"] > old["weight"] or row["origin"] == "curated":
            matched[row["item_id"]][key] = dict(row)
    denominator = sum(wanted.values())
    scores = {key: sum(min(1, row["weight"]) * row["query_weight"] for row in values.values()) / denominator
              for key, values in matched.items()}
    hits = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return hits, {key: list(values.values()) for key, values in matched.items()}


def _semantic(conn, where, args, encoder, text, limit):
    query = normalize_vectors(encoder.encode([text], query=True), 1, encoder.dimensions)[0]
    rows = conn.execute("SELECT c.*,e.vector,e.dimensions FROM chunk_embedding e "
                        "JOIN resource_chunk c USING(chunk_id) JOIN catalog_item i ON i.item_id=c.item_id "
                        "WHERE e.model_id=? AND " + where, [encoder.model_id, *args])
    best, passages, scanned = {}, {}, 0
    while batch := rows.fetchmany(256):
        vectors = np.stack([np.frombuffer(row["vector"], dtype="<f4") for row in batch])
        if vectors.shape[1] != encoder.dimensions or not np.isfinite(vectors).all():
            raise ValueError("corrupt_vector_index")
        # Avoid platform BLAS floating-point flag leakage; accumulation also stays stable.
        scores = np.einsum("ij,j->i", vectors, query, dtype=np.float64)
        if not np.isfinite(scores).all():
            raise ValueError("invalid_cosine_scores")
        scores = np.clip(scores, -1, 1)
        scanned += len(batch)
        for row, score in zip(batch, scores, strict=True):
            item_id, score = row["item_id"], float(score)
            if score > 0 and score > best.get(item_id, float("-inf")):
                best[item_id] = score
                passages[item_id] = {k: row[k] for k in row.keys() if k != "vector"}
    hits = sorted(best.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return hits, {key: passages[key] for key, _ in hits}, scanned


def _similarity(left, right):
    if left["content_hash"] == right["content_hash"]:
        return 1.0
    a, b = left["feature_keys"], right["feature_keys"]
    return len(a & b) / len(a | b) if a | b else 0.0


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
    query_features = list(request.features)
    if request.text:
        query_features += extract(Resource(item_id="query", type="guide", name="query", summary=request.text, url=""))
    if request.problem_type:
        query_features.append(Feature(feature="friction", value=request.problem_type))
    text = request.text or " ".join(f.value for f in query_features)
    where, args = eligibility(request)
    with store.connect(True) as conn:
        response["generation"] = int(conn.execute("SELECT value FROM catalog_meta WHERE key='generation'").fetchone()[0])
        routes, passages = {}, {}
        routes["feature"], matched = _features(conn, where, args, query_features, request.per_route)
        routes["lexical"], lexical_passages = _lexical(conn, where, args, text, request.per_route)
        passages.update(lexical_passages)
        if request.problem_type:
            friction = [Feature(feature="friction", value=request.problem_type)]
            routes["remedy"], _ = _features(conn, where + " AND f.origin='curated'", args, friction, request.per_route)
        if encoder and (request.model_id is None or request.model_id == encoder.model_id) and text:
            model = conn.execute("SELECT * FROM embedding_model WHERE model_id=?", (encoder.model_id,)).fetchone()
            if model and model["descriptor"] != canonical_json(encoder.descriptor):
                raise ValueError("embedding_model_identity_conflict")
            if model:
                total = conn.execute("SELECT count(*) FROM resource_chunk c JOIN catalog_item i USING(item_id) WHERE " + where, args).fetchone()[0]
                routes["semantic"], semantic_passages, scanned = _semantic(conn, where, args, encoder, text, request.per_route)
                passages.update(semantic_passages)
                response["vector"] = {"status": "ready" if scanned == total else "partial", "model_id": encoder.model_id,
                                      "indexed_chunks": scanned, "eligible_chunks": total, "algorithm": "exact_cosine"}
            else:
                response["vector"] = {"status": "not_indexed", "model_id": encoder.model_id}
        elif request.model_id:
            response["vector"] = {"status": "model_not_loaded", "model_id": request.model_id}
        response["routes"] = {route: len(hits) for route, hits in routes.items()}
        parts, fusion = defaultdict(dict), defaultdict(float)
        max_rrf = sum(ROUTE_WEIGHTS[r] / 61 for r, hits in routes.items() if hits)
        for route, hits in routes.items():
            for rank, (item_id, score) in enumerate(hits, 1):
                contribution = ROUTE_WEIGHTS[route] / (60 + rank)
                fusion[item_id] += contribution
                parts[item_id][route] = {"rank": rank, "raw_score": score, "rrf_contribution": contribution}
        candidates = []
        for item_id, rrf in fusion.items():
            row = conn.execute("SELECT * FROM catalog_item WHERE item_id=?", (item_id,)).fetchone()
            metadata = json.loads(row["metadata"])
            all_features = conn.execute("SELECT * FROM item_feature WHERE item_id=?", (item_id,)).fetchall()
            coverage = parts[item_id].get("feature", {}).get("raw_score", 0.0)
            quality = 1.0 if metadata["body_policy"] == "licensed" else 0.5
            risk = min(0.1, len(metadata["risk"]) * 0.02)
            relevance = max(0.0, 0.75 * rrf / max_rrf + 0.15 * coverage + 0.1 * quality - risk)
            passage = passages.get(item_id)
            candidates.append({"item_id": item_id, "type": row["type"], "name": row["name"], "summary": row["summary"],
                               "url": row["url"], "agents": json.loads(row["agents"]), "license": row["license"],
                               "difficulty": row["difficulty"], "last_seen": row["last_seen"], "version_id": row["latest_version"],
                               "content_hash": row["content_hash"], "score": relevance, "score_parts": {"routes": parts[item_id],
                               "rrf_normalized": rrf / max_rrf, "feature_coverage": coverage, "content_quality": quality, "risk_penalty": risk},
                               "matched_features": matched.get(item_id, []), "risk": metadata["risk"],
                               "passage": {k: passage[k] for k in ("chunk_id", "field", "heading", "text", "start")} if passage else None,
                               "evidence_ids": request.evidence_ids, "profile_evidence_ids": request.profile_evidence_ids,
                               "effect_status": "unmeasured", "feature_keys": {(f["feature"], f["value"]) for f in all_features}})
        selected, seen_hashes = [], set()
        while candidates and len(selected) < request.limit:
            def mmr(candidate):
                similarity = max((_similarity(candidate, old) for old in selected), default=0)
                return 0.8 * candidate["score"] - 0.2 * similarity
            candidates.sort(key=lambda c: (-mmr(c), c["item_id"]))
            candidate = candidates.pop(0)
            if candidate["content_hash"] in seen_hashes:
                continue
            candidate["diversity_score"] = mmr(candidate)
            selected.append(candidate)
            seen_hashes.add(candidate["content_hash"])
        for rank, item in enumerate(selected, 1):
            item.pop("feature_keys")
            item["rank"] = rank
        response["items"] = selected
    return response
