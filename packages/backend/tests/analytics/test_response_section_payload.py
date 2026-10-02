"""Section bodies carry the sample boundary as counts + digest, not the full file list."""

from __future__ import annotations

import json

from tandem_backend.analytics.service import response_section

SHARED = ("input_contract", "feature_schema_version", "scope", "coverage", "versions",
          "selection", "effective_samples", "unknown_counts", "analysis_digest",
          "feature_dictionary", "source_coverage", "coverage_report")


def _result(files: int) -> dict:
    boundary = {
        "sources": [{"source_id": "src-a", "agent": "codex"}],
        "files": [{"file_id": f"file-{i:05d}", "source_id": "src-a",
                   "relative_path": f"sessions/2026/01/{i:05d}/rollout-synthetic-{i:05d}.jsonl",
                   "size": 1000 + i, "mtime_ns": i, "status": "indexed"} for i in range(files)],
        "l1_revision_count": files,
        "inventory_scan_ids": ["scan-1"],
    }
    return {**dict.fromkeys(SHARED), "sample_boundary": boundary, "overview": {"sessions": 17}}


def test_section_body_summarises_files_with_count_and_digest():
    big = response_section(_result(1500), "overview")
    small = response_section(_result(3), "overview")
    boundary = big["sample_boundary"]
    assert "files" not in boundary
    assert boundary["file_count"] == 1500 and boundary["sources"] == [
        {"source_id": "src-a", "agent": "codex"}]
    assert boundary["l1_revision_count"] == 1500 and boundary["inventory_scan_ids"] == ["scan-1"]
    assert boundary["files_digest"] and boundary["files_digest"] != small["sample_boundary"][
        "files_digest"]
    assert len(json.dumps(big)) < 2_000
    # The engine result itself keeps the full list for the dedicated endpoint.
    assert len(_result(1500)["sample_boundary"]["files"]) == 1500
