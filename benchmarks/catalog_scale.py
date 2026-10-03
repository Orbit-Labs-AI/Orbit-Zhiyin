"""100k-resource vector infrastructure benchmark; synthetic projections and toy vectors only.

This deliberately bypasses import/feature extraction and real E5 inference to isolate
keyset materialization, resume, matrix loading and exact scoring. It makes no semantic
quality or real-model throughput claim. Run: uv run python benchmarks/catalog_scale.py
"""

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

import numpy as np

from orbit_catalog.contracts import Page, Record, Resource, SourceSpec, digest
from orbit_catalog.store import CatalogStore
from orbit_catalog.vectors import blocked_scores, index_embeddings


class ScaleEncoder:
    model_id = "benchmark:constant-384-not-semantic"
    dimensions = 384
    descriptor = {"encoder": "constant-infrastructure-benchmark-only", "dimensions": 384}

    def encode(self, texts, *, query=False):
        return np.ones((len(texts), self.dimensions), dtype=np.float32)


class ScaleStore(CatalogStore):
    """Generated text access isolates indexing cost from source parsing/decompression."""
    chunks_per_item = 3

    def chunk_texts(self, conn, item_id):
        return [f"Synthetic infrastructure fixture {item_id}, chunk {j}." for j in range(self.chunks_per_item)]


def prepare(store, count):
    store.register([SourceSpec(source_id="scale", kind="bundle", url="bundled:scale")])
    run = store.begin_run("scale")
    store.stage(run["run_id"], Page(records=[Record(native_id="template", resource=Resource(
        item_id="template", type="skill", name="Synthetic scale template", summary="Fixture",
        url="https://example.org/fixture"))], complete=True))
    store.publish(run["run_id"])
    with store.writer(), store.connect() as conn:
        template = dict(conn.execute("SELECT * FROM catalog_item WHERE item_id='template'").fetchone())
        conn.execute("DELETE FROM resource_chunk")
        conn.execute("DELETE FROM catalog_item")
        columns = list(template)
        sql = f"INSERT INTO catalog_item({','.join(columns)}) VALUES({','.join('?' for _ in columns)})"
        for start in range(0, count, 1000):
            items, chunks = [], []
            for i in range(start, min(start + 1000, count)):
                item_id = f"scale:{i:08d}"
                item = {**template, "item_id": item_id, "content_hash": item_id}
                items.append(tuple(item[c] for c in columns))
                for j, text in enumerate(store.chunk_texts(conn, item_id)):
                    chunks.append((item_id, j, i * store.chunks_per_item + j + 1,
                                   "metadata" if j == 0 else "body", "Fixture",
                                   bytes.fromhex(digest(text)[:32]), 1))
            conn.executemany(sql, items)
            conn.executemany("INSERT INTO resource_chunk VALUES(?,?,?,?,?,?,?)", chunks)
        store._bump(conn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, default=100000)
    parser.add_argument("--chunks", type=int, default=3)
    parser.add_argument("--queries", type=int, default=10)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="orbit-scale-") as directory:
        store = ScaleStore(Path(directory) / "catalog.db")
        store.chunks_per_item = args.chunks
        prepare(store, args.items)
        encoder = ScaleEncoder()
        started = time.perf_counter()
        result = index_embeddings(store, encoder, batch_size=512)
        index_seconds = time.perf_counter() - started
        started = time.perf_counter()
        resumed = index_embeddings(store, encoder, batch_size=512)
        resume_seconds = time.perf_counter() - started
        started = time.perf_counter()
        with store.reader() as conn:
            index = store.index(conn)
            matrix, owners, _ = index.matrix(conn, encoder.model_id, encoder.dimensions)
        load_seconds = time.perf_counter() - started
        query = np.ones(encoder.dimensions, dtype=np.float32) / np.sqrt(encoder.dimensions)
        samples = []
        for _ in range(args.queries):
            started = time.perf_counter()
            scores = blocked_scores(matrix, query)
            by_item = np.full(len(index), -np.inf, dtype=np.float32)
            np.maximum.at(by_item, owners, scores)
            np.argpartition(-by_item, min(100, len(by_item) - 1))[:100]
            samples.append((time.perf_counter() - started) * 1000)
        print(json.dumps({"fixture": "synthetic-projections/constant-vectors-not-E5",
                          "items": args.items, "chunks": len(matrix), "dimensions": encoder.dimensions,
                          "index_seconds": round(index_seconds, 3), "resume_seconds": round(resume_seconds, 3),
                          "resume_computed": resumed["computed"], "snapshot_load_seconds": round(load_seconds, 3),
                          "matrix_mib": round(matrix.nbytes / 2**20, 2), "memory_mapped": isinstance(matrix, np.memmap),
                          "exact_score_and_owner_top100_ms": {"p50": round(statistics.median(samples), 2),
                              "max": round(max(samples), 2)}, "coverage": result["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
