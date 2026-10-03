"""Token usage from every agent must reach ``overview.usage`` or be excluded with a reason.

Expected numbers are hand-derived from the native rows written below, never read back from
the implementation. Token total of one request = uncached input + cache read + cache write
+ output (``token_semantics``: input is uncached, cache read/write are disjoint, reasoning is
already inside output).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tandem_data.validation.fixtures import create_sources

from tandem_backend.analytics.service import analyze_store
from tandem_backend.data_access.ingest import ingest
from tandem_backend.data_access.store import CanonicalStore


def rewrite_jsonl(path: Path, edit) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = edit(rows)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def usage_of(home: Path) -> dict:
    return analyze_store(CanonicalStore(home), with_text=False)["overview"]["usage"]


def test_requests_with_native_ids_are_summed_exactly_across_agents(tmp_path):
    roots = create_sources(tmp_path / "sources")

    def claude(rows):
        # A second request in the same session with its own message id: 7 + 2 + 1 + 3 = 13.
        second = json.loads(json.dumps(rows[1]))
        second["uuid"] = "a2"
        second["message"].update(id="r2", stop_reason="end_turn",
                                 content=[{"type": "text", "text": "完成"}],
                                 usage={"input_tokens": 7, "output_tokens": 3,
                                        "cache_read_input_tokens": 2,
                                        "cache_creation_input_tokens": 1})
        return [*rows, second]

    def pi(rows):
        for row in rows:
            if row.get("message", {}).get("role") == "assistant":
                row["message"]["responseId"] = "resp-pi-1"
        return rows

    rewrite_jsonl(roots["claude_code"] / "projects/demo/demo.jsonl", claude)
    rewrite_jsonl(roots["pi"] / "sessions/demo/demo.jsonl", pi)
    home = tmp_path / "data"
    for agent in ("claude_code", "pi"):
        assert ingest(home, agent, roots[agent])["import"]["capture_errors"] == 0
    result = usage_of(home)
    # claude r: 20 + 10 + 0 + 5 = 35; claude r2: 13; pi resp-pi-1: 20 + 10 + 0 + 5 = 35.
    assert result["invalid_request_rows"] == 0
    assert result["request_count"] == 3
    assert result["status"] == "available"
    assert result["total_tokens"] == 35 + 13 + 35
    assert result["total_basis"] == "call_delta"
    assert result["token_buckets"] == {"input_tokens": 47, "cache_read_tokens": 22,
                                       "cache_write_tokens": 1, "output_tokens": 13}


def test_rows_without_a_request_boundary_are_excluded_with_a_reason(tmp_path):
    """dsh/kimi/opencode usage rows carry no request id today: they must not be summed as if
    they were requests, and the exclusion must be reported, not silent."""
    roots = create_sources(tmp_path / "sources")
    home = tmp_path / "data"
    for agent in ("claude_code", "dsh", "kimi", "opencode"):
        ingest(home, agent, roots[agent])
    result = usage_of(home)
    assert result["request_count"] == 1  # only Claude's message id "r"
    assert result["invalid_request_rows"] == 3
    assert result["invalid_request_reasons"] == {"unreliable_request_boundary": 3}
    assert result["known_call_tokens"] == 35
    assert result["status"] == "partial"
    assert result["total_tokens"] is None  # never a partial sum presented as the total


@pytest.mark.xfail(strict=True, reason=(
    "follow-up (data connectors): dsh seq / kimi usage.record ordinal / opencode message id "
    "identify one request each but are not recorded as request_id, so boundary_quality is "
    "'unknown' and the App overview total is null for these agents"))
@pytest.mark.parametrize("agent", ["dsh", "kimi", "opencode"])
def test_native_step_ids_establish_a_request_boundary(tmp_path, agent):
    roots = create_sources(tmp_path / "sources")
    home = tmp_path / "data"
    ingest(home, agent, roots[agent])
    result = usage_of(home)
    assert result["invalid_request_rows"] == 0
    assert result["total_tokens"] == 35
