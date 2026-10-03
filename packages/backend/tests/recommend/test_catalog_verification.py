"""Catalog route reads verification and declared agent support from catalog_item when the search
rows leave them out (round-2 audit R-04/R-05), so a crawled item that the catalog verified can pass
the source_verified gate and an unverified one cannot."""

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from test_recall_multi import FakeCatalog, make, many

from orbit_backend.recommend.ranking.gates import check
from orbit_backend.recommend.recall.multi import recall_all

ROWS = {  # item_id -> (verification, metadata)
    "cat-0": ("repository_and_skill_read", {"metadata": {"origin": "crawl"}}),
    "cat-1": ("metadata_only", {}),
    "cat-2": (None, {"metadata": {"agent_support": {"claude_code": "native", "pi": "unsupported",
                                                    "kimi": "bogus"}}}),
}


class Store:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE catalog_item (item_id TEXT, verification TEXT, metadata TEXT)")
            conn.executemany("INSERT INTO catalog_item VALUES (?,?,?)",
                             [(k, v, json.dumps(m)) for k, (v, m) in ROWS.items()])

    @contextmanager
    def connect(self, readonly=False):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()


def _catalog(tmp_path):
    catalog = FakeCatalog(n=9)
    catalog.store = Store(tmp_path / "cat.db")
    return catalog


def _candidates(catalog):
    result = recall_all(make(many("identical_retries")), {}, catalog=catalog)
    return {c["rec_key"]: c for c in result["candidates"]}, result["diagnostics"]


def test_verified_crawled_item_passes_the_source_gate(tmp_path):
    cands, _ = _candidates(_catalog(tmp_path))
    inputs = {"agents": {"claude_code": 30, "codex": 2}, "sessions": {"main": 30}, "inventory": [], "profile": None}
    verdict = {key: check(cands[key], inputs, {})["checks"]["source_verified"]
               for key in ("catalog:cat-0", "catalog:cat-3", "catalog:cat-6")}
    # cat-0 is repository_and_skill_read; cat-3 / cat-6 have no catalog_item row at all
    assert verdict == {"catalog:cat-0": True, "catalog:cat-3": False, "catalog:cat-6": False}
    assert cands["catalog:cat-0"]["source"]["verified"] is True


def test_metadata_only_and_null_verification_stay_unverified(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.by_type["tool_env_failure"] = [0, 1, 2]
    cands, _ = _candidates(catalog)
    assert cands["catalog:cat-1"]["source"]["verified"] is False
    assert cands["catalog:cat-2"]["source"]["verified"] is False


def test_declared_agent_support_is_used_and_invalid_levels_dropped(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.by_type["tool_env_failure"] = [0, 2]
    cands, _ = _candidates(catalog)
    assert cands["catalog:cat-2"]["agents"] == {"claude_code": "native", "pi": "unsupported"}
    assert cands["catalog:cat-0"]["agents"] == {}  # nothing declared: every agent stays unknown
    gate = check(cands["catalog:cat-2"], {"agents": {"pi": 9}, "sessions": {"main": 9}, "inventory": [],
                                          "profile": None}, {})
    assert gate["checks"]["agent_supported"] is False


def test_without_a_store_items_are_unverified_and_a_diagnostic_says_why():
    cands, diagnostics = _candidates(FakeCatalog(n=3))
    assert cands["catalog:cat-0"]["source"]["verified"] is False
    assert {"source": "catalog.verification", "status": "unavailable", "reason": "AttributeError"} in diagnostics


def test_rows_that_carry_verification_need_no_lookup(tmp_path):
    catalog = FakeCatalog(n=3)
    original = catalog._item
    catalog._item = lambda *a: {**original(*a), "verification": "repository_and_source_read",
                                "agent_support": {"codex": "manual"}}
    catalog.store = SimpleNamespace(connect=None)  # would raise if it were called
    cands, diagnostics = _candidates(catalog)
    assert cands["catalog:cat-0"]["source"]["verified"] is True
    assert cands["catalog:cat-0"]["agents"] == {"codex": "manual"}
    assert not [d for d in diagnostics if d["source"] == "catalog.verification"]
