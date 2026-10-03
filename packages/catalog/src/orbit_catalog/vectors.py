"""Versioned local embeddings, resumable materialization, exact cosine search primitives."""

import hashlib
import multiprocessing
import os
import queue
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

import numpy as np

from .contracts import canonical_json, digest
from .embedding_model import model_files


class Encoder(Protocol):
    model_id: str
    dimensions: int
    descriptor: dict

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray: ...


def normalize_vectors(values, count: int, dimensions: int) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    if array.shape != (count, dimensions) or not np.isfinite(array).all():
        raise ValueError("invalid_embedding_shape_or_values")
    norms = np.linalg.norm(array.astype(np.float64), axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError("zero_embedding")
    return np.asarray(array / norms, dtype="<f4")


class LocalE5Encoder:
    """E5-small ONNX with mean pooling. Reads local files only; no remote inference/code.

    Long chunks are split into overlapping token windows rather than silently truncated.
    Each window has its own E5 prefix. Window vectors are mean-pooled and normalized.
    """

    dimensions = 384

    def __init__(self, directory: str | Path, threads: int = 4, *, batch_size: int = 8,
                 max_tokens: int = 512, max_windows: int = 32):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if threads < 1 or batch_size < 1 or not 80 <= max_tokens <= 512 or max_windows < 1:
            raise ValueError("invalid_encoder_limits")
        self.batch_size, self.max_tokens, self.max_windows = batch_size, max_tokens, max_windows
        ort.disable_telemetry_events()
        directory = Path(directory).expanduser().resolve()
        model_path, tokenizer_path, manifest = model_files(directory)
        self.directory = directory
        self.manifest = manifest
        def sha(path):
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        self.descriptor = {"encoder": "multilingual-e5-small-onnx", "model_sha256": sha(model_path),
                           "tokenizer_sha256": sha(tokenizer_path), "dimensions": self.dimensions,
                           "query_prefix": "query: ", "document_prefix": "passage: ",
                           "pooling": "masked-mean/window-mean/l2-v1", "max_tokens": max_tokens, "overlap": 64,
                           "precision": "float32", "distance": "cosine", "runtime": ort.__version__}
        self.model_id = "e5:" + digest(self.descriptor)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.bos, self.eos, self.pad = [self.tokenizer.token_to_id(t) for t in ("<s>", "</s>", "<pad>")]
        if None in (self.bos, self.eos, self.pad):
            raise ValueError("not_an_e5_tokenizer")

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)
        prefix = self.tokenizer.encode("query: " if query else "passage: ", add_special_tokens=False).ids
        frames, owners = [], []
        width = self.max_tokens - len(prefix) - 2
        for index, encoding in enumerate(self.tokenizer.encode_batch(texts, add_special_tokens=False)):
            ids = encoding.ids
            if len(ids) > width + (self.max_windows - 1) * (width - 64):
                raise ValueError("embedding_window_limit_exceeded: split the source chunk; no text was truncated")
            for start in range(0, max(1, len(ids)), width - 64):
                frames.append([self.bos, *prefix, *ids[start:start + width], self.eos])
                owners.append(index)
                if start + width >= len(ids):
                    break
        order = sorted(range(len(frames)), key=lambda i: len(frames[i]))
        frames, owners = [frames[i] for i in order], [owners[i] for i in order]
        results = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        counts = np.zeros((len(texts), 1), dtype=np.float32)
        inputs = {i.name for i in self.session.get_inputs()}
        for start in range(0, len(frames), self.batch_size):
            batch = frames[start:start + self.batch_size]
            length = max(map(len, batch))
            ids = np.full((len(batch), length), self.pad, dtype=np.int64)
            mask = np.zeros_like(ids)
            for i, frame in enumerate(batch):
                ids[i, :len(frame)], mask[i, :len(frame)] = frame, 1
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            if hidden.ndim != 3 or hidden.shape[-1] != self.dimensions:
                raise ValueError("unexpected_e5_output")
            vectors = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            vectors = normalize_vectors(vectors, len(batch), self.dimensions)
            for owner, vector in zip(owners[start:start + len(batch)], vectors, strict=True):
                results[owner] += vector
                counts[owner] += 1
        return normalize_vectors(results / counts, len(texts), self.dimensions)


