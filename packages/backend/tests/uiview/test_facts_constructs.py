"""Construct checks for the persona facts: validation commands and structured openings."""

from __future__ import annotations

import pytest

from orbit_backend.uiview import facts, persona


@pytest.mark.parametrize("command", [
    "pytest -q tests/uiview", "uv run pytest -x", "uv run --no-sync ruff check src",
    "python -m pytest", "python3 -m mypy pkg", "npx vitest run", "npm test", "pnpm check",
    "pnpm run typecheck", "yarn lint:fix", "cargo test --all", "cargo build", "go vet ./...",
    "swift build", "make test", "xcodebuild test -scheme App", "tsc --noEmit",
    "CI=1 npm run test", "cd pkg && pnpm test", "git add . ; pytest", "./gradlew check",
])
def test_validation_commands(command):
    assert facts.is_validation_command(command)


@pytest.mark.parametrize("command", [
    # Audit false positives: the word appears, but the command does not validate anything.
    "cd build", "ls test/", "cat tests/test_a.py", "rm -rf build", "git diff --check",
    "docker build .", "mkdir -p test", "rg check src", "echo 'run the tests'",
    "git checkout main", "npm install", "pnpm add -D vitest", "cargo add serde",
    "python script.py --check", "", None,
])
def test_non_validation_commands(command):
    assert not facts.is_validation_command(command)


@pytest.mark.parametrize(("text", "flagged", "expected"), [
    ("修一下 README.md 里的错别字", False, 0),            # a file name is not a plan
    ("Traceback (most recent call last):\n" + "x" * 400, False, 0),  # long paste ≠ structure
    ("1. 先读代码\n2. 再改测试", False, 1),                # ≥ 2 list items
    ("实现登录，验收：能用测试账号登录", False, 1),        # acceptance words
    ("按 spec 实现", False, 1),
    ("随便看看", True, 1),                                # instruction flagged it
    ("随便看看", False, 0),
    (None, False, None),
])
def test_structured_opening(text, flagged, expected):
    assert facts.structured_opening(text, flagged) == expected


def test_evidence_splits_requested_and_agent_run_verification():
    rows = [{"id": "s1", "d": "2026-09-01", "p": None, "msgs": 2, "steps": 3}]
    # [steps, verify, requested, ran]: user asked (and agent ran), agent ran alone, neither.
    aux = {"s1": {"open": 1, "turns": [[1, 1, 1, 1], [1, 1, 0, 1], [1, 0, 0, 0]]}}
    p = {"axes": [{"k": "I", "n_units": 1, "k_units": 0}]}
    ev = persona.evidence(rows, aux, p, {"verify": 100.0, "verify_n": 1}, {})
    assert ev["V"]["requested_turns"] == 1 and ev["V"]["agent_only_turns"] == 1
    assert ev["V"]["detail"] == "用户要求验证 1 轮 · 仅 Agent 自行运行 1 轮"
    # Old two-element turns: the split is unknown, not 0.
    old = persona.evidence(rows, {"s1": {"open": 1, "turns": [[1, 1]]}}, p,
                           {"verify": 100.0, "verify_n": 1}, {})
    assert old["V"]["requested_turns"] is None and old["V"]["detail"] is None


def test_shell_text_unwraps_codex_argv():
    assert facts.shell_text("bash", '["bash", "-lc", "cd app && pnpm test"]') == \
        "cd app && pnpm test"
    assert facts.is_validation_command(facts.shell_text("bash", '["bash", "-lc", "pnpm test"]'))
    assert not facts.is_validation_command(facts.shell_text("bash", '["bash", "-lc", "ls test"]'))
    assert facts.shell_text("pytest", None) == "pytest"
    assert facts.shell_text("cd", "cd build") == "cd build"
