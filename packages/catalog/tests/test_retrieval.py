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


def test_lexical_finds_filtered_item_behind_many_stronger_hits(store):
    rows = [record(f"p{n:03}", summary="retry retry retry wording", agents=["claude_code"]) for n in range(60)]
    rows.append(record("only-codex", summary="retry once, among many other unrelated words here", agents=["codex"]))
    publish(store, rows)
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
    monkeypatch.setattr(module, "_fts_term", lambda term, is_prefix: '"a b"')  # phrase: unsupported here
    result = search(store, MatchRequest(text="tool env", features=[Feature(feature="friction", value="tool_env")]))
    assert result["degraded"] == ["lexical:OperationalError"]
    assert result["routes"]["lexical"] == 0
    assert [i["item_id"] for i in result["items"]] == ["envfix"]


# --- lexical BM25F ranking and absolute scores (hand-computed expectations) ---------------------

def _animals(store):
    rows = [("zebra", "zebra", "striped animal"), ("lion", "lion", "savanna animal"),
            ("eagle", "eagle", "mountain bird"), ("guide", "safari guide", "lion lion lion tracking")]
    publish(store, [Record(native_id=i, resource=Resource(item_id=i, type="skill", name=n, summary=s,
                                                           url="https://example.org")) for i, n, s in rows])


def _lexical_raw(result, item_id):
    item = next(i for i in result["items"] if i["item_id"] == item_id)
    return item["score_parts"]["routes"]["lexical"]["raw_score"]


def test_bm25f_absolute_score_matches_hand_computation(store):
    import math

    from tandem_catalog.search import IDF_PRIOR_DOCS
    _animals(store)  # 4 items, one metadata chunk each: "name\nsummary"
    n = 4 + IDF_PRIOR_DOCS
    idf = lambda df: math.log(1 + (n - df + 0.5) / (df + 0.5))  # noqa: E731
    result = search(store, MatchRequest(text="zebra"))
    # name hit (weight 4) + one occurrence in the chunk text: tf~ = 5, saturation 5 / (1.2 + 5)
    assert _lexical_raw(result, "zebra") == pytest.approx(5 / 6.2)
    result = search(store, MatchRequest(text="zebra animal"))
    expected = (idf(1) * 5 / 6.2 + idf(2) * 1 / 2.2) / (2 * idf(1))
    assert _lexical_raw(result, "zebra") == pytest.approx(expected)
    # "lion" (savanna animal) carries only the df=2 term in its text.
    assert _lexical_raw(result, "lion") == pytest.approx(idf(2) / 2.2 / (2 * idf(1)))
    assert result["items"][0]["item_id"] == "zebra"


def test_name_hit_outranks_repeated_body_mentions(store):
    _animals(store)
    ids = [i["item_id"] for i in search(store, MatchRequest(text="lion"))["items"]]
    # lion: tf~ = 4 + 1 → 5/6.2 = 0.81; guide: three body hits → 3/4.2 = 0.71.
    assert ids[:2] == ["lion", "guide"]


def test_rare_term_outranks_common_term(store):
    _animals(store)
    rows = [Record(native_id=f"x{k}", resource=Resource(item_id=f"x{k}", type="skill", name=f"pack {k}",
                   summary="deploy notes", url="https://example.org")) for k in range(8)]
    rows.append(Record(native_id="w", resource=Resource(item_id="w", type="skill", name="pack w",
                       summary="wrangler notes", url="https://example.org")))
    publish(store, rows, source="primary", revision="r2", mode="incremental")
    ids = [i["item_id"] for i in search(store, MatchRequest(text="deploy wrangler"))["items"]]
    assert ids[0] == "w"


def test_multi_term_match_outranks_single_term(store):
    rows = [("both", "browser kit", "playwright automation"), ("one", "browser kit two", "plain automation"),
            ("other", "playwright notes", "recording only")]
    publish(store, [Record(native_id=i, resource=Resource(item_id=i, type="skill", name=n, summary=s,
                                                           url="https://example.org")) for i, n, s in rows])
    assert search(store, MatchRequest(text="playwright browser"))["items"][0]["item_id"] == "both"


