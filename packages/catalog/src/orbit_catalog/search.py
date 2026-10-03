"""Filter first, independent recall routes, RRF, transparent reranking and diversity.

Eligibility is a boolean mask from the in-memory index; the lexical route asks FTS5 for
the top-K chunks once (K doubles only when the mask leaves too few items) and the
semantic route scans an fp16 matrix exactly.
"""

import json
import math
import re
import sqlite3
import threading
from collections import OrderedDict, defaultdict

import numpy as np

from .contracts import Feature, MatchRequest, canonical_json
from .features import VOCABULARY, lexical_tokens
from .quality import assess as assess_quality
from .vectors import blocked_scores, normalize_vectors

RANKING_VERSION = "hybrid-bm25f-abs-mmr80-v5"
ROUTE_WEIGHTS = {"remedy": 1.5, "feature": 1.2, "lexical": 1.0, "semantic": 2.0}
# Han function words, Lucene's EnglishAnalyzer default stop set (a an and are as at be but by for
# if in into is it no not of on or such that the their then there these they this to was will with),
# plus conversational query filler (pronouns, question words, modal verbs, "help" mirroring 帮助).
STOP_WORDS = set("的 和 为 是 在 与 及 了 把 中 从 到 用 做 对 将 并 要 如何 是否 以及 进行 帮助 我 你 我们 怎么 一下 "
                 "a an and are as at be but by for if in into is it no not of on or such that the their then there "
                 "these they this to was will with i me my you your we our its those how what why when which who "
                 "do does did can could should would please help best tool tools".split())
# Han query words -> English phrases. Generated from features.VOCABULARY (every Han word of a
# key expands to the Latin words of the same key), plus query-only aliases that are not
# extraction features. Expansions only add lexical alternatives; they never become features.
EXTRA_ALIASES = {
    "排错": ("debugging", "troubleshooting"), "无障碍": ("accessibility", "a11y"), "网页": ("web", "website"),
    "键盘": ("keyboard",), "优化": ("optimization", "optimize"), "代码": ("code",), "审查": ("review",),
    "测试用例": ("test case", "unit test"), "图表": ("chart", "visualization"), "可视化": ("visualization",),
    "笔记": ("notes", "notebook"), "爬虫": ("scraping", "crawler"), "邮件": ("email",), "支付": ("payment", "payments"),
    "搜索": ("search",), "自动化": ("automation",), "截图": ("screenshot",), "视频": ("video",),
    "图片": ("image",), "演示": ("presentation", "slides"), "脚本": ("script",), "命令行": ("cli", "command line"),
}
HAN_EXPANSIONS: dict[str, set[str]] = {}
for _words in VOCABULARY.values():
    _latin = {w for w in _words if w.isascii()}
    for _word in _words:
        if not _word.isascii() and _latin:
            HAN_EXPANSIONS.setdefault(_word, set()).update(_latin)
for _word, _phrases in EXTRA_ALIASES.items():
    HAN_EXPANSIONS.setdefault(_word, set()).update(_phrases)
HAN_WORDS_BY_LENGTH = sorted(HAN_EXPANSIONS, key=lambda w: (-len(w), w))  # longest match first
MAX_TOKENS = 24
# BM25 parameters. k1=1.2 is the standard default (Robertson & Zaragoza 2009, "The Probabilistic
# Relevance Framework: BM25 and Beyond", §3.4: k1 in [1.2, 2.0]). b=0 (no length normalisation):
# documents are chunks already windowed to <=1200 characters (features.chunks), the passage-level
# alternative to length normalisation, and resource_chunk stores no token counts to normalise by.
LEXICAL_K1 = 1.2
# BM25F field weight of the resource name over the chunk text; same 4:1 ratio the original
# bm25(chunk_fts, 4.0, 1.0) call asked for. A name hit alone saturates to 4/(1.2+4)=0.77.
TITLE_WEIGHT = 4.0
# multilingual-e5 cosine scores concentrate in [0.7, 1.0] because of the 0.01 InfoNCE temperature
# (intfloat/multilingual-e5-small model card, FAQ 3); below 0.7 carries no relevance signal.
SEMANTIC_FLOOR = 0.7
# Free-text hits below this absolute strength are dropped unless a structured feature also hit.
# Calibrated on the bundled 1277-item seed (see tests/test_retrieval.py golden set): a query of
# generic words ("use the file") peaks at 0.14, single rare-term body hits sit at >= 0.25.
MIN_TEXT_RELEVANCE = 0.2
# Pseudo-chunks without the term added to N (an additive prior on document frequency). A small
# catalog (a local-only library, a fresh install before the seed) has too few chunks for df to
# separate "generic" from "shared by these few items"; with the bundled seed (7.9k chunks) the
# prior changes idf by < 0.15 nats for every df, so large-library ranking is unaffected.
IDF_PRIOR_DOCS = 1000
# Items rescored with exact term counts (chunk text is recomputed, ~1 ms per cached item).
RERANK = 40
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


