"""Regressions for benchmark leakage and accounting failures, without paid calls."""

import copy
import json
from pathlib import Path

import pytest
from evals.skill_learning.runtime import summarize_events
from evals.skill_learning.study import offline_verifier, strip_skills, tree, validate_protocol


def test_repeated_agent_end_does_not_double_count_tokens():
    message = {"role": "assistant", "stopReason": "stop", "content": [],
               "usage": {"input": 7, "output": 3, "cacheRead": 19, "cacheWrite": 11}}
    events = [{"type": "message_end", "message": message},
              {"type": "agent_end", "messages": [message]}]
    result = summarize_events(events)
    assert result["usage"]["total_tokens"] == 40
    assert result["usage"]["complete"]


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
