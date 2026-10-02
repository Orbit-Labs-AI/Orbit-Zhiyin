"""Parallel capture/mapping must equal the serial path, logically and byte-for-byte."""

import json

import pytest
from _integrity import assert_integrity, build_relation_tree, differing_tables, logical_digest

from tandem_data.pipeline import rebuild
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store
from tandem_data.validation.fixtures import create_sources


def _sources(folder):
    roots = create_sources(folder / "fixtures")
    tree = build_relation_tree(folder / "tree")
    return [*sorted(roots.items()), *sorted(tree.items())]


def _import(home, sources, workers, threshold=None):
    with Store(home) as store:
        service = ImportService(store, workers=workers)
        if threshold is not None:
            service.pool.threshold = threshold
        try:
            for agent, root in sources:
                result = service.import_source(ImportRequest(agent, root))
                assert result["capture_errors"] == 0
        finally:
            service.close()
        assert_integrity(store)
    return logical_digest(home)


def test_parallel_import_matches_serial_for_fixtures_and_relations(tmp_path):
    sources = _sources(tmp_path)
    serial = _import(tmp_path / "serial", sources, workers=1)
    inline = _import(tmp_path / "inline", sources, workers=8)
    pooled = _import(tmp_path / "pooled", sources, workers=8, threshold=0)
    assert differing_tables(tmp_path / "serial", tmp_path / "inline") == []
    assert differing_tables(tmp_path / "serial", tmp_path / "pooled") == []
    assert serial == inline == pooled
    with Store(tmp_path / "serial") as store:
        relations = dict(
            store.db.execute("SELECT disposition,COUNT(*) FROM raw_record GROUP BY disposition")
        )
        assert relations.get("replayed", 0) > 0  # resume copies and forks were exercised
        kinds = {row[0] for row in store.db.execute("SELECT DISTINCT kind FROM session")}
        assert {"main", "subagent"} <= kinds
        assert store.db.execute(
            "SELECT COUNT(*) FROM session WHERE forked_from IS NOT NULL"
        ).fetchone()[0]


def test_parallel_rebuild_matches_serial_for_codex_fork(tmp_path):
    from test_edges import stream

    parent = [
        {"type": "session_meta", "ordinal": 0, "payload": {"id": "p", "session_id": "p"}},
        {"type": "turn_context", "ordinal": 1, "payload": {"turn_id": "t", "model": "test"}},
        {
            "type": "response_item",
            "ordinal": 2,
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        },
    ]
    child = [
        {
            "type": "session_meta",
            "ordinal": 0,
            "payload": {
                "id": "c",
                "session_id": "p",
                "parent_thread_id": "p",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "p"}}},
                "subagent_history_start_ordinal": 2,
            },
        },
        *[{**row, "ordinal": i + 1} for i, row in enumerate(parent[1:])],
        {
            "type": "response_item",
            "ordinal": 3,
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "child"}],
            },
        },
    ]
    digests = []
    for name, workers in (("serial", 1), ("parallel", 8)):
        with Store(tmp_path / name) as store:
            stream(store, "codex", tmp_path / "source", parent, "a-parent.jsonl")
            stream(store, "codex", tmp_path / "source", child, "b-child.jsonl")
            rebuild(store, workers=workers)
            assert_integrity(store)
        digests.append(logical_digest(tmp_path / name))
    assert digests[0] == digests[1]


def test_workers_one_is_the_serial_path(tmp_path, monkeypatch):
    import tandem_data.parallel as parallel

    def forbidden(*_, **__):
        raise AssertionError("workers=1 must not plan parallel work")

    monkeypatch.setattr(parallel.MapPlan, "__init__", forbidden)
    monkeypatch.setattr(parallel, "capture", forbidden)
    sources = _sources(tmp_path)
    _import(tmp_path / "serial", sources, workers=1)


