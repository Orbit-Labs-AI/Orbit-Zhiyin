from __future__ import annotations

import time

from tandem_backend.ai.generate.hooks_replay import replay
from tandem_backend.ai.generate.templates import get


def _call(head=None, status="ok", tool="Bash", exts=()):
    return {"tool_name": tool, "kind": "shell" if head else "edit", "command_head": head, "status": status,
            "error_class": None if status == "ok" else "exit_nonzero",
            "exit_code": (0 if status == "ok" else 1) if head else None, "file_exts": list(exts)}


FAILING = {"session_uid": "s1", "title": "反复失败", "evidence": True,
           "calls": [_call("pnpm test", "error")] * 4}
NORMAL = {"session_uid": "s2", "title": "正常", "evidence": False,
          "calls": [_call(tool="Edit", exts=[".ts"]), _call("pnpm test"), _call("git commit")]}


def test_recall_and_no_false_block():
    result = replay(get("retry-breaker"), {"threshold": 3, "message": "stop", "command_heads": []}, [FAILING, NORMAL])
    assert result["status"] == "ok"
    assert result["recall"] == 1.0 and result["false_block"] == 0
    assert [s["result"] for s in result["sessions"]] == ["pass", "pass"]


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


def test_replay_performance_8_sessions_x_200_calls():
    calls = ([_call(tool="Edit", exts=[".py"]), _call("pytest", "error"), _call("pytest")] * 67)[:200]
    sessions = [{"session_uid": f"s{i}", "title": "", "evidence": i < 3, "calls": calls} for i in range(8)]
    template = get("retry-breaker")
    replay(template, {"threshold": 2, "command_heads": []}, sessions[:1])  # warm module cache
    start = time.perf_counter()
    replay(template, {"threshold": 2, "command_heads": []}, sessions)
    assert time.perf_counter() - start < 0.3
