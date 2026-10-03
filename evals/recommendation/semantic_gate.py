"""Semantic-route gate on a constructed cosine population (no model, no user data).

The population reproduces the per-query cosine distributions measured with the int8
multilingual-e5-small on the bundled seed (docs/modules/catalog/validation.md, "余弦分布与语义路阈值"):
for each of the 6 queries, unrelated items ~ Normal(P50, (P95-P5)/3.29) and related items likewise
from their own P5/P50/P95. It compares the old absolute gate (cosine rescaled from SEMANTIC_FLOOR,
kept when strength >= MIN_TEXT_RELEVANCE, i.e. cos >= 0.76) with the shipped per-query
``search.semantic_gate``. Absolute numbers depend on the constructed population; the comparison
is what it measures. Real-model numbers stay in validation.md.

    uv run python -m evals.recommendation.semantic_gate
"""

import json

import numpy as np

from orbit_catalog.search import MIN_TEXT_RELEVANCE, SEMANTIC_FLOOR, semantic_gate

# query: (related n, related P5/P50/P95, unrelated P5/P50/P95); unrelated n = 7744 / 6 per query.
MEASURED = {
    "调试测试反复失败": (25, (0.786, 0.809, 0.888), (0.752, 0.788, 0.833)),
    "postgres database": (28, (0.819, 0.852, 0.888), (0.768, 0.795, 0.819)),
    "pdf docx": (22, (0.807, 0.830, 0.853), (0.774, 0.799, 0.829)),
    "代码审查": (43, (0.809, 0.837, 0.858), (0.777, 0.804, 0.833)),
    "浏览器自动化测试": (6, (0.810, 0.834, 0.845), (0.767, 0.800, 0.835)),
    "deploy to kubernetes": (4, (0.863, 0.872, 0.878), (0.786, 0.818, 0.843)),
}
UNRELATED_PER_QUERY = 7744 // 6


def _draw(rng, n, quantiles):
    p5, p50, p95 = quantiles
    return np.clip(rng.normal(p50, (p95 - p5) / 3.29, n), -1, 1).astype(np.float32)


def auc(positive, negative) -> float:
    """Mann-Whitney AUC with ties counted half."""
    values = np.concatenate([positive, negative])
    order = values.argsort(kind="stable")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(1, len(values) + 1)
    for value in np.unique(values):  # average ranks of ties
        tied = values == value
        ranks[tied] = ranks[tied].mean()
    return float((ranks[:len(positive)].sum() - len(positive) * (len(positive) + 1) / 2) / (len(positive) * len(negative)))


def evaluate(seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    old = {"related": [], "unrelated": []}
    new = {"related": [], "unrelated": []}
    for n_related, related_q, unrelated_q in MEASURED.values():
        related = _draw(rng, n_related, related_q)
        unrelated = _draw(rng, UNRELATED_PER_QUERY, unrelated_q)
        scores = np.concatenate([related, unrelated])
        labels = np.arange(len(scores)) < n_related
        old_strength = np.clip((scores - SEMANTIC_FLOOR) / (1 - SEMANTIC_FLOOR), 0, 1)
        old_keep = (scores > 0) & (old_strength >= MIN_TEXT_RELEVANCE)
        keep, strength, standardised = semantic_gate(scores, np.ones(len(scores), dtype=bool))
        assert standardised
        z = (scores - np.median(scores)) / scores.std()
        for bucket, mask in (("related", labels), ("unrelated", ~labels)):
            old[bucket].append((old_keep[mask], scores[mask]))
            new[bucket].append((keep[mask], z[mask]))

    def summary(groups):
        kept = {b: float(np.concatenate([k for k, _ in g]).mean()) for b, g in groups.items()}
        ranking = auc(np.concatenate([s for _, s in groups["related"]]), np.concatenate([s for _, s in groups["unrelated"]]))
        return {"related_kept": round(kept["related"], 3), "unrelated_kept": round(kept["unrelated"], 3),
                "pooled_auc": round(ranking, 3)}

    return {"population": "constructed from validation.md quantiles", "seed": seed,
            "absolute_gate": summary(old), "per_query_z_gate": summary(new)}


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
