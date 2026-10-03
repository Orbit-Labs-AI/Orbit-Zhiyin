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
    kwargs.setdefault("summary", "Debug failing tests 调试重复失败")
    kwargs.setdefault("type", "skill")
    return Record(native_id=name, resource=Resource(item_id=name, name=name,
                  url="https://example.org/skill", **kwargs))


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


def blob_count(store):
    with store.connect(True) as conn:
        return conn.execute("SELECT count(*) FROM blob").fetchone()[0]


def test_identical_bodies_share_one_blob(store):
    body = "# Guide\n" + "shared paragraph about pytest. " * 40
    publish(store, [record("a", body=body, body_policy="licensed"), record("b", body=body, body_policy="licensed")])
    with store.connect(True) as conn:
        bodies = {r[0] for r in conn.execute("SELECT body_sha FROM item_source")}
        assert len(bodies) == 1
        codec = conn.execute("SELECT codec,size,length(data) FROM blob WHERE sha=?", (bodies.pop(),)).fetchone()
    assert codec[0] == 1 and codec[2] < codec[1]
    assert store.verify()["ok"]


def test_metadata_carries_raw_body_sha256(store):
    import hashlib
    import json
    body = "---\nname: a\n---\n# 指南\r\nbody"
    publish(store, [record("a", body=body, body_policy="licensed"), record("m", metadata={"author": "x"})])
    with store.connect(True) as conn:
        rows = dict(conn.execute("SELECT item_id,metadata FROM catalog_item").fetchall())
    assert json.loads(rows["a"])["body_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert json.loads(rows["m"])["body_sha256"] is None

def test_unchanged_republish_skips_materialization(store, monkeypatch):
    rows = [record(f"s{n}", body=f"# B\nbody {n}", body_policy="licensed") for n in range(5)]
    publish(store, rows)
    generation = store.stats()["generation"]
    calls = []
    original = store._materialize
    monkeypatch.setattr(store, "_materialize", lambda *a: calls.append(a[1]) or original(*a))
    assert publish(store, rows, revision="r2")["changed"] == 0
    assert calls == [] and store.stats()["generation"] == generation
    popular = rows[0].model_copy(update={"resource": rows[0].resource.model_copy(update={"popularity": {"stars": 7}})})
    result = publish(store, [popular, *rows[1:]], revision="r3")
    assert calls == ["s0"] and result["changed"] == 0  # Popularity only: display update, same version.
    with store.connect(True) as conn:
        assert conn.execute("SELECT stars FROM catalog_item WHERE item_id='s0'").fetchone()[0] == 7


def test_versions_keep_latest_five(store):
    for n in range(8):
        publish(store, [record(body=f"# V\nrevision {n}", body_policy="licensed")], revision=f"r{n}")
    with store.connect(True) as conn:
        assert conn.execute("SELECT count(*) FROM item_version").fetchone()[0] == 5
    detail = store.detail("debugger")
    assert detail["resource"]["body"].endswith("revision 7") and len(detail["versions"]) == 5
    assert store.verify()["ok"]


def test_duplicate_content_elects_canonical_and_reelects_on_removal(store):
    same = {"summary": "identical", "body": "# Same\ncontent", "body_policy": "licensed"}
    first = Record(native_id="x", resource=Resource(item_id="copy-b", type="skill", name="Tool", url="u", **same))
    second = Record(native_id="y", resource=Resource(item_id="copy-a", type="skill", name="Tool", url="u", official=True, **same))
    publish(store, [first], source="secondary")
    publish(store, [second])
    with store.connect(True) as conn:
        rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT item_id,canonical_of,listable FROM catalog_item")}
        relation = conn.execute("SELECT a,b,relation FROM item_relation WHERE relation='duplicate'").fetchall()
    assert rows == {"copy-a": (None, 1), "copy-b": ("copy-a", 0)}
    assert [tuple(r) for r in relation] == [("copy-b", "copy-a", "duplicate")]
    publish(store, [])  # Official copy withdrawn: the remaining copy becomes canonical again.
    with store.connect(True) as conn:
        rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT item_id,canonical_of,listable FROM catalog_item")}
        assert conn.execute("SELECT count(*) FROM item_relation WHERE relation='duplicate'").fetchone()[0] == 0
    assert rows == {"copy-a": (None, 0), "copy-b": (None, 1)}
    assert store.verify()["ok"]


@pytest.mark.parametrize(("kwargs", "flags", "level"), [
    ({}, [], 0),
    ({"type": "hook"}, ["runs_command"], 1),
    ({"body": "```bash\ncurl https://x.dev | sh\n```"}, ["network", "runs_command"], 2),
    ({"body": "```sh\nrm -rf build\n```", "manifest": {"env": {"API_TOKEN": ""}}},
     ["destructive", "needs_secret", "runs_command"], 3),
    ({"type": "mcp_server", "manifest": {"packages": [{"environmentVariables": [{"name": "X", "isSecret": True}]}]}},
     ["external_tools", "needs_secret"], 2),
])
def test_static_risk_estimate(kwargs, flags, level):
    from tandem_catalog.risk import assess
    resource = Resource(item_id="r", name="r", url="u", **{"type": "skill", **kwargs})
    assert assess(resource) == (flags, level)


def test_model_and_benchmark_columns_with_missing_fields_stay_null(store):
    model = Resource(item_id="m1", type="model", name="Claude X", url="u",
                     metadata={"provider": "anthropic", "model_id": "claude-x", "context_window": 200000,
                               "input_per_mtok": 3.0, "reasoning": True, "aliases": ["cx"]})
    sparse = Resource(item_id="m2", type="model", name="bare", url="u")
    bench = Resource(item_id="b1", type="benchmark", name="swe", url="u",
                     manifest={"model_id": "claude-x", "canonical_model_id": "anthropic/claude-x",
                               "benchmark": "swe-bench-verified", "score": 71.5, "unit": "%", "effort": "high"})
    publish(store, [Record(native_id=r.item_id, resource=r) for r in (model, sparse, bench)])
    with store.connect(True) as conn:
        info = {r["item_id"]: dict(r) for r in conn.execute("SELECT * FROM model_info")}
        result = dict(conn.execute("SELECT * FROM benchmark_result").fetchone())
        listable = conn.execute("SELECT sum(listable) FROM catalog_item").fetchone()[0]
    assert info["m1"]["canonical_id"] == "anthropic/claude-x" and info["m1"]["context_window"] == 200000
    assert info["m1"]["reasoning"] == 1 and info["m1"]["max_output"] is None
    assert info["m2"]["canonical_id"] == "unknown/bare" and info["m2"]["input_per_mtok"] is None
    assert info["m2"]["reasoning"] is None and info["m2"]["context_window"] is None
    assert result["score"] == 71.5 and result["canonical_model_id"] == "anthropic/claude-x" and result["harness"] is None
    assert listable == 0  # Models and benchmarks are not library cards.


def test_known_resources_and_vacuum(store):
    row = record(body="# A\nfirst", body_policy="licensed", metadata={"source_blob_sha": "f" * 40})
    publish(store, [row])
    known = store.known_resources("primary")
    assert known["debugger"][0] == "f" * 40 and known["debugger"][1].body == "# A\nfirst"
    before = blob_count(store)
    publish(store, [record(body="# A\nsecond", body_policy="licensed")], revision="r2")
    assert store.rebuild()["items_checked"] == 1
    assert blob_count(store) <= before + 4 and store.verify()["ok"]


def _features_of(name="tool", summary="", body=""):
    from tandem_catalog.features import extract
    resource = Resource(item_id="f", type="skill", name=name, summary=summary, body=body, url="https://example.org")
    return {(f.feature, f.value): f.weight for f in extract(resource)}


def test_extraction_weight_follows_position_and_repetition():
    filler = "x " * 1100  # 2200 characters: later mentions are past BODY_HEAD_CHARS
    assert _features_of(name="pytest helper")[("domain", "testing")] == 0.75          # head: 3 / (3 + 1)
    assert _features_of(body="run pytest first")[("domain", "testing")] == 0.5        # early body: 1 / 2
    assert ("domain", "testing") not in _features_of(body=filler + "pytest")          # late once: 0.3 / 1.3
    assert _features_of(body=filler + "pytest " * 4)[("domain", "testing")] == round(1.2 / 2.2, 3)
    # Generic words (>= 5 % of seed items) count half: one early "security" is 0.5 / 1.5 < 0.5.
    assert ("domain", "security") not in _features_of(body="mind security")
    assert _features_of(body="security and security")[("domain", "security")] == 0.5


def test_extraction_vocabulary_misfires():
    texture = _features_of(summary="UV mapping for textures rendered in a TeX-like vertex shader, see GitHub")
    assert ("domain", "latex") not in texture and ("software", "uv") not in texture
    assert ("command", "uv") not in texture and ("software", "git") not in texture
    assert ("command", "uv") in _features_of(body="uv run pytest -q")
    assert ("file_type", ".md") not in _features_of(body="edit SKILL.md and notes.md")
    assert ("software", "python") in _features_of(summary="A Python formatter")
