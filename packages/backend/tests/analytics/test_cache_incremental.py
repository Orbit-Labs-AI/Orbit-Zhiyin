"""Cached, partially cached and cold analyses are identical; only changed trees recompute."""

import json
import sqlite3

import pytest
from cache_fixtures import build_home, normalized, reingest, write_session

from tandem_backend.analytics import cache as cache_module
from tandem_backend.analytics.cache import AnalysisCache, clear_memory_cache
from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.history import history_for, recorded
from tandem_backend.analytics.inputs import Scope
from tandem_backend.analytics.service import (
    ROW_STATS,
    SECTIONS,
    _row_sessions,
    analyze_bundle,
    analyze_store,
    compute_row_cores,
)
from tandem_backend.data_access.store import CanonicalStore


def reference(store, scope, with_text):
    """The pure single-pass engine on a fresh bundle: the ground truth for every cache path."""
    return json.loads(json.dumps(analyze_bundle(store.analysis_bundle(scope), scope, with_text)))


def drop_sections(store):
    clear_memory_cache()
    with history_for(store).connect() as db:
        db.execute("DELETE FROM analysis_section")


def drop_rows(store):
    with history_for(store).connect() as db:
        db.execute("DELETE FROM session_result")


@pytest.fixture(autouse=True)
def isolated_memory_cache():
    clear_memory_cache()
    yield
    clear_memory_cache()


@pytest.mark.parametrize(
    ("scope", "with_text"),
    [
        (Scope(), False),
        (Scope(), True),
        (Scope(from_ts=1769990400000, until_ts=1771200000000, display_timezone="Asia/Shanghai"), False),
        (Scope(model_ids=["fixture-model-1"]), False),
    ],
)
def test_cold_row_hit_and_full_hit_paths_are_identical(tmp_path, scope, with_text):
    home, source = build_home(tmp_path, 24)
    store = CanonicalStore(home)
    expected = normalized(reference(store, scope, with_text))

    cold = analyze_store(store, scope, with_text)
    assert cold["freshness"]["cache_hit"] is False
    assert cold["freshness"]["rows"] == {"computed": cold["freshness"]["rows"]["computed"], "reused": 0}
    assert normalized(cold) == expected

    hit = analyze_store(store, scope, with_text)
    assert hit["freshness"]["cache_hit"] is True
    assert normalized(hit) == expected

    # Section cache gone, session rows still valid: every row comes from session_result.
    drop_sections(store)
    rows_only = analyze_store(store, scope, with_text)
    assert rows_only["freshness"]["cache_hit"] is False
    assert rows_only["freshness"]["rows"]["computed"] == 0
    assert rows_only["freshness"]["rows"]["reused"] > 0
    assert normalized(rows_only) == expected

    # One changed session: exactly one row is recomputed, the result matches a cold run.
    write_session(source / "sessions", 3, follow_up="再补一个用例，并解释原因。")
    reingest(home, source)
    changed_expected = normalized(reference(store, scope, with_text))
    assert changed_expected != expected
    partial = analyze_store(store, scope, with_text)
    assert partial["freshness"]["rows"]["computed"] == 1  # session 3 is in every scope above
    assert normalized(partial) == changed_expected
    drop_sections(store)
    drop_rows(store)
    assert normalized(analyze_store(store, scope, with_text)) == changed_expected


def test_every_section_alone_equals_the_complete_result(tmp_path):
    home, _ = build_home(tmp_path, 12)
    store = CanonicalStore(home)
    expected = json.loads(normalized(reference(store, Scope(), False)))
    cache = AnalysisCache(store)
    for name in SECTIONS:
        drop_sections(store)
        result = json.loads(normalized(cache.sections(Scope(), [name], with_text=False)))
        assert result[name] == expected[name], name
        assert {k: v for k, v in result.items() if k != name} == {
            k: v for k, v in expected.items() if k not in SECTIONS
        }


def test_parallel_chunks_equal_serial_rows(tmp_path, monkeypatch):
    home, _ = build_home(tmp_path, 9)
    store = CanonicalStore(home)
    bundle = store.analysis_bundle(Scope())
    context = AnalysisContext.select(bundle, Scope())
    sids = [s["session_uid"] for s in _row_sessions(context)]
    monkeypatch.setattr("tandem_backend.analytics.service.PARALLEL_CHUNK", 4)
    before = ROW_STATS["parallel_chunks"]
    parallel = compute_row_cores(context, sids, parallel=True)
    assert ROW_STATS["parallel_chunks"] - before == 3  # really ran in worker processes
    serial = compute_row_cores(context, sids, parallel=False)
    assert json.dumps(parallel, sort_keys=True) == json.dumps(serial, sort_keys=True)


def test_appending_one_session_to_500_recomputes_one_root(tmp_path):
    home, source = build_home(tmp_path, 500)
    store = CanonicalStore(home)
    first = AnalysisCache(store).sections(Scope(), ["overview", "sessions"])
    assert first["freshness"]["rows"] == {"computed": 500, "reused": 0}
    computed = ROW_STATS["computed"]
    write_session(source / "sessions", 500)
    reingest(home, source)
    second = AnalysisCache(store).sections(Scope(), ["overview", "sessions"])
    assert ROW_STATS["computed"] - computed == 1  # counting hook: one new root only
    assert second["freshness"]["rows"] == {"computed": 1, "reused": 500}
    assert second["freshness"]["input_fp"] != first["freshness"]["input_fp"]
    assert second["effective_samples"]["main_sessions"] == 501
    assert len(second["sessions"]) == 501


