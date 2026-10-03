"""Semantic route lifecycle without a model: download checks, degradation, slices, coverage.

The encoder is a fixed 384-dimension fixture: every text maps to a hand-written unit vector
(axis 0 = "alpha", axis 1 = "bravo"), so every cosine below is derived by hand, not by
running the implementation.
"""

import hashlib
import io
import time

import numpy as np
import pytest

from tandem_catalog import embedding_model
from tandem_catalog.contracts import MatchRequest, Record, Resource, SourceSpec
from tandem_catalog.search import search
from tandem_catalog.service import CatalogService
from tandem_catalog.vectors import embedding_coverage, index_embeddings

from .test_storage import publish

DIM = 384


def axis(*weights):
    vector = np.zeros(DIM, dtype=np.float32)
    vector[:len(weights)] = weights
    return vector / np.linalg.norm(vector)


class FixtureEncoder:
    """alpha -> e0, bravo -> e1, both words -> (e0+e1)/sqrt(2), anything else -> e2."""
    model_id = "fixture:e384-v1"
    dimensions = DIM
    descriptor = {"encoder": "fixture-384", "revision": 1}

    def __init__(self):
        self.encoded = []

    def encode(self, texts, *, query=False):
        self.encoded.extend(texts)
        rows = []
        for text in texts:
            a, b = "alpha" in text.lower(), "bravo" in text.lower()
            rows.append(axis(1, 1) if a and b else axis(1) if a else axis(0, 1) if b else axis(0, 0, 1))
        return np.array(rows)


def items(*specs):
    return [Record(native_id=key, resource=Resource(item_id=key, type="skill", name=key, summary=summary,
                                                    url="https://example.org/" + key))
            for key, summary in specs]


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.delenv("TANDEM_HOME", raising=False)
    monkeypatch.delenv(embedding_model.ENV_ALLOW, raising=False)
    svc = CatalogService(tmp_path / "home/catalog.db", http=object())
    svc.store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    yield svc
    svc.close()


def wait(svc, job):
    for _ in range(500):
        current = svc.job(job["job_id"])
        if current["status"] not in ("queued", "running"):
            return current
        time.sleep(0.01)
    raise AssertionError("job did not finish")


# --- download -------------------------------------------------------------------------------

class Server:
    """Serves fixed bodies; records Range headers; optionally ignores Range (HTTP 200)."""

    def __init__(self, bodies, honour_range=True):
        self.bodies, self.honour_range, self.ranges = bodies, honour_range, []

    def __call__(self, url, headers):
        body = self.bodies[url.rsplit("/resolve/r1/", 1)[1]]
        self.ranges.append(headers.get("Range"))
        start = int(headers["Range"][6:-1]) if headers.get("Range") and self.honour_range else 0
        response = io.BytesIO(body[start:])
        response.status = 206 if start else 200
        return response


def pinned(bodies, tamper=()):
    return tuple((path, len(body), hashlib.sha256(b"x" if path in tamper else body).hexdigest())
                 for path, body in bodies.items())


BODIES = {"onnx/model.onnx": b"0123456789abcdef", "onnx/tokenizer.json": b'{"tok": 1}'}


def test_download_checksum_mismatch_leaves_no_model(tmp_path, monkeypatch):
    monkeypatch.setattr(embedding_model, "CHUNK", 4)
    files = pinned(BODIES, tamper={"onnx/model.onnx"})
    with pytest.raises(embedding_model.ModelDownloadError, match="model_checksum_mismatch"):
        embedding_model.download(tmp_path, opener=Server(BODIES), files=files, base_url="https://h/resolve/r1/")
    target = tmp_path / embedding_model.MODEL_NAME
    assert not (target / "onnx/model.onnx").exists()
    assert not (target / "onnx/model.onnx.part").exists()  # a bad partial file is not resumed
    assert not (target / "manifest.json").exists()
    assert embedding_model.discover([tmp_path]) is None


