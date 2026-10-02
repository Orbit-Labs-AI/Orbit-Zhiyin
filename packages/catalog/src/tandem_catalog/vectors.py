"""Versioned local embeddings, resumable materialization, exact cosine search primitives."""

import hashlib
import time
from pathlib import Path
from typing import Protocol

import numpy as np

from .contracts import canonical_json, digest


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

    def __init__(self, directory: str | Path, threads: int = 4):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        ort.disable_telemetry_events()
        directory = Path(directory).expanduser().resolve()
        model_path, tokenizer_path = directory / "onnx/model.onnx", directory / "onnx/tokenizer.json"
        def sha(path):
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        self.descriptor = {"encoder": "multilingual-e5-small-onnx", "model_sha256": sha(model_path),
                           "tokenizer_sha256": sha(tokenizer_path), "dimensions": self.dimensions,
                           "query_prefix": "query: ", "document_prefix": "passage: ",
                           "pooling": "masked-mean/window-mean/l2-v1", "max_tokens": 512, "overlap": 64,
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
        width = 512 - len(prefix) - 2
        for index, encoding in enumerate(self.tokenizer.encode_batch(texts, add_special_tokens=False)):
            ids = encoding.ids
            for start in range(0, max(1, len(ids)), width - 64):
                frames.append([self.bos, *prefix, *ids[start:start + width], self.eos])
                owners.append(index)
                if start + width >= len(ids):
                    break
        results = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        counts = np.zeros((len(texts), 1), dtype=np.float32)
        inputs = {i.name for i in self.session.get_inputs()}
        for start in range(0, len(frames), 8):
            batch = frames[start:start + 8]
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


def register_model(store, encoder: Encoder):
    if not 1 <= encoder.dimensions <= 8192:
        raise ValueError("invalid_embedding_dimensions")
    with store.writer(), store.connect() as conn:
        row = conn.execute("SELECT * FROM embedding_model WHERE model_id=?", (encoder.model_id,)).fetchone()
        descriptor = canonical_json(encoder.descriptor)
        if row and (row["dimensions"] != encoder.dimensions or row["descriptor"] != descriptor):
            raise ValueError("embedding_model_identity_conflict")
        conn.execute("INSERT OR IGNORE INTO embedding_model VALUES(?,?,?,?)",
                     (encoder.model_id, encoder.dimensions, descriptor, int(time.time() * 1000)))


def index_embeddings(store, encoder: Encoder, *, batch_size=32, max_chunks=None, cancelled=lambda: False):
    """Missing (current chunk, model) pairs are the durable queue; completed batches survive crashes."""
    if batch_size < 1 or (max_chunks is not None and max_chunks < 0):
        raise ValueError("invalid_embedding_batch_limit")
    register_model(store, encoder)
    indexed, computed, reused = 0, 0, 0
    while not cancelled() and (max_chunks is None or indexed < max_chunks):
        limit = min(batch_size, max_chunks - indexed) if max_chunks is not None else batch_size
        with store.connect(True) as conn:
            rows = conn.execute("SELECT c.* FROM resource_chunk c JOIN catalog_item i USING(item_id) LEFT JOIN chunk_embedding e "
                                "ON e.chunk_id=c.chunk_id AND e.model_id=? WHERE e.chunk_id IS NULL "
                                "ORDER BY CASE i.type WHEN 'skill' THEN 0 WHEN 'workflow' THEN 1 WHEN 'rule' THEN 2 "
                                "WHEN 'hook' THEN 3 WHEN 'command' THEN 4 WHEN 'subagent' THEN 5 WHEN 'plugin' THEN 6 "
                                "WHEN 'mcp_server' THEN 7 ELSE 8 END,CASE c.field WHEN 'metadata' THEN 0 ELSE 1 END,"
                                "c.item_id,c.ordinal LIMIT ?", (encoder.model_id, limit)).fetchall()
            if not rows:
                break
            cache = {}
            for row in rows:
                cached = conn.execute("SELECT vector FROM embedding_cache WHERE model_id=? AND text_hash=?",
                                      (encoder.model_id, row["text_hash"])).fetchone()
                if cached:
                    cache[row["text_hash"]] = cached[0]
        missing = {row["text_hash"]: row["text"] for row in rows if row["text_hash"] not in cache}
        if missing:
            encoded = normalize_vectors(encoder.encode(list(missing.values())), len(missing), encoder.dimensions)
            cache.update({key: vector.tobytes() for key, vector in zip(missing, encoded, strict=True)})
            computed += len(missing)
        now = int(time.time() * 1000)
        with store.writer(), store.connect() as conn:
            for text_hash, blob in cache.items():
                conn.execute("INSERT OR IGNORE INTO embedding_cache VALUES(?,?,?,?)",
                             (encoder.model_id, text_hash, encoder.dimensions, blob))
            for row in rows:
                # A sync may have changed this document while inference was running.
                cursor = conn.execute("INSERT OR IGNORE INTO chunk_embedding "
                                      "SELECT chunk_id,?,text_hash,?,?,? FROM resource_chunk WHERE chunk_id=? AND text_hash=?",
                                      (encoder.model_id, encoder.dimensions, cache[row["text_hash"]], now, row["chunk_id"], row["text_hash"]))
                indexed += cursor.rowcount
                reused += int(row["text_hash"] not in missing and cursor.rowcount > 0)
            conn.execute("UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    with store.connect(True) as conn:
        pending = conn.execute("SELECT count(*) FROM resource_chunk c LEFT JOIN chunk_embedding e "
                               "ON e.chunk_id=c.chunk_id AND e.model_id=? WHERE e.chunk_id IS NULL", (encoder.model_id,)).fetchone()[0]
    return {"model_id": encoder.model_id, "indexed": indexed, "computed": computed, "reused": reused,
            "pending": pending, "status": "ready" if pending == 0 else "partial"}
