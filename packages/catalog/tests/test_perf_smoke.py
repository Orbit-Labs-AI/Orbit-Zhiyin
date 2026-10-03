"""Coarse latency guard (N=1500, 5x slack); benchmarks/catalog_bench.py holds the real targets."""

import statistics
import time

from tandem_catalog import query
from tandem_catalog.contracts import MatchRequest, Page, Record, Resource, SourceSpec
from tandem_catalog.search import search
from tandem_catalog.store import CatalogStore

WORDS = "retry flaky pytest debug cache build deploy docker review prompt token latency index schema agent hook".split()


def test_lexical_and_list_latency_smoke(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="bench", kind="bundle", url="bundled:test")])
    records = []
    for n in range(1500):
        words = " ".join(WORDS[(n * 7 + k) % len(WORDS)] for k in range(60))
        records.append(Record(native_id=str(n), resource=Resource(
            item_id=f"b{n}", type="skill", name=f"{WORDS[n % len(WORDS)]} helper {n}", summary=words[:120],
            url="https://x", body="# Body\n" + (words + "\n") * 8, body_policy="licensed")))
    run = store.begin_run("bench")
    store.stage(run["run_id"], Page(records=records, complete=True))
    store.publish(run["run_id"])
    search(store, MatchRequest(text="warm"))
    timings = []
    for n in range(60):
        start = time.perf_counter()
        # Every WORD is in every document (no discriminating power); the number names one item.
        assert search(store, MatchRequest(text=f"{WORDS[n % len(WORDS)]} helper {n * 17}"))["items"]
        timings.append(time.perf_counter() - start)
    p95 = statistics.quantiles(timings, n=20)[-1] * 1000
    assert p95 < 100 * 5, p95
    start = time.perf_counter()
    for _ in range(50):
        query.list_items(store, sort="installs")
    assert (time.perf_counter() - start) / 50 * 1000 < 5 * 5
