"""The process LRU of the analysis cache is bounded by bytes, not only by entry count.

On a real home one full pass stored projects / statistics / bottleneck_features sections of
hundreds of MB of JSON each; the uncapped LRU kept ~1 GB of that text in the analysis worker
after the task, so every worker exceeded the 1.5 GB recycle threshold.
"""

import json

import pytest
from cache_fixtures import build_home

from orbit_backend.analytics import cache as cache_module
from orbit_backend.analytics.cache import AnalysisCache, clear_memory_cache, lru_stats
from orbit_backend.analytics.inputs import Scope
from orbit_backend.analytics.service import SECTIONS
from orbit_backend.data_access.store import CanonicalStore


@pytest.fixture(autouse=True)
def isolated_memory_cache():
    clear_memory_cache()
    yield
    clear_memory_cache()


def test_lru_skips_oversized_sections_and_evicts_by_bytes(monkeypatch):
    monkeypatch.setattr(cache_module, "LRU_ENTRY_BYTES", 100)
    monkeypatch.setattr(cache_module, "LRU_BYTES", 250)
    serialized = []
    real_dumps = json.dumps
    monkeypatch.setattr(cache_module.json, "dumps",
                        lambda value, **kw: serialized.append(value) or real_dumps(value, **kw))
    cache_module._lru_put(("h", "k", "fp", "huge"), {"x": "y" * 500}, size=510)
    assert serialized == [] and cache_module._lru_get(("h", "k", "fp", "huge")) is None
    cache_module._lru_put(("h", "k", "fp", "big"), {"x": "y" * 500})  # size unknown: measured
    assert cache_module._lru_get(("h", "k", "fp", "big")) is None
    for index in range(4):
        cache_module._lru_put(("h", "k", "fp", f"s{index}"), {"x": "y" * 80})
    stats = lru_stats()
    assert stats["chars"] <= 250 and stats["entries"] == 2
    assert cache_module._lru_get(("h", "k", "fp", "s3")) == {"x": "y" * 80}
    assert cache_module._lru_get(("h", "k", "fp", "s0")) is None


def test_a_full_pass_keeps_large_sections_out_of_process_memory(tmp_path, monkeypatch):
    home, _ = build_home(tmp_path, 12)
    store = CanonicalStore(home)
    cache = AnalysisCache(store)
    monkeypatch.setattr(cache_module, "LRU_ENTRY_BYTES", 2_000)
    first = cache.sections(Scope(), list(SECTIONS), True)
    stats = lru_stats()
    assert 0 < stats["chars"] <= cache_module.LRU_BYTES
    assert all(len(text) <= 2_000 for text in cache_module._lru.values())
    # Sections left out of memory are still served, from analysis.sqlite.
    clear_memory_cache()
    again = cache.sections(Scope(), list(SECTIONS), True)
    assert again["freshness"]["cache_hit"] is True
    def plain(value):  # computed values may hold tuples; stored ones are JSON
        return json.loads(json.dumps(value, ensure_ascii=False))

    big = [name for name in SECTIONS if len(json.dumps(first[name], ensure_ascii=False)) > 2_000]
    assert big and all(plain(again[name]) == plain(first[name]) for name in big)
