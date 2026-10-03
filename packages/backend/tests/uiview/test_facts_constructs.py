"""Construct checks for the persona facts: validation commands and structured openings."""

from __future__ import annotations

import pytest

from orbit_backend.uiview import facts, persona

from .l1_builder import *  # noqa: F403 - pytest fixtures
from .l1_builder import MIN, T0


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
    assert ev["V"]["detail"] == "你要求验证 1 轮 · 仅 Agent 自行运行 1 轮"
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


# -- persona signal inputs (uiview-persona-v1) ------------------------------------------------
def test_rollback_commands_are_matched_on_the_git_subcommand():
    from orbit_backend.uiview.facts import is_rollback_command
    assert is_rollback_command("git revert HEAD")
    assert is_rollback_command("cd repo && git reset --hard origin/main")
    assert is_rollback_command("git restore src/app.py")
    assert is_rollback_command("git checkout -- src/app.py")
    assert not is_rollback_command("git checkout main")
    assert not is_rollback_command("git reset HEAD~1")  # soft reset keeps the work
    assert not is_rollback_command("echo git revert")


def test_rollback_skips_unstage_and_global_git_options():
    from orbit_backend.uiview.facts import is_rollback_command
    assert not is_rollback_command("git restore --staged src/app.py")  # only unstages
    assert not is_rollback_command("git restore -S src/app.py")
    assert is_rollback_command("git restore --staged --worktree src/app.py")
    assert is_rollback_command("git -C /w/repo revert HEAD")
    assert is_rollback_command("git -C /w/repo reset --hard HEAD~1")
    assert is_rollback_command("git -c core.pager=cat restore src/app.py")
    assert not is_rollback_command("git -C /w/repo status")
    assert not is_rollback_command("git -C /w/repo checkout main")


def test_opening_halves_and_redo_words():
    from orbit_backend.uiview.facts import ACCEPT_RE, REDO_RE, SPEC_RE
    assert SPEC_RE.search("按 docs/plans/sync-plan.md 实现") and SPEC_RE.search("先读 PRD")
    assert not SPEC_RE.search("fix README.md typo")
    assert ACCEPT_RE.search("验收：测试全绿") and not ACCEPT_RE.search("修一下按钮")
    assert REDO_RE.search("把刚才的改动回滚") and REDO_RE.search("please revert that")
    assert not REDO_RE.search("继续")


def test_subagent_peak_concurrency():
    from orbit_backend.uiview.facts import _subagents
    result = {"sessions": [
        {"session_uid": "m", "kind": "main"},
        {"session_uid": "c1", "root_uid": "m", "started_at": 0, "ended_at": 10},
        {"session_uid": "c2", "root_uid": "m", "started_at": 5, "ended_at": 12},
        {"session_uid": "c3", "root_uid": "m", "started_at": 20, "ended_at": 30}]}
    root_of = {"m": "m", "c1": "m", "c2": "m", "c3": "m"}
    assert _subagents(result, root_of) == {"m": 2}


def _facts_over(l1, sessions):
    from types import SimpleNamespace
    result = {"sessions": [{"session_uid": uid, "kind": "main", "root_uid": uid, "agent": agent,
                            "features": {"user_message_count": 1, "tool_call_count": 0,
                                         "correction_signal_count": 0}}
                           for uid, agent in sessions]}
    return facts.build_facts(l1.db, result, SimpleNamespace(display_timezone="UTC"))


def test_stop_signal_counts_only_user_stops(l1):
    """``failed`` / ``error`` turns are tool or environment failures, not the user steering."""
    l1.session("s1")
    for i, status in enumerate(("interrupted", "failed", "error", "rejected", "completed")):
        l1.turn("s1", i, status, l1.user("s1", T0 + i * MIN, f"第 {i} 步"))
    wire = facts.aux_units(_facts_over(l1, [("s1", "claude_code")])["aux"]["s1"])
    assert (wire["ik"], wire["kn"]) == (2, 5)


def test_subagent_signal_is_unknown_for_agents_without_child_sessions(l1):
    l1.session("cc1")
    l1.session("gm1", agent="codex")
    aux = _facts_over(l1, [("cc1", "claude_code"), ("gm1", "gemini")])["aux"]
    assert aux["cc1"]["sub"] == 0          # records sub-agents, ran none
    assert aux["gm1"]["sub"] is None       # cannot record them: the signal drops out


def test_redo_words_only_count_in_short_messages():
    assert facts.asks_redo(["把刚才的改动回滚"])
    assert not facts.asks_redo(["log:\n" + "x" * 500 + "\nundo stack overflow"])
    assert not facts.asks_redo([])
