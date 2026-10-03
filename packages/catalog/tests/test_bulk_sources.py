"""Streaming import boundaries; all contents below are constructed fixtures."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from orbit_catalog.sources.bulk import BulkConnector


def source(tmp_path, rows, **config):
    path = tmp_path / "skills.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return SimpleNamespace(source_id="bulk-test", url="https://example.test/dataset",
                           config={"file": str(path), "revision": "immutable-test-revision",
                                   "dataset_license": "CC-BY-4.0", **config})


def row(text="---\nname: Example\ndescription: A constructed fixture\nlicense: MIT\n---\n# Work\nRead a file."):
    return {"content": text, "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "repo": "test/fixture", "path": "skills/example/SKILL.md", "source": "clone", "stars": 12}


def test_resumes_at_byte_offset_and_is_unchanged_on_second_scan(tmp_path):
    spec = source(tmp_path, [row(), row("Another constructed skill")], page_size=1)
    connector = BulkConnector(spec)
    first = connector.fetch_page({}, {})
    assert not first.complete and len(first.records) == 1
    second = BulkConnector(spec).fetch_page(first.checkpoint, {})
    assert second.complete and len(second.records) == 1
    assert first.records[0].native_id != second.records[0].native_id
    unchanged = connector.fetch_page({}, {"revision": second.revision})
    assert unchanged.complete and unchanged.mode == "incremental" and not unchanged.records


def test_compilation_license_does_not_grant_install_rights(tmp_path):
    record = BulkConnector(source(tmp_path, [row()])).fetch_page({}, {}).records[0]
    resource = record.resource
    assert resource.name == "Example" and resource.summary == "A constructed fixture"
    assert resource.body_policy == "index_only" and resource.body
    assert resource.license is None and resource.install == {}
    assert resource.metadata["declared_license"] == "MIT"
    assert resource.metadata["dataset_license"] == "CC-BY-4.0"
    assert resource.metadata["verification"] == "dataset_snapshot_read"
    assert resource.metadata["installable"] is False
    assert "content" not in record.raw
    assert record.native_id == resource.metadata["content_sha256"]


def test_truncation_is_explicit_and_identity_uses_entire_content(tmp_path):
    text = "a" * 250005
    record = BulkConnector(source(tmp_path, [row(text)])).fetch_page({}, {}).records[0]
    assert len(record.resource.body) == 250000
    assert record.resource.metadata["body_truncated"]
    assert record.resource.metadata["original_content_chars"] == 250005
    assert record.native_id == hashlib.sha256(text.encode()).hexdigest()


def test_explicit_large_body_limit_indexes_full_document(tmp_path):
    text = "a" * 1025262
    record = BulkConnector(source(tmp_path, [row(text)], body_limit=2000000)).fetch_page({}, {}).records[0]
    assert record.resource.body == text
    assert record.resource.metadata["body_truncated"] is False
    assert record.resource.metadata["indexed_content_chars"] == len(text)
    with pytest.raises(ValueError, match="bulk_invalid_body_limit"):
        BulkConnector(source(tmp_path, [row()], body_limit=2000001))


def test_deduplication_identity_uses_content_not_location(tmp_path):
    a, b = row(), row()
    b["repo"] = "other/repository"
    records = BulkConnector(source(tmp_path, [a, b])).fetch_page({}, {}).records
    assert records[0].native_id == records[1].native_id
    assert records[0].resource.item_id == records[1].resource.item_id


def test_changed_file_cannot_resume_an_old_scan(tmp_path):
    spec = source(tmp_path, [row(), row()], page_size=1)
    first = BulkConnector(spec).fetch_page({}, {})
    with open(spec.config["file"], "a") as stream:
        stream.write(json.dumps(row()) + "\n")
    with pytest.raises(ValueError, match="bulk_file_changed_during_scan"):
        BulkConnector(spec).fetch_page(first.checkpoint, {})


@pytest.mark.parametrize("kind", ["command", "hook", "workflow", "mcp_server"])
def test_non_skill_sources_keep_type_and_documented_license(tmp_path, kind):
    spec = source(tmp_path, [row()], resource_type=kind, content_license="CC0-1.0",
                  license_url="https://example.test/pinned/LICENSE", agents=["copilot"])
    resource = BulkConnector(spec).fetch_page({}, {}).records[0].resource
    assert resource.type == kind and resource.item_id.startswith(kind + ":sha256:")
    assert resource.body_policy == "licensed" and resource.license == "CC0-1.0"
    assert resource.agents == ["copilot"] and resource.install == {}
    assert resource.metadata["license_scope"] == "original_repository"


def test_body_license_requires_original_source_evidence(tmp_path):
    with pytest.raises(ValueError, match="bulk_content_license_requires_evidence"):
        BulkConnector(source(tmp_path, [row()], content_license="CC-BY-4.0"))


@pytest.mark.parametrize("bad", [{"content": ""}, {"content": "ok", "content_hash": "f" * 64}, []])
def test_invalid_records_fail_without_silent_skipping(tmp_path, bad):
    with pytest.raises(ValueError, match="bulk_missing_content|bulk_content_hash_mismatch"):
        BulkConnector(source(tmp_path, [bad])).fetch_page({}, {})
