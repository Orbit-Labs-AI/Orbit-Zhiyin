"""Keep native elapsed execution and observation wall span without selecting a winner."""

import pytest
from orbit_data.analysis_input import AnalysisScope, read_analysis
from orbit_data.contract import canonical
from orbit_data.duration import native_duration_ms
from orbit_data.store import Store

from orbit_backend.analytics.cost_time import summarize_durations


@pytest.mark.parametrize("duration", [
    {"secs": -1}, {"secs": True}, {"secs": 1, "nanos": -1},
    {"secs": 1, "nanos": 1_000_000_000}, {"secs": float("inf")},
])
def test_invalid_native_duration_stays_unknown(duration):
    assert native_duration_ms({"duration": duration}) is None


def test_different_wall_and_native_durations_survive_reader_and_cutoff(tmp_path):
    records = [
        {"type": "session_meta", "payload": {"id": "sample"}},
        {"type": "event_msg", "payload": {"type": "item_completed",
         "started_at_ms": 1000, "completed_at_ms": 39_601_000, "item": {
             "type": "CommandExecution", "id": "cmd1", "status": "completed", "exit_code": 0,
             "command": ["pytest"], "duration": {"secs": 5400, "nanos": 500_000_000}}}},
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("codex", tmp_path / "source")
        store.capture_stream(source, "sessions/sample.jsonl", [(canonical(r) + "\n").encode() for r in records])
        store.rebuild()
        bundle = read_analysis(store.home, AnalysisScope("UTC"))
        call = bundle["tool_calls"][0]
        assert call["native_execution_ms"] == 5_400_500
        assert call["wall_elapsed_ms"] == 39_600_000
        result = summarize_durations(bundle["tool_calls"], bundle["events"])
        assert result["wall_elapsed_sum_ms"] == 39_600_000
        assert result["native_execution_sum_ms"] == 5_400_500
        assert result["wall_interval_union_ms"] == 39_600_000
        assert result["wall_elapsed"]["over_one_hour_contribution"] == 1
        assert result["execution_duration_sum_ms"] == 5_400_500
        assert result["approval_wait_sum_ms"] is None
        historical = read_analysis(store.home, AnalysisScope("UTC", until_ts=39_601_000))
        earlier = summarize_durations(historical["tool_calls"], historical["events"])
        assert earlier["native_execution_sum_ms"] is None
        assert earlier["wall_elapsed_sum_ms"] is None
