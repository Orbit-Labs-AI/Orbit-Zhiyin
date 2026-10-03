"""Resume only interrupted attempts; do not select successful reruns."""

from pathlib import Path

import pytest
from evals.artificial_benchmark.resume import (
    archive_incomplete,
    classify,
    credential_directory,
    load_keys,
    task_groups,
)
from evals.artificial_benchmark.resume_pi import configure
from evals.artificial_benchmark.study import read, save, tree


def run_files(path, *, completed=True, passed=False, termination="completed", error="", tokens=None):
    save(path / "result.json", {"agent_completed": completed, "passed": passed,
                               "termination": termination, "usage": {"total_tokens": tokens},
                               "verifier": {"status": "passed" if passed else "failed"}})
    save(path / "trajectory.json", {"messages": ([{"role": "assistant", "stopReason": "error",
                                                 "errorMessage": error}] if error else [])})


@pytest.mark.parametrize("passed", [True, False])
def test_completed_runs_with_unknown_usage_are_never_repeated(tmp_path, passed):
    run_files(tmp_path, passed=passed)
    assert classify(tmp_path) == "completed"


@pytest.mark.parametrize("termination", ["timeout", "turn_limit"])
def test_original_model_budget_failures_are_terminal(tmp_path, termination):
    run_files(tmp_path, completed=False, termination=termination)
    assert classify(tmp_path) == "budget_exhausted"


@pytest.mark.parametrize(("error", "expected"), [
    ("403 You've reached your 5-hour usage limit", "rate_limited"),
    ("429 rate_limit_exceeded", "rate_limited"),
    ("402 insufficient balance", "balance_exhausted"),
    ("400 invalid model", "provider_error"),
])
def test_provider_failures_are_separate_from_model_failures(tmp_path, error, expected):
    run_files(tmp_path, completed=False, error=error)
    assert classify(tmp_path) == expected


def test_verifier_failure_does_not_authorize_repeating_completed_agent(tmp_path):
    run_files(tmp_path)
    row = read(tmp_path / "result.json")
    row["verifier"] = {"status": "infrastructure_error"}
    save(tmp_path / "result.json", row)
    assert classify(tmp_path) == "needs_rescore"


def test_grouping_finishes_most_complete_triplets_without_using_pass_outcomes():
    order = [{"task_id": tid, "arm": arm} for arm in ("llm", "ours", "vanilla")
             for tid in ("empty", "partial", "nearly", "finished")]
    completed = {("partial", "vanilla"), ("nearly", "ours"), ("nearly", "llm"),
                 *(('finished', arm) for arm in ("llm", "ours", "vanilla"))}
    assert task_groups(order, completed) == [
        {"task_id": "nearly", "arms": ["vanilla"]},
        {"task_id": "partial", "arms": ["llm", "ours"]},
        {"task_id": "empty", "arms": ["llm", "ours", "vanilla"]},
    ]


def test_archiving_is_lossless_and_idempotent_after_new_result_promotion(tmp_path):
    original = tmp_path / "test/task--ours"
    run_files(original, completed=False, error="403 5-hour usage limit")
    files = tree(original)
    inventory = {"inventory": [{"original_state": "rate_limited", "files": files,
                                "original_path": "test/task--ours"}]}
    archive_incomplete(tmp_path, inventory)
    archived = tmp_path / "resume/original-attempts/task--ours"
    assert tree(archived) == files
    assert not original.exists()
    run_files(original, completed=True, passed=False, tokens=123)
    newer = tree(original)
    archive_incomplete(tmp_path, inventory)
    assert tree(original) == newer
    assert tree(archived) == files


def test_archive_refuses_changed_attempt_evidence(tmp_path):
    original = tmp_path / "test/task--ours"
    run_files(original, completed=False)
    inventory = {"inventory": [{"original_state": "interrupted", "files": tree(original),
                                "original_path": "test/task--ours"}]}
    (original / "trajectory.json").write_text('{}')
    with pytest.raises(ValueError, match="changed"):
        archive_incomplete(tmp_path, inventory)
    assert original.is_dir()


def test_keys_are_private_and_temporary_copies_are_cleaned_on_failure(tmp_path):
    key_file = tmp_path / "keys.txt"
    key_file.write_text("example-one\nexample-two\nexample-three\n")
    key_file.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        load_keys(key_file)
    key_file.chmod(0o600)
    assert len(load_keys(key_file)) == 3
    directory = None
    with pytest.raises(RuntimeError):
        with credential_directory(tmp_path / "credentials", "example-one", {"id": "kimi-k3"}) as directory:
            assert (directory / "auth.json").stat().st_mode & 0o077 == 0
            assert read(directory / "auth.json")["kimi-coding"]["key"] == "example-one"
            raise RuntimeError("simulated interruption")
    assert isinstance(directory, Path) and not directory.exists()


def test_explicit_pi_override_uses_only_the_authorized_model_and_endpoint(tmp_path):
    model = {"id": "kimi-k3", "baseUrl": "https://tokendance.space/gateway/v1",
             "api": "openai-completions", "thinkingLevelMap": {"max": "max"}}
    save(tmp_path / "models-store.json", {"kimi-coding": {"models": [model]}})
    configure(tmp_path)
    config = read(tmp_path / "models.json")["providers"]["kimi-coding"]
    assert config["baseUrl"] == model["baseUrl"]
    assert config["models"] == [model]
    model["baseUrl"] = "https://unapproved.example/v1"
    save(tmp_path / "models-store.json", {"kimi-coding": {"models": [model]}})
    with pytest.raises(ValueError, match="Unexpected resume"):
        configure(tmp_path)
