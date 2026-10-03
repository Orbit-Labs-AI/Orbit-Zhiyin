"""Opt-in integration test; CI/unit tests never download a model or use cloud inference."""

import os

import pytest

from orbit_catalog.contracts import MatchRequest, Record, Resource, SourceSpec
from orbit_catalog.search import search
from orbit_catalog.store import CatalogStore
from orbit_catalog.vectors import LocalE5Encoder, index_embeddings

from .test_storage import publish


@pytest.mark.skipif(not os.environ.get("ORBIT_TEST_E5_DIR"), reason="local E5 snapshot not supplied")
def test_local_multilingual_recall(tmp_path):
    encoder = LocalE5Encoder(os.environ["ORBIT_TEST_E5_DIR"])
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    documents = {
        "debug": "Systematic debugging: reproduce a failing test, investigate its root cause, and verify the fix.",
        "web": "Build accessible web interfaces: keyboard navigation, screen reader labels, semantic HTML and contrast.",
        "paper": "Verify citations in scientific papers. Check the original sources and whether each claim is supported.",
    }
    rows = [Record(native_id=key, resource=Resource(item_id=key, type="skill", name=key, summary=value, url="https://example.org"))
            for key, value in documents.items()]
    publish(store, rows)
    assert index_embeddings(store, encoder)["pending"] == 0
    for query, expected in [("排查自动化测试反复失败的原因", "debug"), ("改善网页的无障碍访问", "web"), ("核对论文中的引用是否真实", "paper")]:
        result = search(store, MatchRequest(text=query, limit=1), encoder)
        assert result["items"][0]["item_id"] == expected
        assert result["vector"]["status"] == "ready"


@pytest.mark.skipif(not os.environ.get("ORBIT_TEST_E5_DIR"), reason="local E5 snapshot not supplied")
def test_parallel_e5_ranges_and_resume(tmp_path):
    from orbit_catalog.vectors import index_embeddings_parallel
    store = CatalogStore(tmp_path / "parallel.db")
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test")])
    rows = [Record(native_id=str(i), resource=Resource(item_id=f"parallel:{i}", type="skill", name=f"Debug {i}",
            summary="Investigate root causes and verify the fix.", url="https://example.org")) for i in range(8)]
    publish(store, rows)
    cancelled = index_embeddings_parallel(store, os.environ["ORBIT_TEST_E5_DIR"], workers=2, cancelled=lambda: True)
    assert cancelled["cancelled"] and cancelled["computed"] == 0
    assert cancelled["coverage"]["overview_items"] == 0
    updates = []
    result = index_embeddings_parallel(store, os.environ["ORBIT_TEST_E5_DIR"], workers=2, batch_size=2,
                                       scope="overview", progress=updates.append)
    assert result["coverage"]["overview_items"] == 8
    assert result["computed"] == 8 and result["workers"] == 2
    assert updates and updates[-1]["computed"] == 8
    assert index_embeddings_parallel(store, os.environ["ORBIT_TEST_E5_DIR"], workers=2)["computed"] == 0