Term = tuple[str, bool]  # (token, is_prefix)


def query_concepts(text: str, prefix: bool = False) -> list[list[list[Term]]]:
    """The query as concepts; each concept is a list of alternative token sequences.

    A Latin word is a concept with one alternative. A Han word from ``HAN_EXPANSIONS`` is one
    concept whose alternatives are its own bigrams and each English phrase it expands to, so
    "代码审查" scores as well as an item that says "code review" and expansion size does not
    dilute the score. Remaining Han text keeps the bigram tokens of ``lexical_tokens``.
    """
    concepts, seen = [], set()

    def add(alternatives):
        alternatives = [[(t, False) for t in alt if t not in STOP_WORDS] for alt in alternatives]
        alternatives = [alt for alt in alternatives if alt]
        key = tuple(tuple(alt) for alt in alternatives)
        if alternatives and key not in seen:
            seen.add(key)
            concepts.append(alternatives)

    rest = text
    for word in HAN_WORDS_BY_LENGTH:
        if word in rest:
            add([lexical_tokens(word)] + [lexical_tokens(phrase) for phrase in sorted(HAN_EXPANSIONS[word])])
            rest = rest.replace(word, " ")
    own = [t for t in dict.fromkeys(lexical_tokens(rest)) if t not in STOP_WORDS]
    stem = next((t for t in reversed(own) if len(t) >= 3 and t.isascii()), None) if prefix else None
    for token in own:
        add([[token]])
    if stem:
        concepts = [[[(t, t == stem) for t, _ in alt] for alt in concept] for concept in concepts]
    budget, capped = MAX_TOKENS, []
    for concept in concepts:  # Keep whole concepts within the token budget.
        size = sum(len(alt) for alt in concept)
        if size > budget and capped:
            break
        capped.append(concept)
        budget -= size
    return capped


def query_terms(text: str, prefix: bool = False) -> list[Term]:
    """Distinct (token, is_prefix) pairs of all concepts, in query order."""
    return list(dict.fromkeys(t for concept in query_concepts(text, prefix) for alt in concept for t in alt))


def _fts_term(token: str, is_prefix: bool) -> str:
    return '"' + token.replace('"', '""') + '"' + ("*" if is_prefix else "")


def match_expression(text: str, prefix: bool = False) -> str | None:
    terms = query_terms(text, prefix)
    return " OR ".join(_fts_term(t, p) for t, p in terms) if terms else None


def idf(n_docs: int, df: int) -> float:
    """BM25 idf with the +1 inside the log (Lucene form), never negative for common terms."""
    return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))


def _tf(tokens: list[str], term: str, is_prefix: bool) -> int:
    return sum(1 for t in tokens if t.startswith(term)) if is_prefix else tokens.count(term)


def _concept_score(concepts, weights, tf) -> float:
    """Σ_concepts max_alternatives mean_t idf(t)·tf~/(k1+tf~); tf(term) -> tf~ (title-weighted)."""
    total = 0.0
    for concept in concepts:
        best = 0.0
        for alt in concept:
            value = 0.0
            for term in alt:
                if term in weights:
                    count = tf(term)
                    value += weights[term] * count / (LEXICAL_K1 + count)
            best = max(best, value / len(alt))
        total += best
    return total


