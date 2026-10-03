"""Guard experimental accounting and separation from hidden evaluation assets."""

import pytest
from evals.artificial_benchmark.adaptation import add_spec, history_pack, packs
from evals.artificial_benchmark.evaluate import aggregate, compare
from evals.artificial_benchmark.runner import summarize_events
from evals.artificial_benchmark.study import offline_verifier, strip_skills


def assistant(usage=None, stop="stop"):
    return {"type": "message_end", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "done"}],
        "stopReason": stop, "usage": usage,
    }}


def test_provider_tokens_are_counted_once_including_cached_input():
    usage = {"input": 100, "output": 25, "cacheRead": 80, "cacheWrite": 40,
             "totalTokens": 245, "reasoning": 20}
    event = assistant(usage)
    result = summarize_events([event, {"type": "agent_end", "messages": [event["message"]]}])
    assert result["usage"]["total_tokens"] == 245
    assert result["usage"]["complete"]


@pytest.mark.parametrize("bad", [None, {}, {"input": 0, "output": 0, "cacheRead": -1, "cacheWrite": 0}])
def test_missing_usage_does_not_become_a_zero_cost_run(bad):
    events = [assistant({"input": 10, "output": 2, "cacheRead": 0, "cacheWrite": 0}), assistant(bad)]
    result = summarize_events(events)
    assert result["usage"]["total_tokens"] is None
    assert result["usage"]["known_total_tokens"] == 12


def test_failed_request_keeps_reported_subtotal_and_marks_unknown_billing():
    result = summarize_events([assistant({"input": 10, "output": 2, "cacheRead": 0, "cacheWrite": 0}, "error")])
    assert result["usage"]["total_tokens"] is None
    assert result["usage"]["known_total_tokens"] == 12


def test_preinstalled_verifier_retains_spreadsheet_formula_evaluation():
    script = """#!/bin/bash
apt-get update
apt-get install -y curl
curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh
source $HOME/.local/bin/env
ssconvert -S /root/gdp.xlsx /root/sheet.csv
uvx \\
  --with pytest==8.4.1 \\
  --with openpyxl==3.1.5 \\
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA -v
PYTEST_EXIT_CODE=$?
echo $PYTEST_EXIT_CODE
"""
    offline = offline_verifier(script)
    assert "ssconvert -S /root/gdp.xlsx /root/sheet.csv" in offline
    assert "python3 -m pytest --ctrf" in offline
    assert "PYTEST_EXIT_CODE=$?" in offline
    assert not any(s in offline for s in ("apt-get", "uvx", "--with", "curl -LsSf"))


def test_unknown_verifier_launcher_is_rejected():
    with pytest.raises(ValueError, match="Unsupported verifier"):
        offline_verifier("some-other-test-runner /tests\n")


def test_upstream_answers_are_not_in_task_images():
    source = "FROM ubuntu:24.04\nCOPY skills /root/.agents/skills\nCOPY data.xlsx /root/data.xlsx\n"
    assert strip_skills(source) == "FROM ubuntu:24.04\nCOPY data.xlsx /root/data.xlsx\n"
    with pytest.raises(ValueError, match="Unsupported skills copy"):
        strip_skills('COPY ["skills", "/root/skills"]\n')


def result(passed, tokens):
    return {"passed": passed, "usage": {"total_tokens": tokens, "known_total_tokens": tokens or 0},
            "agent_turns": 2, "tool_calls": 3, "failed_tool_calls": 1, "wall_time_seconds": 4}


def test_pairwise_quality_dominates_efficiency_and_missing_is_not_a_tie():
    assert compare(result(True, 100), result(False, 10)) == "win"
    assert compare(result(False, 100), result(False, 10)) == "tie"
    assert compare(result(True, 10), result(True, 100)) == "win"
    assert compare(result(True, None), result(True, 100)) == "unknown"
    assert compare(result(None, 10), result(False, 100)) == "unknown"


def test_tokens_per_success_includes_failed_runs_and_refuses_missing_usage():
    assert aggregate([result(True, 100), result(False, 300)])["tokens_per_success"] == 400
    unknown = aggregate([result(True, 100), result(False, None)])
    assert unknown["tokens_per_success"] is None
    assert unknown["usage_complete_runs"] == 1
    assert aggregate([result(False, 100)])["tokens_per_success"] is None


def test_personalization_cannot_write_outside_its_asset_directory(tmp_path):
    manifest = {"instructions": [], "skills": [], "hooks": []}
    spec = {"kind": "skill", "payload": {"name": "probe", "files": [
        {"rel": "../../escape.txt", "text": "should never be written"}]}}
    with pytest.raises(ValueError, match="escapes personalization"):
        add_spec(tmp_path, manifest, spec)
    assert not (tmp_path / "escape.txt").exists()


def test_history_only_generation_does_not_inspect_host_rules(monkeypatch, tmp_path):
    inspected = []
    monkeypatch.setattr(packs, "_rule_files", lambda context: inspected.append(True) or [])
    spec = {"task_id": "isolation-probe", "pack_items": [("existing_rules", True), ("inventory", True)]}
    pack = history_pack(spec, reads=None, appdb=None, home=tmp_path)
    assert inspected == []
    assert pack["content"] == {"existing_rules": [], "inventory": []}
