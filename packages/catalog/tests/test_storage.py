import sqlite3

import pytest

from tandem_catalog.contracts import Feature, Page, Record, Resource, SourceSpec
from tandem_catalog.features import chunks, lexical_tokens
from tandem_catalog.store import CatalogBusy, CatalogStore


@pytest.fixture
def store(tmp_path):
    result = CatalogStore(tmp_path / "catalog.db")
    result.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:test", priority=90),
                     SourceSpec(source_id="secondary", kind="bundle", url="bundled:test", priority=30)])
    return result


def record(name="debugger", **kwargs):
    return Record(native_id=name, resource=Resource(item_id=name, type="skill", name=name,
                  summary="Debug failing tests 调试重复失败", url="https://example.org/skill", **kwargs))


def publish(store, rows, source="primary", revision="r1", mode="full"):
    run = store.begin_run(source)
    store.stage(run["run_id"], Page(records=rows, complete=True, mode=mode, revision=revision, watermark="2026-10-02T00:00:00Z"))
    return store.publish(run["run_id"])


def test_schema_reopens_and_rejects_another_database(tmp_path):
    path = tmp_path / "catalog.db"
    CatalogStore(path)
    assert CatalogStore(path).stats()["items"] == 0
    other = tmp_path / "tandem.db"
    with sqlite3.connect(other) as conn:
        conn.execute("CREATE TABLE sessions(id TEXT)")
    with pytest.raises(ValueError, match="not_a_catalog"):
        CatalogStore(other)
    with sqlite3.connect(other) as conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_staged_pages_invisible_and_resume_without_cursor_advance(store):
    publish(store, [record("old")])
    run = store.begin_run("primary")
    store.stage(run["run_id"], Page(records=[record("new")], complete=False, checkpoint={"cursor": "page2"}, revision="r2"))
    store.finish_interrupted(run["run_id"], "http_503")
    assert store.detail("new") is None
    assert store.detail("old")["resource"]["status"] == "active"
    assert store.sources()[0]["revision"] == "r1"
    resumed = store.begin_run("primary")
    assert resumed["run_id"] == run["run_id"]
    assert resumed["checkpoint"] == {"cursor": "page2"}
    store.stage(run["run_id"], Page(records=[record("other")], complete=True, revision="r2"))
    result = store.publish(run["run_id"])
    assert result["seen"] == 2
    assert store.detail("old")["resource"]["status"] == "deleted"
    assert store.stats()["items"] == 2


def test_publish_rolls_back_all_projections_on_failure(store, monkeypatch):
    publish(store, [record("old")])
    run = store.begin_run("primary")
    store.stage(run["run_id"], Page(records=[record("new")], complete=True, revision="r2"))
    def broken(*args):
        raise RuntimeError("interrupted")
    monkeypatch.setattr(store, "_materialize", broken)
    with pytest.raises(RuntimeError, match="interrupted"):
        store.publish(run["run_id"])
    assert store.sources()[0]["revision"] == "r1"
    assert store.detail("old")["resource"]["status"] == "active"
    assert store.detail("new") is None


def test_idempotency_updates_and_tombstones_keep_history(store):
    r = record(body_policy="licensed", body="# Run\nUse pytest for testing.", license="MIT")
    publish(store, [r])
    original = store.detail("debugger")
    counts = store.stats()
    assert publish(store, [r], revision="r2")["changed"] == 0
    assert store.stats()["versions"] == counts["versions"]
    changed = r.model_copy(update={"resource": r.resource.model_copy(update={"body": "# Fix\nNew body"})})
    publish(store, [changed], revision="r3")
    assert original["version_id"] != store.detail("debugger")["version_id"]
    publish(store, [], revision="r4")
    assert store.stats()["items"] == store.stats()["chunks"] == 0
    assert store.stats()["versions"] == 2
    with store.connect(True) as conn:
        assert conn.execute("SELECT count(*) FROM chunk_fts").fetchone()[0] == 0


def test_incremental_absence_does_not_delete_and_second_source_survives(store):
    publish(store, [record("a"), record("b")])
    publish(store, [], revision="unchanged", mode="incremental")
    assert store.stats()["items"] == 2
    publish(store, [record("a", body="low priority", body_policy="licensed")], source="secondary")
    assert store.detail("a")["resource"]["body"] == ""
    publish(store, [])
    assert store.detail("a")["resource"]["status"] == "active"
    assert store.detail("a")["resource"]["body"] == "low priority"
    assert store.detail("b")["resource"]["status"] == "deleted"


def test_changed_source_config_discards_incomplete_snapshot(store):
    run = store.begin_run("primary")
    store.stage(run["run_id"], Page(records=[record("stale")], complete=False, checkpoint={"page": 1}))
    store.register([SourceSpec(source_id="primary", kind="bundle", url="bundled:replacement")])
    assert store.begin_run("primary")["checkpoint"] == {}


def test_unknown_license_does_not_persist_body_and_features_are_auditable(store):
    publish(store, [record(body="PRIVATE LICENSE CONTENT", body_policy="metadata",
                           features=[Feature(feature="friction", value="retry", origin="curated", evidence="reviewed")])])
    r = store.detail("debugger")["resource"]
    assert r["body"] == ""
    assert any(f["value"] == "debugging" and f["origin"] == "extracted" for f in r["features"])
    assert any(f["value"] == "retry" and f["origin"] == "curated" for f in r["features"])
    assert "重复" in lexical_tokens("调试重复失败")


def test_wal_snapshot_and_process_writer_lock(store):
    publish(store, [record("old")])
    with store.connect(True) as reader:
        assert reader.execute("SELECT count(*) FROM catalog_item").fetchone()[0] == 1
        publish(store, [record("new")])
        assert reader.execute("SELECT count(*) FROM catalog_item").fetchone()[0] == 1
    with store.writer(), pytest.raises(CatalogBusy), store.writer():
        pass


def test_chunk_provenance_and_no_silent_body_cutoff():
    r = record(body_policy="licensed", body="# A\n" + "中文说明" * 1000 + "\n# B\nlast section").resource
    result = chunks(r)
    assert len(result) > 3
    assert any(c["heading"] == "B" and c["text"] == "last section" for c in result)
    assert all(len(c["text"]) <= 1200 and c["text_hash"] for c in result)


def test_v2_catalog_is_backed_up_and_rebuilt_as_v3(tmp_path):
    path = tmp_path / "catalog.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE catalog_item(item_id TEXT)")
        conn.execute("PRAGMA application_id=1413696583")
        conn.execute("PRAGMA user_version=2")
    store = CatalogStore(path)
    assert store.stats()["schema_version"] == 3 and store.verify()["ok"]
    with sqlite3.connect(tmp_path / "catalog.db.v2.bak") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_catalog_field_dictionary_matches_data_package_ddl():
    import json
    from importlib.resources import files

    from tandem_catalog.schema_export import table_schemas
    expected = json.loads(files("tandem_data").joinpath("schemas/catalog-v1.schema.json").read_text())
    assert expected == table_schemas()
