"""Known complete checks survive wrappers; mentions and ambiguous scripts abstain."""

import json

import pytest

from orbit_data.command_spec import command_spec


@pytest.mark.parametrize(
    "command,kind",
    [
        ("pytest tests/unit", "test"),
        (".venv/bin/python3.13 -m pytest -q", "test"),
        ("uv run --locked --no-sync ruff check src", "lint"),
        ("cd packages/backend && uv run pytest tests", "test"),
        ("pnpm check", "check"),
        ("pnpm --filter @orbit/connectors check", "check"),
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


@pytest.mark.parametrize("workdir", [5, True, ["sub"], {"path": "sub"}])
def test_non_string_workdir_is_no_cwd(workdir):
    # Tool arguments are model output; a malformed workdir must not raise.
    assert command_spec("cd sub && pytest", cwd=workdir)["cwd"] == "sub"


def test_malformed_workdir_does_not_fail_the_source_import(tmp_path):
    from orbit_data.contract import canonical
    from orbit_data.service import ImportRequest, ImportService
    from orbit_data.store import Store

    rollout = tmp_path / "codex/sessions/rollout-s.jsonl"
    rollout.parent.mkdir(parents=True)
    arguments = json.dumps({"cmd": "cd sub && pytest", "workdir": 5})
    records = [
        {"type": "session_meta", "payload": {"id": "s", "cwd": "/fixture"}},
        {"type": "turn_context", "payload": {"turn_id": "t", "model": "fixture"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "run tests"}},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": "c1",
                "name": "exec_command",
                "arguments": arguments,
            },
        },
        {
            "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        },
    ]
    rollout.write_text("".join(canonical(r) + "\n" for r in records))
    with Store(tmp_path / "data") as store:
        ImportService(store).import_source(ImportRequest("codex", tmp_path / "codex"))
        assert store.db.execute("SELECT count(*) FROM tool_call").fetchone()[0] == 1