def test_append_fast_path_matches_full_capture(tmp_path):
    sources = _sources(tmp_path)
    claude_root = dict(sources)["claude_code"]
    target = sorted(claude_root.rglob("*.jsonl"))[0]
    digests = []
    for name, workers in (("serial", 1), ("parallel", 8)):
        home = tmp_path / name
        _import(home, sources, workers)
        digests.append(home)
    line = json.loads(target.read_text().splitlines()[0])
    line["uuid"] = "appended-line"
    with target.open("a") as handle:
        handle.write(json.dumps(line) + "\n")
    for home, workers in zip(digests, (1, 8), strict=True):
        with Store(home) as store:
            service = ImportService(store, workers=workers)
            result = service.import_source(ImportRequest("claude_code", claude_root))
            service.close()
            assert result["changed"] == 1
            assert_integrity(store)
    assert differing_tables(digests[0], digests[1]) == []


@pytest.mark.parametrize("workers", [8])
def test_changed_source_during_parallel_map_aborts_publication(tmp_path, workers):
    sources = _sources(tmp_path)
    home = tmp_path / "data"
    _import(home, sources, workers)
    with Store(home) as store:
        before = store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0]
        target = sorted(dict(sources)["pi"].rglob("*.jsonl"))[0]
        # Change bytes without a rescan; the next rebuild must refuse to publish.
        target.write_text(target.read_text().replace("任务", "任務", 1))
        store.db.execute(
            "UPDATE source_file SET watermark=json_remove(watermark,'$.projected_revision')"
        )
        from tandem_data.source_reader import SourceUnavailable

        with pytest.raises(SourceUnavailable):
            rebuild(store, workers=workers)
        assert store.db.execute("SELECT COUNT(*) FROM projection_run").fetchone()[0] == before


def test_cached_source_paths_match_source_reader(tmp_path):
    from tandem_data import parallel
    from tandem_data.discovery import inputs
    from tandem_data.source_reader import SourceUnavailable, source_path

    root = tmp_path / "pi"
    outside = tmp_path / "outside"
    (root / "sessions/a").mkdir(parents=True)
    outside.mkdir()
    (root / "sessions/a/one.jsonl").write_text("{}\n")
    (outside / "two.jsonl").write_text("{}\n")
    (root / "sessions/linked").symlink_to(outside, target_is_directory=True)
    (root / "sessions/a/alias.jsonl").symlink_to(root / "sessions/a/one.jsonl")
    found = list(inputs("pi", root))
    assert [str(item.path.relative_to(root)) for item in found] == ["sessions/a/one.jsonl"]
    assert parallel.relative_paths(root, found) == {"sessions/a/one.jsonl"}
    locate = parallel._SourcePaths(root)
    for relative in (
        "sessions/a/one.jsonl",
        "sessions/a/alias.jsonl",
        "sessions/linked/two.jsonl",
        "sessions/a/missing.jsonl",
    ):
        outcomes = []
        for resolve in (lambda r: source_path(root, r), locate):
            try:
                outcomes.append(str(resolve(relative)))
            except SourceUnavailable as error:
                outcomes.append(error.status)
        assert outcomes[0] == outcomes[1], relative


def test_grouped_capture_isolates_a_failing_file(tmp_path, monkeypatch):
    import tandem_data.parallel as parallel
    from tandem_data.discovery import inputs

    root = dict(_sources(tmp_path))["claude_code"]
    target = sorted(root.rglob("*.jsonl"))[1]
    original = parallel.index_file

    def flaky(store, source_id, path, role, scan=None):
        if path == target:
            with store.transaction():
                store.db.execute(
                    "UPDATE source SET label='partial' WHERE source_id=?", (source_id,)
                )
                raise ValueError("simulated capture failure")
        return original(store, source_id, path, role, scan)

    monkeypatch.setattr(parallel, "index_file", flaky)
    monkeypatch.setattr(parallel, "CAPTURE_GROUP_FILES", 2)
    with Store(tmp_path / "data") as store:
        service = ImportService(store, workers=8)
        service.pool.threshold = 0
        result = service.import_source(ImportRequest("claude_code", root))
        service.close()
        assert result["capture_errors"] == 1
        assert result["files"] == len(list(inputs("claude_code", root))) - 1
        # The failing file's savepoint rolled back alone; its neighbours were committed.
        assert store.db.execute("SELECT label FROM source").fetchone()[0] is None
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM ingest_issue WHERE code='capture_failed'"
            ).fetchone()[0]
            == 1
        )
        assert store.db.execute("SELECT COUNT(*) FROM source_file").fetchone()[0] == result["files"]
        assert not store.db.in_transaction
