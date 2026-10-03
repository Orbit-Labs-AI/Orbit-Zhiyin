from contextlib import contextmanager
from pathlib import Path
from threading import Event

from evals.skill_learning import providers


def test_provider_switch_repeats_matched_triplet_but_never_retries_task_failure(tmp_path, monkeypatch):
    calls = []

    def run(study, task, output, docker, credentials, *, arm, assets):
        calls.append((study["model"], arm))
        if study["model"] == "native" and arm == "ours":
            return {"outcome_state": "provider_error", "passed": None}
        return {"outcome_state": "completed", "passed": arm != "vanilla"}

    @contextmanager
    def credentials(*args):
        yield Path("credentials")

    monkeypatch.setattr(providers, "one_run", run)
    monkeypatch.setattr(providers, "credential_directory", credentials)
    monkeypatch.setattr(providers, "load_keys", lambda path: ["one", "two", "three"])
    monkeypatch.setattr(providers, "balances", lambda keys: [{"remaining_microyuan": 10_000_000}] * 3)
    items = [({"task_id": "task"}, tmp_path / "test" / ("task--" + arm), arm, None)
             for arm in ("vanilla", "ours", "llm")]
    recovery = {"key_file": "unused", "fallback_model": {"id": "fallback"},
                "key_slots": 3, "minimum_balance_microyuan": 1}
    result = providers.run_group(tmp_path, {"model": "native", "model_config": {"id": "native"}}, items,
                                 Path("native"), "docker", recovery, 0, Event())
    assert calls == [("native", "vanilla"), ("native", "ours"), ("fallback", "vanilla"),
                     ("fallback", "ours"), ("fallback", "llm")]
    assert result["cohort"] == "tokendance" and len(result["selected"]) == 3
    assert all("test-tokendance" in path for path in result["selected"].values())
    assert len(result["attempts"]) == 5


def test_grouping_preserves_frozen_task_and_arm_order():
    items = [({"task_id": task}, None, arm, None) for task, arm in
             [("b", "ours"), ("a", "vanilla"), ("b", "llm"), ("a", "ours")]]
    assert [[item[2] for item in group] for group in providers.grouped(items)] == [
        ["ours", "llm"], ["vanilla", "ours"]]
