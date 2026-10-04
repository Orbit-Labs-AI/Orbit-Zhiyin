from pathlib import Path

import pytest
from evals.skill_learning import final
from evals.skill_learning.study import digest, save


def frozen(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(final, "command", lambda args: "abc" if "rev-parse" in args else "")
    save(tmp_path / "protocol.json", {"version": "fixed"})
    save(tmp_path / "library.json", {"learned": "history only"})
    save(tmp_path / "llm.json", {"learned": "same history"})
    study = {"provider": "kimi-coding", "model": "k3", "memory": "off", "benchmark_commit": "source",
             "tasks": [{"task_id": "family-5", "split": "test"}]}
    save(tmp_path / "study.json", study)
    save(tmp_path / "freeze.json", {"code_commit": "abc", "source_commit": "source",
         "runtime": {key: study.get(key) for key in final.RUNTIME_KEYS},
         "protocol_sha256": digest(tmp_path / "protocol.json"),
         "library": str(tmp_path / "library.json"), "library_sha256": digest(tmp_path / "library.json"),
         "llm_result": str(tmp_path / "llm.json"), "llm_sha256": digest(tmp_path / "llm.json"),
         "run_order": [{"task_id": "family-5", "arm": "ours"}]})
    (tmp_path / "freeze.sha256").write_text(digest(tmp_path / "freeze.json"))


def test_test_runner_rejects_changed_library_and_provider(tmp_path, monkeypatch):
    frozen(tmp_path, monkeypatch)
    assert final.check_freeze(tmp_path)[1]["memory"] == "off"
    save(tmp_path / "library.json", {"learned": "test feedback"})
    with pytest.raises(ValueError, match="library"):
        final.check_freeze(tmp_path)
    frozen(tmp_path, monkeypatch)
    study = final.read(tmp_path / "study.json")
    study["model"] = "different"
    save(tmp_path / "study.json", study)
    with pytest.raises(ValueError, match="provider"):
        final.check_freeze(tmp_path)


def test_test_runner_rejects_family_selection_after_freeze(tmp_path, monkeypatch):
    frozen(tmp_path, monkeypatch)
    study = final.read(tmp_path / "study.json")
    study["tasks"] = [{"task_id": "easier-5", "split": "test"}]
    save(tmp_path / "study.json", study)
    with pytest.raises(ValueError, match="split"):
        final.check_freeze(tmp_path)
