"""Known complete checks survive wrappers; mentions and ambiguous scripts abstain."""

import json

import pytest

from tandem_data.command_spec import command_spec


@pytest.mark.parametrize(
    "command,kind",
    [
        ("pytest tests/unit", "test"),
        (".venv/bin/python3.13 -m pytest -q", "test"),
        ("uv run --locked --no-sync ruff check src", "lint"),
        ("cd packages/backend && uv run pytest tests", "test"),
        ("pnpm check", "check"),
        ("pnpm --filter @tandem/connectors check", "check"),
        ("pnpm exec tsc --noEmit", "typecheck"),
        ("npm run test", "test"),
        ("swift test --package-path packages/catalog-macos", "test"),
        ("env SECRET=do-not-save pytest tests", "test"),
        ("/bin/zsh -lc 'cd repo && uv run pytest -q'", "test"),
    ],
)
def test_complete_validation_commands(command, kind):
    spec = command_spec(command, cwd="/synthetic", project_id="project")
    assert spec["command_complete"] is True
    assert spec["validation_kind"] == kind
    assert spec["validation_scope"] == {"project_id": "project", "coverage": "unspecified"}
    assert "do-not-save" not in json.dumps(spec)
    assert "tests/unit" not in json.dumps(spec)


@pytest.mark.parametrize(
    "command",
    [
        "echo pytest",
        "pytest --collect-only",
        "pytest --help",
        "ruff check --show-files",
        "cargo test --no-run",
        "go test -list=.",
        "pnpm test --dry-run",
        "pytest && echo ok",
        "echo done; pytest",
        "pytest || true",
        "pytest &",
        "pytest | tee log",
        "pytest > log",
        "pytest &&",
        "&& pytest",
        "pytest $(echo tests)",
        "pytest `echo tests`",
        "cd missing; pytest",
        "pytest\nrm file",
        'pytest "unterminated',
    ],
)
def test_ambiguous_or_nonexecuting_commands_are_never_validation_facts(command):
    assert command_spec(command)["validation_kind"] is None


def test_directory_prefix_and_argument_digest_are_preserved_without_raw_arguments():
    a = command_spec("cd repo && pytest private-file --secret unique-secret", cwd="/synthetic")
    b = command_spec("cd repo && pytest other-file --secret unique-secret", cwd="/synthetic")
    assert a["cwd"] == "/synthetic/repo"
    assert a["argv_digest"] != b["argv_digest"]
    assert "unique-secret" not in json.dumps(a)
    assert command_spec(None) is None
