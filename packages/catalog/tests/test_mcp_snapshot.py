"""Offline snapshots use the ordinary MCP parser and full-scan sync semantics."""

import json

import pytest

from orbit_catalog.contracts import SourceSpec
from orbit_catalog.sources.structured import StructuredConnector
from orbit_catalog.store import CatalogStore
from orbit_catalog.sync import CatalogSync

URL = "https://registry.modelcontextprotocol.io/v0.1/servers"


class NoNetwork:
    def json(self, *_):
        raise AssertionError("snapshot attempted network")


def fixture(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    manifest = {"complete": True, "pages": 2, "records": 2, "unique_names": 2,
                "next_cursor": None, "source": URL, "fetched_at": "2026-10-03T12:00:00Z"}
    (root / "manifest.json").write_text(json.dumps(manifest))
    for index, name in enumerate(["io.github.example/one", "io.github.example/two"]):
        data = {"servers": [{"server": {"name": name, "version": "1", "description": name,
                                        "remotes": [{"type": "streamable-http", "url": "https://example.test/mcp"}]},
                              "_meta": {"io.modelcontextprotocol.registry/official": {
                                  "updatedAt": "2026-10-01T01:00:00Z", "status": "active"}}}],
                "metadata": {"count": 1, "nextCursor": "cursor-one" if index == 0 else None}}
        (root / f"page-{index:04d}.json").write_text(json.dumps(data))
    return SourceSpec(source_id="offline-mcp", kind="mcp", url=URL,
                      config={"snapshot_dir": str(root), "publish_every_pages": 1})


def edit(spec, filename, change):
    from pathlib import Path
    path = Path(spec.config["snapshot_dir"]) / filename
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def test_snapshot_resumes_and_ignores_existing_network_watermark(tmp_path):
    spec = fixture(tmp_path)
    state = {"watermark": "2026-10-03T13:00:00Z"}
    first = StructuredConnector(spec, NoNetwork()).fetch_page({}, state)
    assert first.mode == "full" and not first.complete
    assert first.watermark == "2026-10-03T12:00:00+00:00"
    assert first.records[0].resource.item_id == "mcp:io.github.example/one"
    assert first.records[0].resource.install["mcp"]["transport"] == "http"
    assert first.records[0].resource.license is None
    second = StructuredConnector(spec, NoNetwork()).fetch_page(first.checkpoint, state)
    assert second.complete and second.mode == "full" and second.revision == first.revision
    assert second.records[0].native_id == "io.github.example/two"
    unchanged = StructuredConnector(spec, NoNetwork()).fetch_page({}, {"revision": second.revision})
    assert unchanged.complete and unchanged.mode == "incremental" and unchanged.records == []


def test_snapshot_full_sync_pause_resume_and_noop_preserve_items(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    store.register([fixture(tmp_path)])
    sync = CatalogSync(store, NoNetwork())
    assert sync.sync(max_pages=1)[0]["status"] == "paused"
    assert store.stats()["items"] == 1
    assert sync.sync(force=True)[0]["status"] == "completed"
    assert store.stats()["items"] == 2
    assert sync.sync(force=True)[0]["status"] == "completed"
    assert store.stats()["items"] == 2


@pytest.mark.parametrize("filename,change,error", [
    ("manifest.json", lambda d: d.update(complete=False), "mcp_snapshot_incomplete"),
    ("manifest.json", lambda d: d.update(pages=0), "mcp_snapshot_incomplete"),
    ("manifest.json", lambda d: d.update(pages=3), "mcp_snapshot_noncontiguous_pages"),
    ("manifest.json", lambda d: d.update(records=3), "mcp_snapshot_count_mismatch"),
    ("manifest.json", lambda d: d.update(next_cursor="unfinished"), "mcp_snapshot_manifest_mismatch"),
    ("page-0000.json", lambda d: d["metadata"].update(nextCursor=None), "mcp_snapshot_cursor_mismatch"),
    ("page-0001.json", lambda d: d["metadata"].update(nextCursor="unexpected"), "mcp_snapshot_cursor_mismatch"),
    ("page-0001.json", lambda d: d["servers"][0]["server"].update(name="io.github.example/one"), "mcp_snapshot_invalid_or_duplicate_name"),
])
def test_incomplete_inconsistent_or_duplicate_snapshot_rejected(tmp_path, filename, change, error):
    spec = fixture(tmp_path)
    edit(spec, filename, change)
    with pytest.raises(ValueError, match=error):
        StructuredConnector(spec, NoNetwork()).fetch_page({}, {})


def test_checkpoint_cursor_and_snapshot_revision_are_bound(tmp_path):
    spec = fixture(tmp_path)
    first = StructuredConnector(spec, NoNetwork()).fetch_page({}, {})
    with pytest.raises(ValueError, match="mcp_snapshot_checkpoint_mismatch"):
        StructuredConnector(spec, NoNetwork()).fetch_page({**first.checkpoint, "cursor": "wrong"}, {})
    edit(spec, "manifest.json", lambda d: d.update(fetched_at="2026-10-03T12:01:00Z"))
    with pytest.raises(ValueError, match="mcp_snapshot_checkpoint_mismatch"):
        StructuredConnector(spec, NoNetwork()).fetch_page(first.checkpoint, {})


def test_changes_during_scan_and_relative_path_are_rejected(tmp_path):
    spec = fixture(tmp_path)
    adapter = StructuredConnector(spec, NoNetwork())
    first = adapter.fetch_page({}, {})
    edit(spec, "page-0001.json", lambda d: d["servers"][0]["server"].update(description="changed"))
    with pytest.raises(ValueError, match="mcp_snapshot_changed_during_scan"):
        adapter.fetch_page(first.checkpoint, {})
    spec.config["snapshot_dir"] = "relative/snapshot"
    with pytest.raises(ValueError, match="mcp_snapshot_dir_must_be_absolute"):
        StructuredConnector(spec, NoNetwork()).fetch_page({}, {})