def test_download_resumes_with_range_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr(embedding_model, "CHUNK", 4)
    files, server = pinned(BODIES), Server(BODIES)
    calls = iter([False, True])  # cancelled() is checked after each 4-byte block: stop after the first
    with pytest.raises(embedding_model.ModelDownloadError, match="model_download_cancelled"):
        embedding_model.download(tmp_path, opener=server, files=files, base_url="https://h/resolve/r1/",
                                 cancelled=lambda: next(calls))
    part = tmp_path / embedding_model.MODEL_NAME / "onnx/model.onnx.part"
    assert part.read_bytes() == b"0123"  # first block written, second one refused
    seen = []
    target = embedding_model.download(tmp_path, opener=server, files=files, base_url="https://h/resolve/r1/",
                                      progress=lambda done, total: seen.append((done, total)))
    assert server.ranges == [None, "bytes=4-", None]  # model resumed at byte 4, tokenizer fresh
    assert (target / "onnx/model.onnx").read_bytes() == BODIES["onnx/model.onnx"]
    assert seen[-1] == (16 + 10, 16 + 10)
    assert embedding_model.discover([tmp_path]) == target
    model, tokenizer, manifest = embedding_model.model_files(target)
    assert manifest["revision"] == embedding_model.REVISION and model.name == "model.onnx"


def test_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    monkeypatch.setattr(embedding_model, "CHUNK", 4)
    part = tmp_path / embedding_model.MODEL_NAME / "onnx/model.onnx.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"0123")
    server = Server(BODIES, honour_range=False)
    target = embedding_model.download(tmp_path, opener=server, files=pinned(BODIES), base_url="https://h/resolve/r1/")
    assert server.ranges[0] == "bytes=4-"
    assert (target / "onnx/model.onnx").read_bytes() == BODIES["onnx/model.onnx"]


