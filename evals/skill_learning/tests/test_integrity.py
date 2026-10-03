"""Regressions for benchmark leakage and accounting failures, without paid calls."""

import copy
import json
from pathlib import Path

import pytest
from evals.skill_learning.runtime import completion_state, summarize_events
from evals.skill_learning.study import offline_verifier, strip_skills, tree, validate_protocol


def test_repeated_agent_end_does_not_double_count_tokens():
    message = {"role": "assistant", "stopReason": "stop", "content": [],
               "usage": {"input": 7, "output": 3, "cacheRead": 19, "cacheWrite": 11}}
    events = [{"type": "message_end", "message": message},
              {"type": "agent_end", "messages": [message]}]
    result = summarize_events(events)
    assert result["usage"]["total_tokens"] == 40
    assert result["usage"]["complete"]


def test_provider_errors_are_unknown_and_task_budget_failures_are_retained():
    trajectory = {"termination": "completed", "exit_code": 0, "last_stop_reason": "error"}
    assert completion_state(trajectory, {"passed": False}) == (None, "provider_error")
    trajectory.update(last_stop_reason="stop")
    assert completion_state(trajectory, {"passed": False}) == (False, "completed")
    assert completion_state(trajectory, {"passed": True}) == (True, "completed")
    trajectory.update(termination="turn_limit")
    assert completion_state(trajectory, {"passed": True}) == (False, "budget_exhausted")


def test_report_does_not_turn_unknown_usage_into_a_total():
    from evals.skill_learning.report import usage_total

    known = {"known_total_tokens": 40, "total_tokens": 40, "complete": True}
    missing = {"known_total_tokens": 17, "total_tokens": None, "complete": False}
    result = usage_total([known, missing])
    assert result["known_tokens_lower_bound"] == 57 and result["total_tokens"] is None
    assert result["unknown_usage_attempts"] == 1
    assert usage_total([])["total_tokens"] is None


@pytest.mark.parametrize("last", [{"stopReason": "error"}, {"stopReason": "aborted"},
                                 {"usage": None}, {"usage": {"input": -1}}])
def test_unreported_or_failed_request_usage_stays_unknown(last):
    known = {"role": "assistant", "stopReason": "toolUse", "content": [],
             "usage": {"input": 7, "output": 3, "cacheRead": 19, "cacheWrite": 11}}
    final = {**known, **last}
    result = summarize_events([{"type": "message_end", "message": known},
                               {"type": "message_end", "message": final}])
    assert result["usage"]["total_tokens"] is None
    assert result["usage"]["known_total_tokens"] >= 40
    assert not result["usage"]["complete"]


def test_verifier_network_installer_removed_without_changing_assertions():
    source = '''#!/bin/bash
if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env
else
    pip3 install --break-system-packages uv
fi
uvx --python 3.13 \\
  --with pytest==8.4.1 \\
  --with pytest-json-ctrf==0.3.5 \\
  pytest /tests/test_outputs.py --ctrf /logs/verifier/ctrf.json
if [ $? -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
'''
    actual = offline_verifier(source)
    assert "astral.sh" not in actual
    assert "uvx" not in actual
    assert "python3 -m pytest /tests/test_outputs.py --ctrf /logs/verifier/ctrf.json" in actual
    assert actual.splitlines()[-1] == source.splitlines()[-1]
    with pytest.raises(ValueError, match="Unsupported verifier"):
        offline_verifier("echo 1 > /logs/verifier/reward.txt\n")


def test_upstream_skills_not_copied_and_unknown_copy_fails_closed():
    assert strip_skills("FROM debian\nCOPY skills /root/.agents/skills\nCOPY data /app/data\n") == \
        "FROM debian\nCOPY data /app/data\n"
    with pytest.raises(ValueError, match="Unsupported upstream skills copy"):
        strip_skills('FROM debian\nCOPY ["skills", "/app/skills"]\n')


def test_source_symlinks_cannot_escape_isolated_build_context(tmp_path):
    source = tmp_path / "environment"
    source.mkdir()
    secret = tmp_path / "not-task-data"
    secret.write_text("outside")
    (source / "linked").symlink_to(secret)
    with pytest.raises(ValueError, match="symlinks"):
        tree(source)


def test_preregistration_rejects_overlap_and_prior_test_exposure():
    protocol = json.loads((Path(__file__).parents[1] / "protocol.json").read_text())
    validate_protocol(protocol)
    family = next(iter(protocol["candidate_families"]))
    overlap = copy.deepcopy(protocol)
    overlap["candidate_families"][family]["test"].append(
        overlap["candidate_families"][family]["history"][0])
    with pytest.raises(ValueError, match="Overlapping"):
        validate_protocol(overlap)
    protocol["prior_exposed_families"].append(family)
    with pytest.raises(ValueError, match="Previously exposed"):
        validate_protocol(protocol)


@pytest.mark.parametrize("split", ["validation", "test"])
def test_native_pipeline_refuses_nonhistory_before_creating_output(tmp_path, split):
    from evals.skill_learning.pipeline import capture

    output = tmp_path / "output"
    with pytest.raises(ValueError, match="history"):
        capture([{"split": split, "root": str(tmp_path / "source")}], output, 1)
    assert not output.exists()


def test_usage_requires_observed_read_and_later_method_evidence(tmp_path):
    from evals.skill_learning.trace import observe

    session = tmp_path / "sessions/run.jsonl"
    session.parent.mkdir()
    rows = [
        {"customType": "orbit.benchmark.injection", "data": {"skills": [{"name": "skill"}]}},
        {"type": "message", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "before"}]}},
        {"customType": "orbit.benchmark.activation", "data": {"skill": "skill", "observation": "body_read", "success": True}},
        {"type": "message", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "after"}]}},
        {"customType": "orbit.benchmark.hook", "data": {"code": 2}},
        {"customType": "orbit.benchmark.hook", "data": {"code": 1}},
    ]
    session.write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = observe(tmp_path)
    assert result["skills"][0]["actual_usage"] is None
    assert result["counts"]["successfully_read_skills"] == 1
    assert result["counts"]["hook_blocks"] == 1
    assert result["counts"]["hook_errors"] == 1
    for invalid in ("before", "nonexistent"):
        with pytest.raises(ValueError, match="later observed"):
            observe(tmp_path, {"skills": {"skill": {"used": True,
                "evidence": [{"tool_call_id": invalid, "step": "Validate saved output"}]}}})
    result = observe(tmp_path, {"skills": {"skill": {"used": True,
        "evidence": [{"tool_call_id": "after", "step": "Validate saved output"}]}}})
    assert result["counts"]["confirmed_used_skills"] == 1