def _lexical(store, conn, index, mask, text, limit, prefix):
    """BM25F over chunks: FTS5 recalls the candidate set, ranking is computed here.

    ``chunk_fts`` is ``detail=column``, where SQLite's ``bm25()`` has no term positions and
    returns 0 for every row, so FTS order collapsed to rowid. Here FTS only answers "which
    chunks contain t" (per column) which yields df(t); scoring is BM25F (Robertson & Zaragoza
    2009) with b=0 over query concepts (see ``query_concepts``):
      raw = Σ_c max_alt mean_t idf(t) · tf~/(k1 + tf~),  tf~ = TITLE_WEIGHT·tf_title + tf_body.
    Stage 1 assumes tf=1 per field that contains t; the best ``RERANK`` items are rescored
    with exact term counts recomputed from ``store.chunk_texts`` (the FTS table is contentless).
    The absolute score divides by the best case of the same sum: every concept that occurs in
    the corpus at all, matched by a df=1 term with tf→∞. It depends only on the item and the
    corpus, not on which other items happened to be candidates.
    """
    concepts = query_concepts(text, prefix)
    if not concepts:
        return [], {}
    n_docs = int((index.chunk_item >= 0).sum()) + IDF_PRIOR_DOCS
    body_hits, title_hits, weights = defaultdict(set), defaultdict(set), {}
    try:
        for term in dict.fromkeys(t for concept in concepts for alt in concept for t in alt):
            fts = _fts_term(*term)
            rows = [r[0] for r in conn.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?", (fts,))]
            if not rows:
                continue  # Out-of-vocabulary tokens (typos, CJK filler bigrams) say nothing about any item.
            weights[term] = idf(n_docs, len(rows))
            titled = {r[0] for r in conn.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?",
                                                 ("{title} : " + fts,))}
            for rowid in titled:
                title_hits[rowid].add(term)
            # Title and content share one FTS row: a titled row may or may not also hold t in its
            # text, so stage 1 counts it as a title hit only; stage 2 recounts both fields.
            for rowid in rows:
                if rowid not in titled:
                    body_hits[rowid].add(term)
    except sqlite3.OperationalError:
        # An FTS syntax edge must cost only this route, not the feature/remedy/semantic recall.
        return None, {}
    live = [c for c in concepts if any(t in weights for alt in c for t in alt)]
    if not live:
        return [], {}
    ceiling = idf(n_docs, 1) * len(live)
    rowids = np.fromiter(set(body_hits) | set(title_hits), dtype=np.int64)
    owners = index.items_of(rowids).tolist()
    # The name is a field of the item, not of one chunk: FTS stores it on ordinal 0 only, so
    # collect title terms per item first and pair them with every candidate passage.
    item_title = defaultdict(set)
    for rowid, owner in zip(rowids.tolist(), owners, strict=True):
        if rowid in title_hits and owner >= 0:
            item_title[owner] |= title_hits[rowid]
    best = {}
    for rowid, owner in zip(rowids.tolist(), owners, strict=True):
        if owner < 0 or not mask[owner]:
            continue
        titled, body = item_title.get(owner, set()), body_hits.get(rowid, set())
        raw = _concept_score(live, weights, lambda t, titled=titled, body=body:
                             (TITLE_WEIGHT if t in titled else 0) + (1 if t in body else 0))
        item_id = index.ids[owner]
        if item_id not in best or (raw, -rowid) > (best[item_id][0], -best[item_id][1]):
            best[item_id] = (raw, rowid)
    ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))[:max(limit, RERANK)]
    rescored = []
    for position, (item_id, (raw, rowid)) in enumerate(ranked):
        if position < RERANK:
            raw = _exact_bm25(store, conn, index, item_id, rowid, live, weights) or raw
        rescored.append((item_id, raw, rowid))
    rescored.sort(key=lambda r: (-r[1], r[0]))
    hits = [(item_id, raw / ceiling) for item_id, raw, _ in rescored[:limit]]
    return hits, {item_id: rowid for item_id, _, rowid in rescored[:limit]}


def _exact_bm25(store, conn, index, item_id, rowid, concepts, weights) -> float | None:
    ordinal = int(index.chunk_ordinal[rowid]) if 0 <= rowid < len(index.chunk_ordinal) else -1
    texts = store.chunk_texts(conn, item_id)
    if not 0 <= ordinal < len(texts):
        return None
    row = conn.execute("SELECT name FROM catalog_item WHERE item_id=?", (item_id,)).fetchone()
    title = lexical_tokens(row["name"]) if row is not None else []
    body = lexical_tokens(texts[ordinal])
    return _concept_score(concepts, weights, lambda t: TITLE_WEIGHT * _tf(title, *t) + _tf(body, *t))


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
        routes["lexical"], passages = _lexical(store, conn, index, mask, text, request.per_route, request.prefix)
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


