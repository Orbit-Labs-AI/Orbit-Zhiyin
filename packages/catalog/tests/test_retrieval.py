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
    assert store.stats()["chunks"] == 0 and store.verify()["ok"]


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
        assert conn.execute("SELECT 1 FROM resource_chunk WHERE chunk_rowid=?", (int(original),)).fetchone() is None


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


def test_bilingual_lexical_fallback_does_not_invent_profile_features(store):
    row = Record(native_id="debug", resource=Resource(item_id="debug", type="skill", name="Systematic Debugging",
                 summary="Reproduce the failure and investigate its root cause.", url="https://example.org"))
    publish(store, [row])
    result = search(store, MatchRequest(text="调试"))
    assert result["items"][0]["item_id"] == "debug"
    assert result["routes"]["lexical"] == 1
    assert result["routes"]["feature"] == 0
    assert result["items"][0]["matched_features"] == []
    assert result["vector"]["status"] == "not_configured"


def test_prefix_query_matches_partial_last_token(store):
    publish(store, [record("profiler", summary="performance profiling flamegraph")])
    assert search(store, MatchRequest(text="flameg"))["items"] == []
    assert search(store, MatchRequest(text="flameg", prefix=True))["items"][0]["item_id"] == "profiler"


def test_lexical_k_doubles_until_filtered_items_found(store, monkeypatch):
    import tandem_catalog.search as module
    rows = [record(f"p{n:03}", summary="retry retry retry wording", agents=["claude_code"]) for n in range(60)]
    rows.append(record("only-codex", summary="retry once, among many other unrelated words here", agents=["codex"]))
    publish(store, rows)
    monkeypatch.setattr(module, "MIN_K", 1)  # First window (40 chunks) holds only filtered-out items.
    result = search(store, MatchRequest(text="retry", agents=["codex"], per_route=10))
    assert [i["item_id"] for i in result["items"]] == ["only-codex"]


def test_match_many_equals_individual_matches(tmp_path):
    from tandem_catalog.service import CatalogService
    service = CatalogService(tmp_path / "catalog.db", encoder=ToyEncoder())
    try:
        service.store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test", priority=99)])
        publish(service.store, [record("a"), record("b", summary="fault isolation runbook"), record("c", summary="writing")])
        index_embeddings(service.store, service.encoder())
        requests = [MatchRequest(text=t) for t in ("故障排查", "debug", "writing", "debug")]
        batch = service.match_many(requests)
        assert [r["items"] for r in batch] == [service.match(r)["items"] for r in requests]
        assert batch[0]["vector"]["status"] == "ready"
    finally:
        service.close()


def test_fp16_scores_preserve_fp32_top10():
    from tandem_catalog.vectors import blocked_scores
    rng = np.random.default_rng(7)
    matrix = normalize_vectors(rng.normal(size=(5000, 64)), 5000, 64)
    overlaps = []
    for _ in range(20):
        query = normalize_vectors(rng.normal(size=(1, 64)), 1, 64)[0]
        exact = set(np.argsort(-(matrix @ query))[:10])
        approx = set(np.argsort(-blocked_scores(matrix.astype("<f2"), query))[:10])
        overlaps.append(len(exact & approx) / 10)
    assert np.mean(overlaps) >= 0.95


@pytest.mark.parametrize("text", ["tool_env_failure", "node_repl", "exec_command shell", "a_b", "__init__", "ab_"])
def test_snake_case_query_matches_fts_split_not_phrase(store, text):
    rows = [record("envfix", summary="tool env failure triage for node repl and exec command shell, a b init ab")]
    publish(store, rows)
    result = search(store, MatchRequest(purpose="library", text=text))
    assert "degraded" not in result
    assert [i["item_id"] for i in result["items"]] == ["envfix"]


def test_lexical_fts_error_degrades_only_that_route(store, monkeypatch):
    import tandem_catalog.search as module
    publish(store, [record("envfix", features=[Feature(feature="friction", value="tool_env", origin="curated")])])
    monkeypatch.setattr(module, "match_expression", lambda text, prefix=False: '"a b"')  # phrase: unsupported here
    result = search(store, MatchRequest(text="tool env", features=[Feature(feature="friction", value="tool_env")]))
    assert result["degraded"] == ["lexical:OperationalError"]
    assert result["routes"]["lexical"] == 0
    assert [i["item_id"] for i in result["items"]] == ["envfix"]