@contextmanager
def _embedding_writer(store):
    """Independent encoders serialize only their short commits, not inference."""
    from .store import CatalogBusy
    deadline = time.monotonic() + 30
    while True:
        lock = store.writer()
        try:
            lock.__enter__()
            break
        except CatalogBusy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def register_model(store, encoder: Encoder):
    if not 1 <= encoder.dimensions <= 8192:
        raise ValueError("invalid_embedding_dimensions")
    with _embedding_writer(store), store.connect() as conn:
        row = conn.execute("SELECT * FROM embedding_model WHERE model_id=?", (encoder.model_id,)).fetchone()
        descriptor = canonical_json(encoder.descriptor)
        if row and (row["dimensions"] != encoder.dimensions or row["descriptor"] != descriptor):
            raise ValueError("embedding_model_identity_conflict")
        conn.execute("INSERT OR IGNORE INTO catalog_meta(key,value) VALUES('embedding_generation','0')")
        conn.execute("INSERT OR IGNORE INTO embedding_model(model_id,dimensions,descriptor,created_at) VALUES(?,?,?,?)",
                     (encoder.model_id, encoder.dimensions, descriptor, int(time.time() * 1000)))


BLOCK_ROWS = 16384


def blocked_scores(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Exact cosine over an fp16 matrix, converted to fp32 in bounded blocks (no ANN)."""
    scores = np.empty(len(matrix), dtype=np.float32)
    query = np.asarray(query, dtype=np.float32)
    for start in range(0, len(matrix), BLOCK_ROWS):
        scores[start:start + BLOCK_ROWS] = matrix[start:start + BLOCK_ROWS].astype(np.float32) @ query
    if not np.isfinite(scores).all():
        raise ValueError("invalid_cosine_scores")
    return np.clip(scores, -1, 1)


def embedding_coverage(conn, model_id: str) -> dict:
    """Count active resources and chunk ownership, never cache hashes as item coverage."""
    # Both the background service and snapshot readers share one coverage definition.
    if hasattr(conn, "connect"):
        with conn.connect(True) as reader:
            return embedding_coverage(reader, model_id)
    row = conn.execute("""
        WITH per_item AS (
          SELECT i.item_id, count(c.ordinal) AS all_chunks,
                 sum(CASE WHEN c.embed=1 THEN 1 ELSE 0 END) AS eligible,
                 sum(CASE WHEN c.field='body' THEN 1 ELSE 0 END) AS body_chunks,
                 sum(CASE WHEN c.field='body' AND e.text_hash IS NOT NULL THEN 1 ELSE 0 END) AS indexed_body,
                 count(e.text_hash) AS indexed,
                 max(CASE WHEN c.ordinal=0 AND e.text_hash IS NOT NULL THEN 1 ELSE 0 END) AS overview
          FROM catalog_item i LEFT JOIN resource_chunk c ON c.item_id=i.item_id
          LEFT JOIN embedding_cache e ON e.text_hash=c.text_hash AND c.embed=1 AND
            e.model_key=(SELECT model_key FROM embedding_model WHERE model_id=?)
          WHERE i.status='active' GROUP BY i.item_id
        )
        SELECT count(*) AS active_items,
               coalesce(sum(indexed>0),0) AS indexed_items,
               coalesce(sum(overview),0) AS overview_items,
               coalesce(sum(all_chunks>0 AND all_chunks=indexed),0) AS fully_indexed_items,
               coalesce(sum(eligible>0 AND eligible=indexed),0) AS eligible_fully_indexed_items,
               coalesce(sum(body_chunks>0 AND body_chunks=indexed_body),0) AS full_body_items,
               coalesce(sum(body_chunks),0) AS body_chunks,
               coalesce(sum(indexed_body),0) AS indexed_body_chunks,
               coalesce(sum(all_chunks),0) AS all_chunks,
               coalesce(sum(eligible),0) AS eligible_chunks,
               coalesce(sum(indexed),0) AS indexed_chunks
        FROM per_item
        """, (model_id,)).fetchone()
    result = dict(row)
    result["model_id"] = model_id
    result["embedded_chunks"] = result["indexed_chunks"]
    result["ratio"] = round(result["indexed_chunks"] / result["eligible_chunks"], 4) if result["eligible_chunks"] else None
    result["pending_chunks"] = result["eligible_chunks"] - result["indexed_chunks"]
    result["missing_overview_items"] = result["active_items"] - result["overview_items"]
    return result


def index_embeddings(store, encoder: Encoder, *, batch_size=64, max_chunks=None,
                     cancelled=lambda: False, progress=None, scope="all", item_start=None, item_end=None):
    """Resumable keyset scan; only missing text hashes are encoded and each batch commits.

    `scope="overview"` prioritizes one vector per resource before the full body pass.
    Progress fires after durable batches, without recounting the database per batch.
    Counts in `coverage` refer to active item/chunk ownership; `computed` counts
    encoder outputs in committed batches. Concurrent workers may encode the same
    missing hash before either commits, so it is not a global unique-vector count.
    Restarting skips persisted cache rows in one scan.
    """
    if batch_size < 1 or (max_chunks is not None and max_chunks < 0) or scope not in ("all", "overview"):
        raise ValueError("invalid_embedding_batch_limit")
    if item_start is not None and item_end is not None and item_start >= item_end:
        raise ValueError("invalid_embedding_item_range")
    register_model(store, encoder)
    indexed, computed, reused = 0, 0, 0
    started = time.monotonic()
    with store.connect(True) as conn:
        key = conn.execute("SELECT model_key FROM embedding_model WHERE model_id=?", (encoder.model_id,)).fetchone()[0]
        generation = store.generation(conn)
    cursor = (item_start or "", -1)
    was_cancelled = False
    while not (was_cancelled := bool(cancelled())) and (max_chunks is None or indexed < max_chunks):
        limit = min(batch_size, max_chunks - indexed) if max_chunks is not None else batch_size
        with store.connect(True) as conn:
            # Primary-key order avoids repeatedly sorting/scanning the catalog as the
            # cache grows. Each completed pass visits every chunk at most once.
            rows = conn.execute("SELECT c.item_id,c.ordinal,c.text_hash FROM resource_chunk c "
                                "WHERE (c.item_id,c.ordinal)>(?,?) AND c.embed=1 AND EXISTS (SELECT 1 FROM catalog_item i WHERE i.item_id=c.item_id AND i.status='active') "
                                + ("AND c.item_id<? " if item_end is not None else "")
                                + ("AND c.ordinal=0 " if scope == "overview" else "") +
                                "AND NOT EXISTS (SELECT 1 FROM embedding_cache e "
                                "WHERE e.model_key=? AND e.text_hash=c.text_hash) "
                                "ORDER BY c.item_id,c.ordinal LIMIT ?", (*cursor, *((item_end,) if item_end is not None else ()), key, limit)).fetchall()
            if not rows:
                current_generation = store.generation(conn)
                if current_generation == generation:
                    break
                # Publication may insert lower keys while encoding. Revisit only when
                # the resource generation changed, not after embedding-only writes.
                generation, cursor = current_generation, (item_start or "", -1)
                continue
            missing = {}
            texts_by_item = {}
            for row in rows:
                if row["text_hash"] not in missing:
                    if row["item_id"] not in texts_by_item:
                        texts_by_item[row["item_id"]] = store.chunk_texts(conn, row["item_id"])
                    text = texts_by_item[row["item_id"]][row["ordinal"]]
                    if bytes.fromhex(digest(text)[:32]) != row["text_hash"]:
                        raise ValueError("embedding_chunk_text_hash_mismatch")
                    missing[row["text_hash"]] = text
        encoded = normalize_vectors(encoder.encode(list(missing.values())), len(missing), encoder.dimensions)
        with _embedding_writer(store), store.connect() as conn:
            # A concurrent sync only leaves a reusable cache row, never a stale attachment.
            conn.executemany("INSERT OR IGNORE INTO embedding_cache VALUES(?,?,?,?)",
                             [(key, text_hash, encoder.dimensions, vector.astype("<f2").tobytes())
                              for text_hash, vector in zip(missing, encoded, strict=True)])
            conn.execute("UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 WHERE key='embedding_generation'")
        indexed += len(rows)
        computed += len(missing)
        reused += len(rows) - len(missing)
        cursor = (rows[-1]["item_id"], rows[-1]["ordinal"])
        if progress:
            progress({"model_id": encoder.model_id, "scope": scope, "indexed": indexed,
                      "computed": computed, "reused": reused, "cursor": cursor,
                      "elapsed_seconds": round(time.monotonic() - started, 3)})
    with store.connect(True) as conn:
        coverage = embedding_coverage(conn, encoder.model_id)
    pending = coverage["missing_overview_items"] if scope == "overview" else coverage["pending_chunks"]
    return {"model_id": encoder.model_id, "scope": scope, "indexed": indexed, "computed": computed, "reused": reused,
            "pending": pending, "coverage": coverage, "cancelled": was_cancelled,
            "status": "ready" if pending == 0 else "partial"}


def _embedding_worker(path, directory, options, events, stop, worker):
    """Spawn target: models/connections are constructed inside each process."""
    from .store import CatalogStore
    try:
        encoder = LocalE5Encoder(directory, threads=options.pop("threads"),
                                 batch_size=options.pop("encoder_batch_size"))
        result = index_embeddings(CatalogStore(path), encoder, **options, cancelled=stop.is_set,
                                  progress=lambda value: events.put(("progress", worker, value)))
        events.put(("done", worker, result))
    except Exception as exc:
        events.put(("error", worker, f"{type(exc).__name__}: {exc}"))


def index_embeddings_parallel(store, directory, *, workers=1, threads=2, encoder_batch_size=8,
                              batch_size=64, max_chunks=None, scope="all", progress=None,
                              cancelled=lambda: False):
    """Bounded E5 worker processes over disjoint item-key ranges; resumable after cancel.

    The default remains one CPU encoder. At most four workers share the SQLite ledger;
    each owns a model session and commits short batches. Call from a normal guarded
    Python/CLI entry point, since macOS uses multiprocessing spawn. Progress callbacks
    run in the parent with aggregate completed batch counters and a worker id.
    """
    if workers < 1 or threads < 1 or batch_size < 1 or encoder_batch_size < 1 or scope not in ("overview", "all"):
        raise ValueError("invalid_embedding_worker_limits")
    if max_chunks is not None and max_chunks < 0:
        raise ValueError("invalid_embedding_batch_limit")
    workers = min(workers, 4, max(1, (os.cpu_count() or 1) // threads))
    if workers == 1:
        return index_embeddings(store, LocalE5Encoder(directory, threads=threads, batch_size=encoder_batch_size),
                                batch_size=batch_size, max_chunks=max_chunks, scope=scope,
                                progress=progress, cancelled=cancelled)
    with store.connect(True) as conn:
        boundaries = [row[0] for row in conn.execute(
            "SELECT min(item_id) FROM (SELECT item_id,ntile(?) OVER (ORDER BY item_id) AS bucket "
            "FROM catalog_item WHERE status='active') GROUP BY bucket ORDER BY bucket", (workers,))]
    if len(boundaries) < 2:
        return index_embeddings_parallel(store, directory, workers=1, threads=threads,
                                         encoder_batch_size=encoder_batch_size, batch_size=batch_size,
                                         max_chunks=max_chunks, scope=scope, progress=progress, cancelled=cancelled)
    workers = len(boundaries)
    boundaries[0] = None  # Include new keys below today's smallest id if a source publishes concurrently.
    context = multiprocessing.get_context("spawn")
    events, stop = context.Queue(), context.Event()
    processes, finished, latest = [], {}, {}
    exited_without_result = set()
    cancel_started = None
    started = time.monotonic()
    try:
        for worker, lower in enumerate(boundaries):
            budget = None if max_chunks is None else max_chunks // workers + int(worker < max_chunks % workers)
            options = {"item_start": lower, "item_end": boundaries[worker + 1] if worker + 1 < workers else None,
                       "threads": threads, "encoder_batch_size": encoder_batch_size, "batch_size": batch_size,
                       "max_chunks": budget, "scope": scope}
            process = context.Process(target=_embedding_worker,
                                      args=(str(store.path), str(directory), options, events, stop, worker))
            process.start()
            processes.append(process)
        while len(finished) < workers:
            if cancelled() and cancel_started is None:
                cancel_started = time.monotonic()
                stop.set()
            if cancel_started is not None and time.monotonic() - cancel_started >= 15:
                raise InterruptedError("embedding_cancel_timeout: committed batches are resumable")
            try:
                kind, worker, value = events.get(timeout=0.2)
            except queue.Empty:
                if any(p.exitcode not in (None, 0) for p in processes):
                    raise RuntimeError("embedding_worker_exited_without_result") from None
                missing = {i for i, p in enumerate(processes) if p.exitcode == 0 and i not in finished}
                # A result can arrive just after get() times out; require a second
                # empty poll before calling a clean exit without a result a failure.
                if missing & exited_without_result:
                    raise RuntimeError("embedding_workers_finished_without_result") from None
                exited_without_result = missing
                continue
            if kind == "error":
                raise RuntimeError(f"embedding_worker_{worker}: {value}")
            latest[worker] = value
            if kind == "done":
                finished[worker] = value
            if progress:
                progress({"model_id": value["model_id"], "scope": scope, "worker": worker, "workers": workers,
                          **{key: sum(v[key] for v in latest.values()) for key in ("indexed", "computed", "reused")},
                          "elapsed_seconds": round(time.monotonic() - started, 3)})
    finally:
        stop.set()
        deadline = time.monotonic() + 5
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            if process.is_alive():
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
        events.close()
    model_id = finished[0]["model_id"]
    with store.connect(True) as conn:
        coverage = embedding_coverage(conn, model_id)
    pending = coverage["missing_overview_items"] if scope == "overview" else coverage["pending_chunks"]
    return {"model_id": model_id, "scope": scope, "workers": workers,
            **{key: sum(v[key] for v in finished.values()) for key in ("indexed", "computed", "reused")},
            "coverage": coverage, "pending": pending, "cancelled": cancel_started is not None,
            "status": "ready" if pending == 0 else "partial"}
