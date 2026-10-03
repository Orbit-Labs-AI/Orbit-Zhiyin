"""Native direct command → structured L3 fact → scoped outcome evidence."""

from orbit_data.analysis_input import AnalysisScope, read_analysis
from orbit_data.contract import canonical
from orbit_data.store import Store

from orbit_backend.analytics.outcome import extract_validation_runs


def test_native_shell_argv_and_command_status_reach_outcome(tmp_path):
    records = [
        {"type": "session_meta", "payload": {"id": "sample", "cwd": "/synthetic"}},
        {"type": "event_msg", "payload": {"type": "item_completed",
         "started_at_ms": 100, "completed_at_ms": 200, "item": {
             "type": "CommandExecution", "id": "cmd1", "status": "completed", "exit_code": 0,
             "command": ["/bin/zsh", "-lc", "cd repo && uv run pytest tests/private"]}}},
    ]
    with Store(tmp_path / "data") as store:
        source = store.add_source("codex", tmp_path / "source")
        store.capture_stream(source, "sessions/sample.jsonl",
                             [(canonical(r) + "\n").encode() for r in records])
        store.rebuild()
        bundle = read_analysis(store.home, AnalysisScope("UTC"))
        call = bundle["tool_calls"][0]
        assert call["command_spec"]["validation_kind"] == "test"
        assert call["status_scope"] == "direct_command"
        runs = extract_validation_runs([call])["validation_runs"]
        assert len(runs) == 1
        assert runs[0]["validation_result"] == "passed"
        assert runs[0]["identification_source"] == "structured_command_spec"
        assert runs[0]["validation_scope"]["coverage"] == "unspecified"
        assert runs[0]["criterion_uids"] == []
        historical = read_analysis(store.home, AnalysisScope("UTC", until_ts=200))
        assert extract_validation_runs(historical["tool_calls"], until_ts=200)["validation_runs"] == []
