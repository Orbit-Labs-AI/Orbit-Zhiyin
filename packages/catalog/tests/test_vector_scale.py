"""Large-index invariants on small fixtures; inference quality is tested separately."""

import numpy as np

from orbit_catalog.contracts import SourceSpec
from orbit_catalog.store import CatalogStore
from orbit_catalog.vectors import index_embeddings

from .test_retrieval import ToyEncoder
from .test_storage import publish, record


def make_store(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    return store


def test_coverage_counts_owners_not_deduplicated_vectors(tmp_path):
    store = make_store(tmp_path)
    first = record("a")
    second = first.model_copy(update={"native_id": "b", "resource": first.resource.model_copy(update={"item_id": "b"})})
    publish(store, [first, second])
    encoder = ToyEncoder()
    result = index_embeddings(store, encoder)
    assert result["computed"] == 1
    assert result["coverage"]["overview_items"] == 2
    assert result["coverage"]["indexed_items"] == 2
    assert result["coverage"]["fully_indexed_items"] == 2


def test_overview_then_all_and_durable_cancellation(tmp_path):
    store = make_store(tmp_path)
    body = "\n".join(f"## Section {i}\nDistinct paragraph number {i}." for i in range(7))
    publish(store, [record("a", body=body, body_policy="licensed", license="MIT", metadata={"embedding_policy": "all"}),
                    record("b", body=body, body_policy="licensed", license="MIT", metadata={"embedding_policy": "all"})])
    encoder = ToyEncoder()
    updates = []
    first = index_embeddings(store, encoder, scope="overview", batch_size=1, progress=updates.append,
                             cancelled=lambda: len(updates) == 1)
    assert first["cancelled"] and first["pending"] == 1
    assert first["coverage"]["overview_items"] == 1
    second = index_embeddings(store, encoder, scope="overview")
    assert second["status"] == "ready" and second["computed"] == 1
    assert second["coverage"]["pending_chunks"] > 0
    assert second["coverage"]["fully_indexed_items"] == 0
    final = index_embeddings(store, encoder)
    assert final["coverage"]["fully_indexed_items"] == 2
    assert final["coverage"]["full_body_items"] == 2
    assert final["coverage"]["indexed_body_chunks"] == final["coverage"]["body_chunks"]
    assert index_embeddings(store, encoder)["computed"] == 0


def test_partial_embedding_policy_is_not_full_body_coverage(tmp_path):
    store = make_store(tmp_path)
    body = "\n".join(f"## Section {i}\nDistinct paragraph number {i}." for i in range(7))
    publish(store, [record("a", body=body, body_policy="licensed", license="MIT")])
    result = index_embeddings(store, ToyEncoder())
    assert result["status"] == "ready"
    assert result["coverage"]["eligible_fully_indexed_items"] == 1
    assert result["coverage"]["fully_indexed_items"] == 0
    assert result["coverage"]["full_body_items"] == 0
    assert result["coverage"]["indexed_body_chunks"] < result["coverage"]["body_chunks"]


def test_embedding_progress_reuses_catalog_snapshot_refreshes_matrix(tmp_path):
    store = make_store(tmp_path)
    publish(store, [record("a"), record("b")])
    encoder = ToyEncoder()
    snapshot = store.index()
    with store.reader() as conn:
        matrix, _, _ = snapshot.matrix(conn, encoder.model_id, encoder.dimensions)
    assert len(matrix) == 0
    index_embeddings(store, encoder, max_chunks=1)
    assert store.index() is snapshot
    with store.reader() as conn:
        first, _, _ = snapshot.matrix(conn, encoder.model_id, encoder.dimensions)
    assert len(first) == 1
    index_embeddings(store, encoder)
    assert store.index() is snapshot
    with store.reader() as conn:
        second, _, _ = snapshot.matrix(conn, encoder.model_id, encoder.dimensions)
    assert len(second) == 2 and len(first) == 1
    np.testing.assert_array_equal(first[0], second[0])


def test_disjoint_item_ranges_resume_without_reencoding(tmp_path):
    store = make_store(tmp_path)
    publish(store, [record(key) for key in ("a", "b", "c", "d")])
    encoder = ToyEncoder()
    middle = index_embeddings(store, encoder, item_start="b", item_end="d", batch_size=1)
    assert middle["computed"] == 2 and middle["coverage"]["indexed_items"] == 2
    assert index_embeddings(store, encoder, item_end="b")["computed"] == 1
    assert index_embeddings(store, encoder, item_start="d")["computed"] == 1
    assert index_embeddings(store, encoder)["computed"] == 0


def test_failed_batch_preserves_commits_for_resume(tmp_path):
    import pytest
    store = make_store(tmp_path)
    publish(store, [record(key) for key in ("a", "b", "c")])

    class FailedEncoder(ToyEncoder):
        def encode(self, texts, *, query=False):
            if self.calls:
                raise RuntimeError("inference_failed")
            return super().encode(texts, query=query)

    with pytest.raises(RuntimeError, match="inference_failed"):
        index_embeddings(store, FailedEncoder(), batch_size=1)
    resumed = index_embeddings(store, ToyEncoder(), batch_size=1)
    assert resumed["computed"] == 2
    assert resumed["coverage"]["overview_items"] == 3


def test_concurrent_same_hash_counts_attempts_not_unique_cache_rows(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    store = make_store(tmp_path)
    first = record("a")
    second = first.model_copy(update={"native_id": "b", "resource": first.resource.model_copy(update={"item_id": "b"})})
    publish(store, [first, second])
    barrier = threading.Barrier(2)

    class RacingEncoder(ToyEncoder):
        def encode(self, texts, *, query=False):
            barrier.wait(timeout=5)
            return super().encode(texts, query=query)

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(index_embeddings, store, RacingEncoder(), item_end="b")
        right = pool.submit(index_embeddings, store, RacingEncoder(), item_start="b")
        results = [left.result(), right.result()]
    assert sum(r["computed"] for r in results) == 2
    with store.connect(True) as conn:
        assert conn.execute("SELECT count(*) FROM embedding_cache").fetchone()[0] == 1
    assert results[-1]["coverage"]["overview_items"] == 2


def fake_workers(monkeypatch, exitcodes, messages=()):
    """Exercise parent supervision without requiring ONNX or sleeping for timeout tests."""
    import queue
    import threading
    from types import SimpleNamespace

    import orbit_catalog.vectors as vectors

    class Events:
        closed = False

        def __init__(self):
            self.messages = list(messages)
            self.polls = 0

        def get(self, timeout):
            self.polls += 1
            assert self.polls <= 10, "supervisor did not detect the failed/cancelled worker"
            if self.messages:
                return self.messages.pop(0)
            raise queue.Empty

        def close(self):
            self.closed = True

    class Process:
        def __init__(self, *, target, args):
            self.exitcode = exitcodes[len(processes)]
            self.terminated = False
            processes.append(self)

        def start(self):
            pass

        def join(self, timeout):
            pass

        def is_alive(self):
            return self.exitcode is None

        def terminate(self):
            self.terminated, self.exitcode = True, -15

        def kill(self):
            self.terminated, self.exitcode = True, -9

    events, stop, processes = Events(), threading.Event(), []
    context = SimpleNamespace(Queue=lambda: events, Event=lambda: stop, Process=Process)
    monkeypatch.setattr(vectors.multiprocessing, "get_context", lambda _: context)
    monkeypatch.setattr(vectors.os, "cpu_count", lambda: 8)
    return events, stop, processes


def test_parallel_clean_exit_without_result_does_not_wait_for_other_shard(tmp_path, monkeypatch):
    import pytest

    from orbit_catalog.vectors import index_embeddings_parallel
    store = make_store(tmp_path)
    publish(store, [record("a"), record("b")])
    events, stop, processes = fake_workers(monkeypatch, [0, None])
    with pytest.raises(RuntimeError, match="finished_without_result"):
        index_embeddings_parallel(store, "unused", workers=2)
    assert events.polls == 2  # First empty poll allows a racing final queue message to arrive.
    assert events.closed and stop.is_set() and processes[1].terminated


def test_parallel_worker_exception_stops_siblings(tmp_path, monkeypatch):
    import pytest

    from orbit_catalog.vectors import index_embeddings_parallel
    store = make_store(tmp_path)
    publish(store, [record("a"), record("b")])
    events, stop, processes = fake_workers(monkeypatch, [0, None], [("error", 0, "CatalogBusy: catalog_writer_busy")])
    with pytest.raises(RuntimeError, match="CatalogBusy: catalog_writer_busy"):
        index_embeddings_parallel(store, "unused", workers=2)
    assert events.closed and stop.is_set() and processes[1].terminated


def test_parallel_stuck_encoder_cancel_has_deadline(tmp_path, monkeypatch):
    import itertools

    import pytest

    import orbit_catalog.vectors as vectors
    store = make_store(tmp_path)
    publish(store, [record("a"), record("b")])
    events, stop, processes = fake_workers(monkeypatch, [None, None])
    ticks = itertools.count(0, 10)
    monkeypatch.setattr(vectors.time, "monotonic", lambda: next(ticks))
    with pytest.raises(InterruptedError, match="embedding_cancel_timeout"):
        vectors.index_embeddings_parallel(store, "unused", workers=2, cancelled=lambda: True)
    assert events.closed and stop.is_set() and all(p.terminated for p in processes)


def test_old_wal_reader_gets_its_own_catalog_index_without_replacing_new_cache(tmp_path):
    store = make_store(tmp_path)
    publish(store, [record("old")])
    with store.connect(True) as old_conn:
        old_generation = store.generation(old_conn)  # First read pins the WAL snapshot.
        publish(store, [record("new")])
        current = store.index()
        assert current.ids == ["new"] and current.generation > old_generation
        old = store.index(old_conn)
        assert old.generation == old_generation
        assert old.ids == ["old"]
        assert store.index() is current


def test_old_wal_vectors_do_not_roll_back_new_matrix_cache(tmp_path):
    store = make_store(tmp_path)
    publish(store, [record("a"), record("b")])
    encoder = ToyEncoder()
    index_embeddings(store, encoder, max_chunks=1)
    index = store.index()
    with store.connect(True) as old_conn:
        old_generation = int(old_conn.execute("SELECT value FROM catalog_meta WHERE key='embedding_generation'").fetchone()[0])
        index_embeddings(store, encoder)
        with store.connect(True) as fresh_conn:
            current = index.matrix(fresh_conn, encoder.model_id, encoder.dimensions)
            current_generation = int(fresh_conn.execute("SELECT value FROM catalog_meta WHERE key='embedding_generation'").fetchone()[0])
        assert len(current[0]) == 2 and current_generation > old_generation
        previous = index.matrix(old_conn, encoder.model_id, encoder.dimensions)
        assert len(previous[0]) == 1
        assert index._matrix_generation == current_generation
        with store.connect(True) as fresh_conn:
            assert index.matrix(fresh_conn, encoder.model_id, encoder.dimensions) is current
