"""Word-level topic clusters for mixed Chinese/English session text.

Character n-grams over mixed text cluster on shared boilerplate and label clusters with
fragments ("er", "llab"). Here Chinese is segmented with the fixed jieba dictionary and
English kept as words (``products.lexical.sentences``), lines repeated across many
sessions are stripped as boilerplate, and clusters must pass a quality gate; otherwise
the result is ``insufficient`` rather than one giant cluster.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

import numpy as np

TOPIC_VERSION = "word-tfidf-topics-v1"
SMALL_N = 20  # below this, cosine DBSCAN keeps its noise semantics
BOILERPLATE_SHARE, BOILERPLATE_MIN_CHARS = 0.3, 12
MAX_K, GIANT_SHARE, MIN_SILHOUETTE, MIN_CLUSTER_SHARE = 12, 0.6, 0.05, 0.02
SVD_DIMS, SILHOUETTE_SAMPLE = 64, 2000
MIN_CLUSTERED_SHARE = 0.5  # most documents must land in a cluster, else topics are not shown
_NUMERIC = re.compile(r"^[\d_.+#-]+$")


def _line_key(line: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", line).casefold().split())


def strip_boilerplate(texts: list[str]) -> tuple[list[str], int]:
    """Drop long lines that occur in at least 30% (and 3) of the documents."""
    if len(texts) < SMALL_N:
        return texts, 0
    keys = [
        {k for line in text.splitlines() if len(k := _line_key(line)) >= BOILERPLATE_MIN_CHARS}
        for text in texts
    ]
    df = Counter(k for doc in keys for k in doc)
    limit = max(3, math.ceil(BOILERPLATE_SHARE * len(texts)))
    common = {k for k, n in df.items() if n >= limit}
    if not common:
        return texts, 0
    kept = []
    for text in texts:
        rest = "\n".join(line for line in text.splitlines() if _line_key(line) not in common)
        # A document that is only boilerplate (a repeated template) keeps its text.
        kept.append(rest if rest.strip() else text)
    return kept, len(common)


def words(text: str) -> list[str]:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    from ..products.lexical import sentences

    return [
        token
        for clause in sentences(text)
        for token in clause
        if token and token not in ENGLISH_STOP_WORDS and not _NUMERIC.match(token)
    ]


def _identity(doc):
    return doc


def _insufficient(n: int, reason: str, **extra) -> dict:
    return {
        "status": "insufficient",
        "reason": reason,
        "labels": [None] * n,
        "distances": [None] * n,
        "clusters": [],
        "top_terms": None,
        **extra,
    }


def topic_clusters(texts: list[str], *, eps: float = 0.35, min_samples: int = 2) -> dict:
    from sklearn.cluster import DBSCAN, KMeans
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import normalize

    n = len(texts)
    stripped, boilerplate_n = strip_boilerplate(texts)
    docs = [words(text) for text in stripped]
    small = n < SMALL_N
    meta = {"boilerplate_line_n": boilerplate_n, "method": "dbscan" if small else "kmeans"}
    try:
        tfidf = TfidfVectorizer(
            analyzer=_identity,
            min_df=1 if small else 2,
            max_df=1.0 if small else 0.5,
            sublinear_tf=True,
        )
        matrix = normalize(tfidf.fit_transform(docs))
    except ValueError:  # empty vocabulary after cleaning
        return _insufficient(n, "no_shared_vocabulary", **meta)
    terms = tfidf.get_feature_names_out()
    present = np.asarray(matrix.getnnz(axis=1) > 0)

    def top(indices: list[int]) -> list[dict]:
        weights = np.asarray(matrix[indices].mean(axis=0)).ravel()
        best = sorted(range(len(terms)), key=lambda i: (-weights[i], terms[i]))[:20]
        return [
            {"term": str(terms[i]), "weight": round(float(weights[i]), 6)}
            for i in best
            if weights[i] > 0
        ]

    silhouette = None
    if small:
        labels = DBSCAN(
            eps=eps, min_samples=min_samples, metric="cosine", algorithm="brute"
        ).fit_predict(matrix)
        labels = np.where(present, labels, -1)
        space = matrix.toarray()
    else:
        rows = np.flatnonzero(present)
        dims = min(SVD_DIMS, len(rows) - 1, len(terms) - 1)
        if len(rows) < SMALL_N or dims < 2:
            return _insufficient(n, "too_few_documents_with_vocabulary", **meta)
        space = np.zeros((n, dims))
        space[rows] = normalize(
            TruncatedSVD(n_components=dims, random_state=0).fit_transform(matrix[rows])
        )
        floor = max(2, math.ceil(MIN_CLUSTER_SHARE * len(rows)))
        best = None
        for k in range(2, min(MAX_K, len(rows) // 5) + 1):
            found = KMeans(n_clusters=k, n_init=4, random_state=0).fit_predict(space[rows])
            if np.bincount(found).max() > GIANT_SHARE * len(rows):
                continue
            score = float(
                silhouette_score(
                    space[rows],
                    found,
                    metric="cosine",
                    sample_size=min(len(rows), SILHOUETTE_SAMPLE),
                    random_state=0,
                )
            )
            if best is None or score > best[0]:
                best = (score, k, found)
        if best is None or best[0] < MIN_SILHOUETTE:
            return _insufficient(
                n,
                "no_partition_passes_quality_gate",
                silhouette=None if best is None else round(best[0], 4),
                **meta,
            )
        silhouette, _, found = best
        counts = np.bincount(found)
        labels = np.full(n, -1)
        labels[rows] = [label if counts[label] >= floor else -1 for label in found]
        if (labels >= 0).sum() < MIN_CLUSTERED_SHARE * n:
            return _insufficient(
                n, "most_documents_unclustered", silhouette=round(silhouette, 4), **meta
            )
        # Renumber by size so cluster ids are stable and dense.
        order = {
            old: new
            for new, old in enumerate(
                sorted(set(labels[labels >= 0]), key=lambda v: (-counts[v], v))
            )
        }
        labels = np.array([order.get(v, -1) for v in labels])
    distances = [None] * n
    clusters = []
    for label in sorted({int(v) for v in labels if v >= 0}):
        indices = [i for i, v in enumerate(labels) if v == label]
        centroid = normalize(space[indices].mean(axis=0).reshape(1, -1))[0]
        for i in indices:
            distances[i] = 1 - float(np.clip(space[i] @ centroid, -1, 1))
        clusters.append({"cluster_id": label, "size": len(indices), "top_terms": top(indices)})
    sizes = [c["size"] for c in clusters]
    return {
        "status": "available",
        "reason": None,
        "labels": [int(v) for v in labels],
        "distances": distances,
        "clusters": clusters,
        "top_terms": top(list(range(n))),
        "silhouette": None if silhouette is None else round(silhouette, 4),
        "largest_share": max(sizes) / n if sizes else None,
        **meta,
    }