def test_version_and_fingerprint_changes_invalidate(tmp_path, monkeypatch):
    home, _ = build_home(tmp_path, 6)
    store = CanonicalStore(home)
    cache = AnalysisCache(store)
    base = cache.sections(Scope(), ["overview"])
    assert cache.sections(Scope(), ["overview"])["freshness"]["cache_hit"] is True

    # Moving one event to a new rowid (same count, same seq) invalidates exactly its tree.
    connection = sqlite3.connect(home / "tandem.db")
    connection.execute("PRAGMA foreign_keys=OFF")
    rowid = connection.execute("SELECT max(rowid) FROM event").fetchone()[0]
    connection.execute("UPDATE event SET rowid=? WHERE rowid=?", (rowid + 100, rowid))
    connection.commit()
    connection.close()
    moved = cache.sections(Scope(), ["overview"])
    assert moved["freshness"]["cache_hit"] is False
    assert moved["freshness"]["rows"] == {"computed": 1, "reused": 5}
    assert moved["freshness"]["input_fp"] != base["freshness"]["input_fp"]

    monkeypatch.setattr("tandem_backend.analytics.FEATURE_VERSION", "feature-test-bump")
    bumped = cache.sections(Scope(), ["overview"])
    assert bumped["freshness"]["cache_hit"] is False
    assert bumped["freshness"]["rows"] == {"computed": 6, "reused": 0}
    assert bumped["freshness"]["algo_version"] != base["freshness"]["algo_version"]
    monkeypatch.undo()

    from tandem_backend.analytics.products.contracts import RULE_VERSIONS

    monkeypatch.setitem(RULE_VERSIONS, "task", "task-test-bump")
    ruled = cache.sections(Scope(), ["overview"])
    assert ruled["freshness"]["cache_hit"] is False
    assert ruled["freshness"]["rows"] == {"computed": 6, "reused": 0}
    monkeypatch.undo()
    # Only the current algorithm version's rows are kept per root.
    with history_for(store).connect() as db:
        versions = db.execute("SELECT DISTINCT algo_version FROM session_result").fetchall()
    assert len(versions) == 1


def test_exclusions_shrink_every_analysis_and_restore(tmp_path):
    home, _ = build_home(tmp_path, 8)
    store = CanonicalStore(home)
    before = analyze_store(store, with_text=False)
    target = before["sessions"][0]["session_uid"]
    history = history_for(store)
    history.exclude(target, "fixture")
    excluded = analyze_store(store, with_text=False)
    assert target in excluded["scope"]["excluded_session_uids"]
    assert excluded["effective_samples"]["main_sessions"] == before["effective_samples"]["main_sessions"] - 1
    assert excluded["effective_samples"]["human_messages"] < before["effective_samples"]["human_messages"]
    assert target not in {row["session_uid"] for row in excluded["sessions"]}
    history.include(target)
    restored = analyze_store(store, with_text=False)
    assert restored["freshness"]["cache_hit"] is True
    assert normalized(restored) == normalized(before)


def test_recorded_serves_verified_hits_as_light_runs(tmp_path):
    home, _ = build_home(tmp_path, 3)
    store = CanonicalStore(home)
    calls = []

    def compute():
        calls.append(1)
        return {"value": len(calls), "nested": {"b": 1, "a": 2}}

    first = recorded(store, "fixture", {"x": 1}, compute)
    second = recorded(store, "fixture", {"x": 1}, compute)
    assert calls == [1] and second == first
    assert json.dumps(second) == json.dumps(first)  # key order survives the cache
    runs = history_for(store).list_runs(engine="fixture")["items"]
    assert [r["cache_hit"] for r in runs] == [1, 0]
    assert len({r["snapshot_id"] for r in runs}) == 1
    with history_for(store).connect() as db:
        db.execute("UPDATE analysis_snapshot SET payload=? WHERE snapshot_id=?",
                   (b"corrupt", runs[0]["snapshot_id"]))
    with pytest.raises(ValueError, match="corrupt"):
        recorded(store, "fixture", {"x": 1}, compute)
    assert calls == [1]


def test_tampered_section_is_reported_not_recomputed(tmp_path):
    import zlib

    home, _ = build_home(tmp_path, 3)
    store = CanonicalStore(home)
    cache = AnalysisCache(store)
    cache.sections(Scope(), ["overview"])
    clear_memory_cache()
    with history_for(store).connect() as db:
        payload = zlib.decompress(
            db.execute("SELECT payload FROM analysis_section WHERE section='overview'").fetchone()[0]
        )
        tampered = payload.replace(b'"sessions":3', b'"sessions":4')
        assert tampered != payload and len(tampered) == len(payload)
        db.execute("UPDATE analysis_section SET payload=? WHERE section='overview'",
                   (zlib.compress(tampered),))
    with pytest.raises(ValueError, match="checksum"):
        cache.sections(Scope(), ["overview"])


def test_legacy_stores_are_not_cached(tmp_path):
    from tandem_backend.store import Store

    store = Store(tmp_path / "legacy.sqlite")
    assert not cache_module.supports_cache(store)
    result = analyze_store(store, with_text=False)
    assert "freshness" not in result
