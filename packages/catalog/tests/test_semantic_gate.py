import numpy as np

from orbit_catalog.contracts import MatchRequest, Record, Resource, SourceSpec
from orbit_catalog.search import (
    MIN_TEXT_RELEVANCE,
    SEMANTIC_Z_GATE,
    SEMANTIC_Z_MIN_CHUNKS,
    query_concepts,
    search,
    semantic_expansion,
    semantic_gate,
)
from orbit_catalog.store import CatalogStore
from orbit_catalog.vectors import index_embeddings

from .test_storage import publish


def test_gate_standardises_per_query_and_keeps_only_the_upper_tail():
    rng = np.random.default_rng(3)
    # Two queries with different baselines (E5 medians 0.78 vs 0.81): the same absolute cosine
    # 0.83 is an outlier for the first and ordinary for the second.
    for median, expect in ((0.78, True), (0.81, False)):
        scores = np.concatenate([[0.83], rng.normal(median, 0.02, 999)]).astype(np.float32)
        keep, strength, standardised = semantic_gate(scores, np.ones(len(scores), dtype=bool))
        assert standardised and bool(keep[0]) is expect
        z = (scores - np.median(scores)) / scores.std()
        assert np.array_equal(keep, z >= SEMANTIC_Z_GATE)
        assert strength[keep].min() >= np.float32(MIN_TEXT_RELEVANCE) and strength[~keep].max() == 0
        assert keep.mean() < 0.1  # a floor of 0.76 would have kept ~all of them


def test_gate_falls_back_to_the_absolute_floor_on_small_libraries():
    scores = np.array([0.9, 0.75, 0.0, -0.2], dtype=np.float32)
    keep, strength, standardised = semantic_gate(scores, np.ones(4, dtype=bool))
    assert not standardised and keep.tolist() == [True, True, False, False]
    assert abs(float(strength[0]) - (0.9 - 0.7) / 0.3) < 1e-5
    population = np.ones(SEMANTIC_Z_MIN_CHUNKS, dtype=bool)
    assert semantic_gate(np.linspace(0.7, 0.9, SEMANTIC_Z_MIN_CHUNKS, dtype=np.float32), population)[2]


def test_han_query_gets_an_english_semantic_probe():
    assert semantic_expansion("浏览器自动化测试")
    assert "automation" in semantic_expansion("浏览器自动化测试")
    assert semantic_expansion("postgres database") is None


class BilingualEncoder:
    """The Chinese query lands on the Chinese item; only the English probe reaches the English one."""
    model_id = "test:bilingual-v1"
    dimensions = 3
    descriptor = {"encoder": "test-bilingual", "revision": 1}

    def encode(self, texts, *, query=False):
        def vector(t):
            if "自动化" in t:
                return [1, 0, 0]
            if "automation" in t:
                return [0, 1, 0]
            return [0, 0, 1]
        return np.array([vector(t) for t in texts], dtype=np.float32)


def test_bilingual_probe_reaches_english_items(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    publish(store, [Record(native_id=i, resource=Resource(item_id=i, type="skill", name=n, summary=s, url="https://example.org"))
                    for i, n, s in [("zh", "中文条目", "自动化 流程"), ("en", "runner", "automation runner"),
                                    ("other", "misc", "unrelated words")]])
    index_embeddings(store, BilingualEncoder())
    hits = {i["item_id"] for i in search(store, MatchRequest(text="自动化", per_route=10), BilingualEncoder())["items"]
            if "semantic" in i["score_parts"]["routes"]}
    assert {"zh", "en"} <= hits and "other" not in hits


def test_han_filler_is_not_a_query_concept():
    assert query_concepts("有什么好用的") == []
    assert query_concepts("一个工具") == []
