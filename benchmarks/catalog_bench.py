"""Catalog storage/retrieval benchmark on deterministic synthetic data (no network, no ONNX).

    uv run python benchmarks/catalog_bench.py --items 20000 --seed 7 [--embeddings] [--json out.json] [--check]

Measures stage/publish, unchanged republish, database size, and p50/p95 latency of lexical,
semantic, hybrid, list, deep list page, facets (cold cache) and detail reads. ``--check``
asserts the v3 targets when ``--items >= 20000``; smaller runs only report.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import statistics
import sys
import tempfile
import time
import zlib
from pathlib import Path

import numpy as np

from tandem_catalog import query
from tandem_catalog.contracts import Feature, MatchRequest, Page, Record, Resource, SourceSpec
from tandem_catalog.features import lexical_tokens
from tandem_catalog.search import _semantic, search
from tandem_catalog.store import CatalogStore
from tandem_catalog.vectors import index_embeddings

KINDS = ["skill", "plugin", "marketplace", "mcp_server", "hook", "subagent", "command", "rule", "workflow",
         "guide", "output_style", "lsp_server"]
AGENTS = ["claude_code", "codex", "copilot", "gemini"]
HAN = "测试调试文档性能优化验证部署缓存索引检索代码审查重构日志网络安全权限配置数据模型推荐分析"
TARGETS = {"build_s": 40, "republish_unchanged_s": 3, "db_mb": 160, "lexical_p50": 30, "lexical_p95": 80,
           "hybrid_p50": 45, "list_p50": 5, "detail_p50": 8, "facets_p50": 15}


class ToyHashEncoder:
    """Token-hash bag of words, L2-normalised; a deterministic stand-in for E5 in benchmarks."""
    model_id = "bench:toy-hash-384"
    dimensions = 384
    descriptor = {"encoder": "toy-hash", "dimensions": 384}

    def encode(self, texts, *, query=False):
        out = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in lexical_tokens(text)[:400]:
                h = zlib.crc32(token.encode())
                out[row, h % self.dimensions] += 1.0 if h & 1 << 20 else -1.0
            out[row, row % self.dimensions] += 1e-3  # Never an all-zero vector.
        return out


def vocabulary(rng: random.Random) -> list[str]:
    syllables = ["ka", "ro", "ti", "len", "mor", "sa", "qui", "dex", "pa", "zu", "ver", "ion", "bel", "tra", "no", "gim"]
    words = sorted({"".join(rng.choice(syllables) for _ in range(rng.randint(2, 4))) for _ in range(6000)})
    words += [HAN[i] + HAN[j] for i in range(0, len(HAN), 2) for j in range(1, len(HAN), 3)]
    rng.shuffle(words)
    return words


def generate(n: int, seed: int) -> tuple[list[Record], list[str]]:
    rng = random.Random(seed)
    words = vocabulary(rng)
    weights = [1 / (rank + 1) for rank in range(len(words))]  # Zipf(1).
    cumulative = list(np.cumsum(weights))

    def text(count):
        return " ".join(rng.choices(words, cum_weights=cumulative, k=count))

    records = []
    for i in range(n):
        if i > 20 and rng.random() < 0.05:  # 5% exact content copies under another id.
            source = records[rng.randrange(len(records))].resource
            resource = source.model_copy(update={"item_id": f"bench:{i}"})
        else:
            sections = [f"## {text(3)}\n{text(125)}" for _ in range(5)]
            features = [Feature(feature=rng.choice(["domain", "software", "command", "tool_kind"]),
                                value=rng.choice(words[:300]), origin="declared") for _ in range(rng.randint(3, 8))]
            resource = Resource(
                item_id=f"bench:{i}", type=KINDS[i % len(KINDS)], name=text(rng.randint(2, 4)), summary=text(25),
                url=f"https://example.org/{i}", body="\n\n".join(sections), body_policy="licensed", license="MIT",
                agents=rng.sample(AGENTS, rng.randint(1, 3)), difficulty=rng.randint(1, 4), features=features,
                popularity={"installs": int(rng.paretovariate(1.2) * 10), "stars": rng.randint(0, 5000)},
                metadata={"source_updated_at": 1_700_000_000_000 + rng.randint(0, 10**10), "author": f"dev{i % 97}"})
        records.append(Record(native_id=f"n{i}", resource=resource, raw={"i": i}))
    return records, words


def stage_and_publish(store, records) -> tuple[float, float]:
    start = time.perf_counter()
    run = store.begin_run("bench")
    for page in range(0, len(records), 500):
        store.stage(run["run_id"], Page(records=records[page:page + 500], complete=page + 500 >= len(records)))
    staged = time.perf_counter()
    store.publish(run["run_id"])
    return staged - start, time.perf_counter() - staged


def db_size(store) -> tuple[float, dict]:
    with sqlite3.connect(store.path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        try:
            tables = {name: round(size / 2**20, 2) for name, size in conn.execute(
                "SELECT name,sum(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC")}
        except sqlite3.OperationalError:
            tables = {}
    return store.path.stat().st_size / 2**20, tables


def timed(fn, inputs) -> dict:
    samples = []
    for value in inputs:
        start = time.perf_counter()
        fn(value)
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {"p50": round(statistics.median(samples), 2), "p95": round(samples[int(len(samples) * 0.95) - 1], 2),
            "n": len(samples)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--items", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--embeddings", action="store_true")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dir", type=Path, help="keep the database here instead of a temp dir")
    args = parser.parse_args()
    records, words = generate(args.items, args.seed)
    rng = random.Random(args.seed + 1)
    with tempfile.TemporaryDirectory() as tmp:
        home = args.dir or Path(tmp)
        store = CatalogStore(home / "catalog.db")
        store.register([SourceSpec(source_id="bench", kind="bundle", url="bundled:bench")])
        result = {"items": args.items, "seed": args.seed}
        result["build_stage_s"], result["build_publish_s"] = (round(v, 2) for v in stage_and_publish(store, records))
        stage_s, publish_s = stage_and_publish(store, records)
        result["republish_stage_s"], result["republish_unchanged_s"] = round(stage_s, 2), round(publish_s, 2)
        db_mb, tables = db_size(store)
        result["db_mb"], result["db_mb_by_table"] = round(db_mb, 1), tables
        encoder = None
        if args.embeddings:
            encoder = ToyHashEncoder()
            start = time.perf_counter()
            index_embeddings(store, encoder, batch_size=512)
            result["embed_s"] = round(time.perf_counter() - start, 1)
            with_vectors, tables = db_size(store)
            result["db_mb_with_vectors"] = round(with_vectors, 1)
            result["vectors_mb"] = tables.get("embedding_cache", round(with_vectors - db_mb, 1))
        mid = words[30:1500]
        texts = [" ".join(rng.sample(mid, rng.randint(1, 3))) for _ in range(args.queries)]
        start = time.perf_counter()
        store.index()
        result["index_build_ms"] = round((time.perf_counter() - start) * 1000, 1)
        search(store, MatchRequest(text=texts[0]), encoder)  # Warm index matrices and query cache paths.
        result["lexical"] = timed(lambda t: search(store, MatchRequest(text=t)), texts)
        features = [[Feature(feature="domain", value=rng.choice(words[:300]))] for _ in texts]
        result["hybrid"] = timed(lambda i: search(store, MatchRequest(text=texts[i], features=features[i]), encoder),
                                 range(len(texts)))
        if encoder is not None:
            def semantic(text):
                with store.reader() as conn:
                    index = store.index(conn)
                    _semantic(conn, index, index.mask(MatchRequest(text=text), conn), encoder, text, 100)
            result["semantic"] = timed(semantic, [t + " semantic" for t in texts])
        sorts = ["updated", "installs", "stars", "name"]
        result["list"] = timed(lambda i: query.list_items(store, kinds=[KINDS[i % 12]] if i % 3 else [],
                                                          sort=sorts[i % 4]), range(args.queries))
        deep = query.list_items(store, sort="updated", limit=30)
        for _ in range(min(50, args.items // 60)):
            deep = query.list_items(store, sort="updated", limit=30, cursor=deep["next_cursor"])
        cursor = deep["next_cursor"]
        result["list_deep_page"] = timed(lambda _: query.list_items(store, sort="updated", limit=30, cursor=cursor),
                                         range(args.queries))

        def facets(i):
            query._CACHE.clear()  # Cold: measure SQL, not the generation cache.
            query.facets(store, kinds=[KINDS[i % 12]] if i % 2 else [], agents=[AGENTS[i % 4]] if i % 3 else [])
        result["facets"] = timed(facets, range(args.queries))
        ids = [f"bench:{rng.randrange(args.items)}" for _ in range(args.queries)]
        result["detail"] = timed(lambda item_id: query.get_item(store, item_id), ids)
        result["verify_ok"] = store.verify()["ok"]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    if args.check and args.items >= 20000:
        failures = [name for name, ok in {
            "build_s": result["build_stage_s"] + result["build_publish_s"] <= TARGETS["build_s"],
            "republish_unchanged_s": result["republish_unchanged_s"] <= TARGETS["republish_unchanged_s"],
            "db_mb": result["db_mb"] <= TARGETS["db_mb"],
            "lexical_p50": result["lexical"]["p50"] <= TARGETS["lexical_p50"],
            "lexical_p95": result["lexical"]["p95"] <= TARGETS["lexical_p95"],
            "hybrid_p50": result["hybrid"]["p50"] <= TARGETS["hybrid_p50"],
            "list_p50": result["list"]["p50"] <= TARGETS["list_p50"],
            "detail_p50": result["detail"]["p50"] <= TARGETS["detail_p50"],
            "facets_p50": result["facets"]["p50"] <= TARGETS["facets_p50"],
        }.items() if not ok]
        if failures:
            print("targets missed: " + ", ".join(failures), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