def test_discovery_order_and_incomplete_dirs(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    (second / embedding_model.MODEL_NAME / "onnx").mkdir(parents=True)
    for name in ("model.onnx", "tokenizer.json"):
        (second / embedding_model.MODEL_NAME / "onnx" / name).write_bytes(b"x")
    (first / embedding_model.MODEL_NAME / "onnx").mkdir(parents=True)
    (first / embedding_model.MODEL_NAME / "onnx/model.onnx").write_bytes(b"x")  # no tokenizer
    assert embedding_model.discover([first, second]) == second / embedding_model.MODEL_NAME


# --- degradation ----------------------------------------------------------------------------

def test_missing_model_degrades_to_lexical(service):
    publish(service.store, items(("alpha-skill", "alpha deployment helper")))
    result = service.match(MatchRequest(text="alpha deployment"))
    assert [i["item_id"] for i in result["items"]] == ["alpha-skill"]
    assert result["vector"] == {"status": "not_configured"} and "semantic" not in result["routes"]
    status = service.vector_status()
    assert status["status"] == "not_configured" and status["download"]["allowed"] is False
    assert status["download"]["total_bytes"] == 118_346_824 + 17_082_730
    assert service.vector_tick() is None  # no consent: never downloads


def test_download_failure_is_reported_not_retried_at_once(service, monkeypatch):
    def broken(root, **_):
        raise embedding_model.ModelDownloadError("model_checksum_mismatch")
    monkeypatch.setattr(embedding_model, "download", broken)
    status = service.set_model_download(True)
    job = next(j for j in service._jobs.values())
    assert wait(service, job)["error"] == "model_checksum_mismatch"
    status = service.vector_status()
    assert status["status"] == "download_failed" and status["download"]["error"] == "model_checksum_mismatch"
    assert service.vector_tick() is None  # back-off: DOWNLOAD_RETRY_S


def test_unloadable_model_is_unavailable_and_search_still_works(service):
    target = service.model_roots[0] / embedding_model.MODEL_NAME / "onnx"
    target.mkdir(parents=True)
    (target / "model.onnx").write_bytes(b"not onnx")
    (target / "tokenizer.json").write_text("{}")
    publish(service.store, items(("alpha-skill", "alpha deployment helper")))
    result = service.match(MatchRequest(text="alpha deployment"))
    assert result["vector"]["status"] == "unavailable"
    assert result["vector"]["reason"] in ("embedding_model_unloadable", "embedding_runtime_missing")
    assert [i["item_id"] for i in result["items"]] == ["alpha-skill"]
    assert service.vector_status()["status"] == "unavailable"


# --- incremental indexing and coverage --------------------------------------------------------

def test_background_slices_cover_all_chunks_and_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    encoder = FixtureEncoder()
    svc = CatalogService(tmp_path / "catalog.db", http=object(), encoder=encoder)
    try:
        svc.store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
        # Name + summary only: one overview chunk each (features.chunks), all with embed=1.
        publish(svc.store, items(("a", "alpha only"), ("b", "bravo only"), ("c", "alpha and bravo")))
        assert embedding_coverage(svc.store, encoder.model_id) == {
            "model_id": encoder.model_id, "eligible_chunks": 3, "embedded_chunks": 0, "pending_chunks": 3, "ratio": 0.0}
        assert svc.vector_status()["status"] == "not_indexed"
        assert wait(svc, svc.vector_tick(slice_chunks=2))["result"]["indexed"] == 2
        status = svc.vector_status()
        assert status["status"] == "partial" and status["coverage"]["embedded_chunks"] == 2
        assert status["coverage"]["ratio"] == round(2 / 3, 4)
        assert wait(svc, svc.vector_tick(slice_chunks=2))["result"] == {
            "model_id": encoder.model_id, "indexed": 1, "computed": 1, "reused": 0, "pending": 0, "status": "ready"}
        assert svc.vector_status()["status"] == "ready"
        calls = len(encoder.encoded)
        assert svc.vector_tick() is None and len(encoder.encoded) == calls  # idle: same generation
        # A new item with the same text as "a" reuses its vector (text-hash keyed, no encode).
        publish(svc.store, items(("a", "alpha only"), ("b", "bravo only"), ("c", "alpha and bravo"),
                                 ("d", "alpha only")), revision="r2")
        job = svc.vector_tick()
        assert job is not None
        result = wait(svc, job)["result"]
        assert svc.vector_status()["coverage"]["pending_chunks"] == 0
        assert result["indexed"] == result["computed"] + result["reused"]
    finally:
        svc.close()


def test_cancelled_slice_keeps_committed_batches_and_bumps_generation(tmp_path):
    from tandem_catalog.store import CatalogStore
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    publish(store, items(("a", "alpha only"), ("b", "bravo only"), ("c", "alpha and bravo")))
    with store.reader() as conn:
        before = store.generation(conn)
    checks = iter([False, True])
    result = index_embeddings(store, FixtureEncoder(), batch_size=1, cancelled=lambda: next(checks))
    assert (result["indexed"], result["pending"], result["status"]) == (1, 2, "partial")
    with store.reader() as conn:
        assert store.generation(conn) == before + 1
    assert index_embeddings(store, FixtureEncoder())["pending"] == 0  # resumes with the other two


def test_semantic_route_orders_by_hand_computed_cosine(tmp_path):
    from tandem_catalog.store import CatalogStore
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    publish(store, items(("a", "alpha only"), ("b", "bravo only"), ("c", "alpha and bravo")))
    encoder = FixtureEncoder()
    index_embeddings(store, encoder)
    # Query "alpha": cos(a)=1, cos(c)=1/sqrt(2)=0.707, cos(b)=0 (dropped: not positive).
    result = search(store, MatchRequest(text="alpha", limit=5, per_route=10), encoder)
    assert result["vector"]["status"] == "ready" and result["vector"]["indexed_chunks"] == 3
    assert result["routes"]["semantic"] == 2
    semantic = {i["item_id"]: i["score_parts"].get("semantic") for i in result["items"]}
    assert semantic.get("b") is None