def route_strength(route: str, raw: float) -> float:
    """Absolute [0, 1] evidence of one route; never relative to the other candidates.

    lexical: BM25F over its query ceiling (see ``_lexical``). feature / remedy: weighted share
    of the requested features the item carries (Σ w·min(1, weight) / Σ w). semantic: cosine
    rescaled from SEMANTIC_FLOOR to 1.
    """
    if route == "semantic":
        return min(1.0, max(0.0, (raw - SEMANTIC_FLOOR) / (1 - SEMANTIC_FLOOR)))
    return min(1.0, max(0.0, raw))


def _rank(store, conn, index, request, routes, passage_rows, wanted, query_features):
    parts, fusion = defaultdict(dict), defaultdict(float)
    for route, hits in routes.items():
        for rank, (item_id, score) in enumerate(hits, 1):
            contribution = ROUTE_WEIGHTS[route] / (60 + rank)
            fusion[item_id] += contribution
            parts[item_id][route] = {"rank": rank, "raw_score": score, "strength": route_strength(route, score),
                                     "rrf_contribution": contribution}
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
        strengths = {route: part["strength"] for route, part in parts[item_id].items()}
        structured = strengths.get("feature", 0.0) > 0 or strengths.get("remedy", 0.0) > 0
        text = max(strengths.get("lexical", 0.0), strengths.get("semantic", 0.0))
        if not structured and text < MIN_TEXT_RELEVANCE:
            continue  # A weak free-text hit is noise, not a low-ranked answer.
        # Noisy-OR: independent routes agreeing raise confidence; one strong route suffices.
        evidence = 1.0 - math.prod(1.0 - v for v in strengths.values())
        coverage = parts[item_id].get("feature", {}).get("raw_score", 0.0)
        quality_report = assess_quality(row)
        quality = quality_report["score"]
        risk = json.loads(row["risk"])
        penalty = min(0.1, len(risk) * 0.02)
        # Content quality scales the evidence (metadata-only rows lose up to 5%) but never creates it.
        relevance = max(0.0, evidence * (0.9 + 0.1 * quality) - penalty)
        candidates.append({"item_id": item_id, "type": row["type"], "name": row["name"], "summary": row["summary"],
                           "url": row["url"], "agents": json.loads(row["agents"]), "license": row["license"],
                           "difficulty": row["difficulty"], "last_seen": row["last_seen"], "version_id": row["latest_version"],
                           "verification": row["verification"], "language": row["language"],
                           "support": (json.loads(row["metadata"]).get("metadata") or {}).get("agent_support") or {},
                           "quality": quality_report,
                           "content_hash": row["content_hash"], "score": relevance, "score_parts": {"routes": parts[item_id],
                           "evidence": evidence, "rrf": fusion[item_id], "feature_coverage": coverage,
                           "content_quality": quality, "risk_penalty": penalty},
                           "matched_features": matched.get(item_id, []), "risk": risk, "risk_level": row["risk_level"],
                           "passage": passage_rows.get(item_id),
                           "evidence_ids": request.evidence_ids, "profile_evidence_ids": request.profile_evidence_ids,
                           "effect_status": "unmeasured",
                           "_keys": redundancy_keys(row)})
    selected = _mmr(candidates, request.limit)
    texts = _passages(store, conn, index, {item["item_id"]: item["passage"] for item in selected if item["passage"] is not None})
    for rank, item in enumerate(selected, 1):
        item.pop("_keys")
        item["passage"] = texts.get(item["item_id"])
        item["rank"] = rank
    return selected


def redundancy_keys(row) -> frozenset:
    """What makes two results near-duplicates: same name, same repository, same kind.

    Agent and topic features are deliberately absent: two Claude Code skills on different topics
    are not redundant, and every result of a "pdf" query shares the pdf feature.
    """
    url = row["url"] or ""
    repo = re.match(r"https?://(?:www\.)?github\.com/([^/]+/[^/#?]+)", url, re.I)
    return frozenset({("name", row["name_key"]), ("repo", repo.group(1).lower().removesuffix(".git") if repo else url),
                      ("type", row["type"])})


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
        best = min(remaining, key=lambda c: (-(0.8 * c["score"] - 0.2 * redundancy[c["item_id"]]),
                                               -c["score_parts"]["rrf"], c["item_id"]))
        remaining.remove(best)
        if best["content_hash"] in seen_hashes:
            continue
        best["diversity_score"] = 0.8 * best["score"] - 0.2 * redundancy[best["item_id"]]
        selected.append(best)
        seen_hashes.add(best["content_hash"])
        for c in remaining:
            redundancy[c["item_id"]] = max(redundancy[c["item_id"]], _similarity(c, best))
    return selected
