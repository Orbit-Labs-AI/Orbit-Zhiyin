"""scripts/check-repository.py on a throwaway git repository: tracked files only, retired
directories, and docs navigation registration."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check-repository.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_repository", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "docs/guide").mkdir(parents=True)
    (root / "uv.lock").write_text("")
    (root / "pnpm-lock.yaml").write_text("")
    (root / "docs/README.md").write_text("# Docs\n\n- [Guide](guide/README.md)\n")
    (root / "docs/guide/README.md").write_text("# Guide\n\n- [Setup](setup.md)\n")
    (root / "docs/guide/setup.md").write_text("# Setup\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    return root


def test_clean_repository_passes(checker, repo):
    assert checker.check(repo, {}) == []


def test_untracked_files_are_ignored(checker, repo):
    (repo / "docs/plan").mkdir()
    (repo / "docs/plan/draft.md").write_text("[gone](missing.md)\n")
    (repo / "src").mkdir()
    (repo / "src/old.py").write_text("")
    assert checker.check(repo, {}) == []


def test_tracked_files_in_retired_directories_fail(checker, repo):
    (repo / "docs/plan").mkdir()
    (repo / "docs/plan/draft.md").write_text("# Draft\n")
    git(repo, "add", "docs/plan/draft.md")
    errors = checker.check(repo, {})
    assert "retired directory contains tracked files: docs/plan" in errors
    assert "docs/plan/draft.md: not linked from docs/README.md (register it in the docs navigation)" in errors


def test_unregistered_document_fails_until_linked(checker, repo):
    (repo / "docs/guide/new.md").write_text("# New\n")
    git(repo, "add", "docs/guide/new.md")
    assert checker.check(repo, {}) == [
        "docs/guide/new.md: not linked from docs/README.md (register it in the docs navigation)"]
    # A known, owned exception is tolerated...
    assert checker.check(repo, {"docs/guide/new.md": "owner follow-up"}) == []
    # ...and must be dropped from the exception list once it is linked (via a section README).
    (repo / "docs/guide/README.md").write_text("# Guide\n\n- [Setup](setup.md)\n- [New](new.md)\n")
    assert checker.check(repo, {}) == []
    assert checker.check(repo, {"docs/guide/new.md": "owner follow-up"}) == [
        "docs/guide/new.md: now registered, remove it from UNREGISTERED in check-repository.py"]


def test_broken_link_in_tracked_document_fails(checker, repo):
    (repo / "docs/guide/setup.md").write_text("# Setup\n\n[next](next.md)\n")
    assert checker.check(repo, {}) == ["docs/guide/setup.md: missing local link next.md"]


def test_missing_workspace_lock_fails(checker, repo):
    git(repo, "rm", "-q", "--cached", "uv.lock")
    assert checker.check(repo, {}) == [
        "workspace locks must be ['pnpm-lock.yaml', 'uv.lock'], found ['pnpm-lock.yaml']"]


def test_current_repository_passes(checker):
    assert checker.check() == []
