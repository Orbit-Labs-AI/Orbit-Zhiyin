"""Local unsupervised representation; no labels and no remote services."""

import warnings

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA, TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

VECTOR_VERSION = "char-tfidf-svd-v1"


class TextVectorizer:
    def fit(self, texts):
        self.tfidf = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), max_features=20_000,
                                     sublinear_tf=True, lowercase=True)
        matrix = self.tfidf.fit_transform(texts)
        dims = min(32, max(1, matrix.shape[0] - 1), matrix.shape[1] - 1)
        self.svd = TruncatedSVD(n_components=dims, random_state=0) if dims >= 1 else None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # identical documents have zero variance
            if self.svd:
                self.svd.fit(matrix)
        return self

    def transform(self, texts):
        matrix = self.tfidf.transform(texts)
        return normalize(self.svd.transform(matrix) if self.svd else matrix.toarray())


def temporal_novelty(entities):
    """Fit each representation using strictly earlier entities only, including IDF/SVD.

    Equal timestamps are peers, never a fabricated causal ordering. The full-corpus
    visualization representation must not be reused for a temporal claim.
    """
    out = {}
    for e in entities:
        earlier = [p for p in entities if p.get("ts") is not None and e.get("ts") is not None and p["ts"] < e["ts"]]
        if not earlier:
            out[e["entity_id"]] = {"novelty": None, "earlier_n": 0, "reason": "missing_timestamp" if e.get("ts") is None else "no_earlier_entity"}
            continue
        model = TextVectorizer().fit([p["text"] for p in earlier])
        vector = model.transform([e["text"]])
        previous = model.transform([p["text"] for p in earlier])
        similarity = float(np.max(previous @ vector[0]))
        out[e["entity_id"]] = {"novelty": 1 - float(np.clip(similarity, 0, 1)),
                               "earlier_n": len(earlier), "reason": None}
    return out


def representation(entities, eps=.35, min_samples=2):
    entities = sorted((e for e in entities if len(e.get("text", "").strip()) >= 2), key=lambda e: e["entity_id"])
    base = {"vectorizer_version": VECTOR_VERSION, "unit": "main_session",
            "parameters": {"ngram_range": [2, 4], "max_features": 20_000, "svd_max_dimensions": 32,
                           "random_state": 0, "dbscan_cosine_eps": eps, "dbscan_min_samples": min_samples},
            "effective_n": len(entities), "axes_meaning": "visualization only",
            "novelty_basis": "strictly earlier session text; prefix-only TF-IDF/SVD fit; no equal-time peers"}
    if not entities:
        return {**base, "status": "insufficient_samples", "clustering": {"status": "insufficient_samples"},
                "top_terms": None, "clusters": None, "coordinates": None}
    model = TextVectorizer().fit([e["text"] for e in entities])
    vectors = model.transform([e["text"] for e in entities])
    matrix = model.tfidf.transform([e["text"] for e in entities])
    terms = model.tfidf.get_feature_names_out()
    def top(indices):
        weights = np.asarray(matrix[indices].mean(axis=0)).ravel()
        best = sorted(range(len(terms)), key=lambda i: (-weights[i], terms[i]))[:20]
        return [{"term": str(terms[i]), "weight": round(float(weights[i]), 6)} for i in best if weights[i] > 0]
    enough = len(entities) >= 4
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine", algorithm="brute").fit_predict(vectors) if enough else [None] * len(entities)
    coords = np.zeros((len(entities), 2))
    if len(entities) > 1 and vectors.shape[1] > 1 and np.var(vectors, axis=0).sum() > 1e-12:
        coords = PCA(n_components=2, svd_solver="full").fit_transform(vectors)
    novelty = temporal_novelty(entities)
    clusters = []
    for label in sorted({int(v) for v in labels if v is not None and v >= 0}):
        indices = [i for i, value in enumerate(labels) if value == label]
        centroid = normalize(vectors[indices].mean(axis=0).reshape(1, -1))[0]
        clusters.append({"cluster_id": label, "size": len(indices), "top_terms": top(indices),
                         "entity_ids": [entities[i]["entity_id"] for i in indices]})
        for i in indices:
            entities[i]["distance_to_cluster_centroid"] = 1 - float(np.clip(vectors[i] @ centroid, -1, 1))
    return {**base, "status": "available", "clustering": {"status": "available" if enough else "insufficient_samples",
            "cluster_count": len(clusters) if enough else None,
            "noise_count": int(sum(v == -1 for v in labels)) if enough else None},
            "top_terms": top(list(range(len(entities)))), "clusters": clusters if enough else None,
            "coordinates": [{"entity_id": e["entity_id"], "cluster_id": int(labels[i]) if labels[i] is not None else None,
                 "embedding_x": float(coords[i, 0]), "embedding_y": float(coords[i, 1]),
                 "distance_to_cluster_centroid": e.get("distance_to_cluster_centroid"),
                 **novelty[e["entity_id"]]} for i, e in enumerate(entities)]}
