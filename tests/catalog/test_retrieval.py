import numpy as np
import pytest

from tandem_catalog.contracts import Feature, MatchRequest, Record, Resource, SourceSpec
from tandem_catalog.search import search
from tandem_catalog.store import CatalogStore
from tandem_catalog.vectors import index_embeddings, normalize_vectors, register_model

from .test_storage import publish, record


class ToyEncoder:
    """Controlled semantic oracle for route tests, never a shipped fallback encoder."""
    model_id = "test:semantic-v1"
    dimensions = 3
    descriptor = {"encoder": "test", "revision": 1}

    def __init__(self):
        self.calls = 0

    def encode(self, texts, *, query=False):
        self.calls += len(texts)
        return np.array([[1, 0, 0] if "故障排查" in t or "fault isolation" in t else [0, 1, 0] for t in texts], dtype=np.float32)


@pytest.fixture
def store(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    return store


def test_semantic_recall_is_independent_and_filtered_before_topk(store):
    rows = [Record(native_id=str(n), resource=Resource(item_id=str(n), type="plugin", name=f"plugin {n}",
                   summary="fault isolation", url="https://example.org")) for n in range(25)]
    rows.append(Record(native_id="target", resource=Resource(item_id="target", type="skill", name="Runbook",
                       summary="fault isolation", agents=["codex"], url="https://example.org")))
    publish(store, rows)
    encoder = ToyEncoder()
    index_embeddings(store, encoder)
    result = search(store, MatchRequest(text="故障排查", types=["skill"], per_route=10), encoder)
    assert result["items"][0]["item_id"] == "target"
    assert result["routes"]["lexical"] == 0
    assert result["vector"]["indexed_chunks"] == 1
    assert result["items"][0]["passage"]["text"]


def test_chinese_fts_and_source_filters_survive_query_operators(store):
    publish(store, [record("a"), record("b", agents=["claude_code"])])
    result = search(store, MatchRequest(text='重复失败 OR " :*', agents=["codex"], excluded_ids=["a"]))
    assert result["items"] == []
    assert search(store, MatchRequest(text="重复失败"))["items"]
    assert search(store, MatchRequest(text="重复失败", source_ids=["missing"]))["items"] == []


def test_recommendation_requires_evidence_scene_dimension_and_curated_friction(store):
    features = [Feature(feature=k, value=v, origin="curated") for k, v in
                [("friction", "tool_retry"), ("scene", "coding"), ("dimension", "verify")]]
    publish(store, [record("reviewed", agents=["codex"], language="en", features=features,
                           metadata={"verification": "repository_and_skill_read"}),
                    record("unreviewed", agents=["codex"], language="en")])
    req = MatchRequest(text="debug", purpose="recommendation", problem_id="p1", problem_type="tool_retry",
                       evidence_ids=["e1"], profile_evidence_ids=["e2"], scene="coding", agents=["codex"], language="en",
                       features=[Feature(feature="dimension", value="verify")])
    assert [r["item_id"] for r in search(store, req)["items"]] == ["reviewed"]
    assert search(store, req.model_copy(update={"evidence_ids": []}))["gates"] == ["missing_problem_evidence"]
    assert not search(store, req.model_copy(update={"scene": "writing"}))["items"]
    assert not search(store, req.model_copy(update={"language": "zh"}))["items"]
    assert not search(store, req.model_copy(update={"features": []}))["items"]


def test_model_spaces_never_mix_and_partial_coverage_is_explicit(store):
    publish(store, [record("a"), record("b")])
    encoder = ToyEncoder()
    result = index_embeddings(store, encoder, max_chunks=1)
    assert result["status"] == "partial" and result["pending"] == 1
    result = search(store, MatchRequest(text="debug"), encoder)
    assert result["vector"]["status"] == "partial"
    result = search(store, MatchRequest(text="debug", model_id="another:model"), encoder)
    assert result["vector"]["status"] == "model_not_loaded" and "semantic" not in result["routes"]
    encoder.descriptor = {"encoder": "changed"}
    with pytest.raises(ValueError, match="identity_conflict"):
        register_model(store, encoder)


def test_content_cache_reuse_and_deleted_chunks_cannot_match(store):
    row = record(commit_sha="a" * 40)
    publish(store, [row])
    encoder = ToyEncoder()
    index_embeddings(store, encoder)
    count = encoder.calls
    publish(store, [row.model_copy(update={"resource": row.resource.model_copy(update={"commit_sha": "b" * 40})})])
    assert index_embeddings(store, encoder)["computed"] == 0
    assert encoder.calls == count
    publish(store, [])
    assert search(store, MatchRequest(text="debug"), encoder)["items"] == []
    with store.connect(True) as conn:
        assert conn.execute("SELECT count(*) FROM chunk_embedding").fetchone()[0] == 0


def test_stale_embedding_cannot_attach_to_new_version(store):
    publish(store, [record()])
    original = store.detail("debugger")["chunks"][0]["chunk_id"]
    class RacingEncoder(ToyEncoder):
        def encode(self, texts, *, query=False):
            if self.calls == 0:
                publish(store, [record("replacement")])
            return super().encode(texts, query=query)
    result = index_embeddings(store, RacingEncoder())
    assert result["pending"] == 0
    with store.connect(True) as conn:
        assert conn.execute("SELECT 1 FROM chunk_embedding WHERE chunk_id=?", (original,)).fetchone() is None


@pytest.mark.parametrize("vectors", [[[0, 0, 0]], [[float("nan"), 1, 0]], [[1, 2]], [[float("inf"), 0, 0]]])
def test_invalid_embeddings_are_rejected(vectors):
    with pytest.raises(ValueError):
        normalize_vectors(vectors, 1, 3)


def test_read_only_open_during_sync_and_mmr_determinism(store):
    publish(store, [record("one"), record("two")])
    with store.writer():
        reader = CatalogStore(store.path)
        first = search(reader, MatchRequest(text="调试"))
    assert first == search(store, MatchRequest(text="调试"))