def test_unknown_and_stop_word_queries_return_nothing(store):
    _animals(store)
    assert search(store, MatchRequest(text="xqzv"))["items"] == []
    assert search(store, MatchRequest(text="the and of how to"))["items"] == []


def test_same_item_scores_identically_in_different_candidate_sets(store):
    _animals(store)
    full = search(store, MatchRequest(text="animal lion"))
    narrow = search(store, MatchRequest(text="animal lion", excluded_ids=["lion", "guide"]))
    score = {i["item_id"]: i["score"] for i in full["items"]}
    assert narrow["items"] and all(i["score"] == score[i["item_id"]] for i in narrow["items"])
    assert all(i["score"] < 0.85 for i in narrow["items"])  # no "best candidate gets the top score"


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    from tandem_catalog.service import CatalogService
    service = CatalogService(tmp_path_factory.mktemp("seed") / "catalog.db")
    service.bootstrap()
    yield service
    service.close()


# Query -> substring every acceptable target name contains (chosen by reading the seed, not by
# running the ranker): the item a user typing the query is looking for.
GOLDEN = {"pdf docx": "docx", "playwright browser": "playwright", "postgres": "postgres", "slack": "slack",
          "kubernetes": "kubernetes", "figma design": "figma", "stripe payments": "stripe", "sentry errors": "sentry",
          "terraform": "terraform", "systematic debugging": "systematic", "notion": "notion",
          "jupyter notebook": "jupyter", "excel spreadsheet": "xlsx", "code review": "code-review",
          "git commit message": "commit"}


@pytest.mark.parametrize("text", sorted(GOLDEN))
def test_seed_golden_queries_hit_top3(seeded, text):
    result = seeded.match(MatchRequest(text=text, purpose="library", limit=3))
    names = [i["name"].casefold() for i in result["items"]]
    assert any(GOLDEN[text] in name for name in names), names
    assert all(i["score_parts"]["routes"]["lexical"]["raw_score"] > 0 for i in result["items"])


@pytest.mark.parametrize("text", ["use the file", "the best tool", "how do I use this"])
def test_seed_generic_query_returns_nothing(seeded, text):
    # Every remaining word is in a large share of the 7.9k seed chunks: idf is low, so even a
    # saturated match stays under MIN_TEXT_RELEVANCE.
    assert seeded.match(MatchRequest(text=text, purpose="library"))["items"] == []


def test_mmr_does_not_treat_shared_agents_as_redundancy(store):
    agents = ["claude_code", "codex", "gemini", "opencode"]
    rows = [Record(native_id=i, resource=Resource(item_id=i, type="skill", name=n, summary=s, agents=a,
                                                   url=f"https://github.com/{i}/repo"))
            for i, n, s, a in [("a", "pdf merge", "pdf pages", agents), ("b", "pdf split", "pdf pdf files", agents),
                               ("c", "pdf forms", "pdf files", [])]]
    publish(store, rows)
    items = search(store, MatchRequest(text="pdf"))["items"]
    by_score = sorted(items, key=lambda i: (-i["score"], -i["score_parts"]["rrf"], i["item_id"]))
    # Distinct names and repositories, same kind: every pair is 1/5 similar, so MMR keeps score order.
    assert [i["item_id"] for i in items] == [i["item_id"] for i in by_score]
    from tandem_catalog.search import _similarity, redundancy_keys
    keys = {i: redundancy_keys({"url": f"https://github.com/{i}/repo", "name_key": i, "type": "skill"}) for i in "ab"}
    assert _similarity({"content_hash": "x", "_keys": keys["a"]}, {"content_hash": "y", "_keys": keys["b"]}) == 0.2


def test_seed_mmr_keeps_docx_at_or_above_its_score_rank(seeded):
    items = seeded.match(MatchRequest(text="pdf docx", purpose="library", limit=10))["items"]
    by_score = sorted(items, key=lambda i: (-i["score"], -i["score_parts"]["rrf"], i["item_id"]))
    position = next(n for n, i in enumerate(items) if i["name"] == "docx")
    assert position <= next(n for n, i in enumerate(by_score) if i["name"] == "docx")
