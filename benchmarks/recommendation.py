"""Timing boundary: recommend only, using synthetic copies of reviewed metadata."""

import statistics
import time
from copy import deepcopy

from tandem_backend.recommend.service import recommend


def benchmark(analysis, items, context):
    rows = []
    for size, repeats in ((4, 20), (1000, 5)):
        catalog = [deepcopy(items[i % len(items)]) for i in range(size)]
        for i, item in enumerate(catalog):
            item["identity"]["id"] += f":synthetic-load-{i:04d}"
        timings = []
        for _ in range(repeats):
            start = time.perf_counter()
            recommend(analysis, catalog=catalog, context=context)
            timings.append((time.perf_counter() - start) * 1000)
        rows.append({"items": size, "runs": repeats, "median_ms": round(statistics.median(timings), 2),
                     "max_ms": round(max(timings), 2), "dataset": "synthetic repetitions of 4 reviewed metadata records"})
    return rows
