"""Scale failure regressions with constructed data, not measured user effectiveness."""

import numpy as np
import pytest

from orbit_catalog.contracts import MatchRequest, Resource, SourceSpec
from orbit_catalog.features import chunks
from orbit_catalog.search import _mmr, _semantic, redundancy_keys, search
from orbit_catalog.store import CatalogStore

from .test_retrieval import ToyEncoder
from .test_storage import publish, record


@pytest.fixture
def store(tmp_path):
    result = CatalogStore(tmp_path / "catalog.db")
    result.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    return result


def test_exact_reranking_does_not_stop_at_40th_candidate(store):
    rows = [record(f"a{i:03}", summary="zephyr instructions") for i in range(60)]
    rows.append(record("z-target", summary="zephyr " * 8))
    publish(store, rows)
    result = search(store, MatchRequest(text="zephyr", limit=1, per_route=10))
    assert result["items"][0]["item_id"] == "z-target"


def test_best_passage_is_recomputed_after_approximate_recall(store):
    publish(store, [record("guide", summary="zephyr", body_policy="licensed", license="MIT",
                           body="# First\nzephyr once\n# Last\n" + "zephyr " * 20)])
    item = search(store, MatchRequest(text="zephyr"))["items"][0]
    assert item["passage"]["heading"] == "Last"
    assert item["passage"]["text"].count("zephyr") == 20


def test_semantic_topk_aggregates_unbounded_passages_and_stable_ties():
    class Index:
        ids = ["long", "a-target", "b-tie", "excluded"]
        def __len__(self):
            return len(self.ids)

        def matrix(self, *args):
            # More than 4*K strongest chunks belong to one resource; excluded chunks are
            # strongest too. All candidates fit exactly in memory as in production fp16.
            matrix = np.array([[1, 0, 0]] * 100 + [[.9, 0, 0]] * 2 + [[1, 0, 0]], dtype=np.float16)
            return matrix, np.array([0] * 100 + [1, 2, 3]), np.arange(103)

    hits, passages, scanned = _semantic(None, Index(), np.array([True, True, True, False]),
                                       ToyEncoder(), "fault isolation", 2)
    assert [item for item, _ in hits] == ["long", "a-target"]
    assert scanned == 102 and passages == {"long": 0, "a-target": 100}


def test_metadata_only_does_not_lose_relevance_for_licensing_policy(store):
    publish(store, [record("metadata", summary="zephyr", license="MIT"),
                    record("fulltext", summary="zephyr", license="MIT", body_policy="licensed", body="unrelated text")])
    items = {i["item_id"]: i for i in search(store, MatchRequest(text="zephyr"))["items"]}
    assert items["metadata"]["score"] == pytest.approx(items["fulltext"]["score"])
    assert not items["metadata"]["quality"]["dimensions"]["body_available"]
    assert items["fulltext"]["quality"]["dimensions"]["body_available"]
    assert items["metadata"]["effect_status"] == "unmeasured"


def test_repeated_repository_results_accumulate_diversity_cost():
    def candidate(item_id, repo, score):
        row = {"name_key": item_id, "url": f"https://github.com/{repo}/repo", "type": "skill"}
        return {"item_id": item_id, "content_hash": item_id, "score": score,
                "score_parts": {"rrf": 0}, "_keys": redundancy_keys(row)}
    candidates = [candidate(f"a{i}", "one", 1) for i in range(6)]
    candidates.append(candidate("b", "two", .87))
    result = _mmr(candidates, 4)
    # Pairwise max alone leaves b behind all 6 same-repository results; cumulative cost
    # promotes it once three useful results from the first repository have been selected.
    assert [i["item_id"] for i in result] == ["a0", "a1", "a2", "b"]
    assert result[2]["score_parts"]["diversity"]["repository_results_before"] == 2


def test_embedding_budget_spans_body_and_full_policy_is_explicit():
    resource = Resource(item_id="guide", type="skill", name="Guide", url="https://example.org/guide",
                        body_policy="licensed", body="\n".join(f"# Section {n}\nPassage {n}" for n in range(10)))
    sampled = chunks(resource)
    assert sum(c["embed"] for c in sampled) == 4
    assert sampled[0]["embed"] and sampled[-1]["embed"]
    full = chunks(resource.model_copy(update={"metadata": {"embedding_policy": "all"}}))
    assert all(c["embed"] for c in full)


def test_index_only_body_can_recall_but_cannot_be_returned_as_passage(store):
    publish(store, [record("public-guide", summary="Public guide", body_policy="index_only", body="zephyr " * 20)])
    items = search(store, MatchRequest(text="zephyr"))["items"]
    assert len(items) == 1 and items[0]["item_id"] == "public-guide"
    assert items[0]["passage"] is None
    assert items[0]["score_parts"]["routes"]["lexical"]["raw_score"] > 0
    assert not items[0]["quality"]["dimensions"]["body_available"]


def test_semantic_item_topk_with_100000_candidates():
    class Index:
        ids = [f"item-{i:06}" for i in range(100000)]
        def __len__(self):
            return len(self.ids)

        def matrix(self, *args):
            matrix = np.tile(np.array([.8, .6, 0], dtype=np.float16), (len(self.ids), 1))
            matrix[-1] = [1, 0, 0]
            rows = np.arange(len(self.ids))
            return matrix, rows, rows

    index = Index()
    hits, _, scanned = _semantic(None, index, np.ones(len(index), dtype=bool), ToyEncoder(), "fault isolation", 10)
    assert scanned == 100000
    assert [i for i, _ in hits] == ["item-099999", *index.ids[:9]]
