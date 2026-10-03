from __future__ import annotations

import time

import pytest

from tandem_backend.ai.generate.hooks_replay import replay
from tandem_backend.ai.generate.templates import get


# Fixtures use the canonical tool_call.status vocabulary written by the connectors
# (completed / failed / unknown / declined / orphan_result), not the legacy "ok".
def _call(head=None, status="completed", tool="Bash", exts=()):
    ok = status == "completed"
    failed = status == "failed"
    return {"tool_name": tool, "kind": "shell" if head else "edit", "command_head": head, "status": status,
            "error_class": "exit_nonzero" if failed else None,
            "exit_code": (0 if ok else 1 if failed else None) if head else None, "file_exts": list(exts)}


FAILING = {"session_uid": "s1", "title": "反复失败", "evidence": True,
           "calls": [_call("pnpm test", "failed")] * 4}
NORMAL = {"session_uid": "s2", "title": "正常", "evidence": False,
          "calls": [_call(tool="Edit", exts=[".ts"]), _call("pnpm test"), _call("git commit")]}


def test_recall_and_no_false_block():
    result = replay(get("retry-breaker"), {"threshold": 3, "message": "stop", "command_heads": []}, [FAILING, NORMAL])
    assert result["status"] == "ok"
    assert result["recall"] == 1.0 and result["false_block"] == 0
    assert [s["result"] for s in result["sessions"]] == ["pass", "pass"]


def test_normal_session_with_completed_calls_is_not_blocked():
    # 4 successful runs of the same command: the streak counter must reset each time -> no block.
    normal = {"session_uid": "n", "title": "", "evidence": False, "calls": [_call("pnpm test")] * 4}
    result = replay(get("retry-breaker"), {"threshold": 2, "command_heads": []}, [normal])
    assert result["false_block"] == 0 and result["status"] != "blocked"


def test_two_consecutive_failures_reach_recall_one_at_threshold_two():
    evidence = {"session_uid": "e", "title": "", "evidence": True, "calls": [_call("pnpm test", "failed")] * 3}
    result = replay(get("retry-breaker"), {"threshold": 2, "command_heads": []}, [evidence])
    # failures #1 and #2 -> streak 2 -> the third PreToolUse is blocked.
    assert result["recall"] == 1.0 and result["status"] == "ok"


@pytest.mark.parametrize("status", ["unknown", "declined", "orphan_result"])
def test_unknown_outcome_is_neither_success_nor_failure(status):
    # failed, failed, <unknown>, then a 4th call: if unknown counted as success the streak would reset
    # and nothing would fire; if it counted as failure the streak would be 3 one call earlier.
    calls = [_call("pnpm test", "failed"), _call("pnpm test", "failed"), _call("pnpm test", status),
             _call("pnpm test", "failed")]
    session = {"session_uid": "u", "title": "", "evidence": True, "calls": calls}
    fired = replay(get("retry-breaker"), {"threshold": 2, "command_heads": []}, [session])
    assert fired["recall"] == 1.0  # streak of 2 survives the unknown call -> blocked at its PreToolUse
    only_unknown = {"session_uid": "u2", "title": "", "evidence": True, "calls": [_call("pnpm test", status)] * 5}
    assert replay(get("retry-breaker"), {"threshold": 2, "command_heads": []}, [only_unknown])["recall"] == 0


def test_untriggered_when_threshold_too_high():
    result = replay(get("retry-breaker"), {"threshold": 5, "command_heads": []}, [FAILING, NORMAL])
    assert result["status"] == "untriggered" and result["recall"] == 0
    assert result["sessions"][0]["result"] == "fail"


def test_false_block_marks_blocked():
    # verify-before-commit with a verify command the normal session never runs blocks its commit.
    result = replay(get("verify-before-commit"), {"command_heads": ["pnpm lint"]}, [FAILING, NORMAL])
    assert result["status"] == "blocked" and result["false_block"] == 1
    assert result["sessions"][1]["result"] == "fail"


def test_skipped_without_calls():
    assert replay(get("retry-breaker"), {}, [])["status"] == "skipped"
    assert replay(get("paragraph"), {}, [FAILING])["status"] == "skipped"


@pytest.mark.serial
def test_replay_performance_8_sessions_x_200_calls():
    calls = ([_call(tool="Edit", exts=[".py"]), _call("pytest", "failed"), _call("pytest")] * 67)[:200]
    sessions = [{"session_uid": f"s{i}", "title": "", "evidence": i < 3, "calls": calls} for i in range(8)]
    template = get("retry-breaker")
    replay(template, {"threshold": 2, "command_heads": []}, sessions[:1])  # warm module cache
    start = time.perf_counter()
    replay(template, {"threshold": 2, "command_heads": []}, sessions)
    assert time.perf_counter() - start < 0.3
