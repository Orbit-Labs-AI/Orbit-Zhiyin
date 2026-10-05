"""Scripted stand-in for the runner's RunContext (contract C2) used by the generate tests."""

from __future__ import annotations

import sys
from pathlib import Path

from orbit_backend.ai.generate.util import CallFailed

sys.path.insert(0, str(Path(__file__).parent))


class FakeCtx:
    """`responses` is consumed in order: a dict is returned, an Exception is raised.

    Like the runner, a response that fails `validate` is retried once with the next scripted
    response; a second failure raises CallFailed.
    """

    def __init__(self, pack: dict, responses=(), template: str = "v1", params: dict | None = None,
                 task: dict | None = None):
        self.job_id, self.engine = "job_test", "fake"
        self.pack, self.template, self.params, self.task = pack, template, params or {}, task or {}
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.stages: list[tuple[str, str, str | None]] = []
        self.lines: list[str] = []

    def _next(self):
        if not self.responses:
            raise CallFailed("no scripted response")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def call(self, *, system=None, prompt=None, schema=None, slot=None, validate=None, task_id=None) -> dict:
        self.calls.append({"system": system, "prompt": prompt, "schema": schema, "slot": slot})
        for _ in range(2):
            output = self._next()
            if not validate or not validate(output, self.pack):
                return output
        raise CallFailed("validation failed after retry")

    def stage(self, stage_id, status, message=None):
        self.stages.append((stage_id, status, message))

    def stage_status(self, stage_id):
        found = [s for s in self.stages if s[0] == stage_id]
        return found[-1][1] if found else None

    def log(self, line):
        self.lines.append(line)

    def progress(self, n, total):
        pass

    def cancelled(self) -> bool:
        return False

    def reads(self):
        raise RuntimeError("no orbit.db in generate tests")


def hook_pack(**overrides) -> dict:
    """A small pack with the hook items (C4 shapes)."""
    calls_fail = [{"tool_name": "Bash", "kind": "shell", "command_head": "pnpm test", "status": "failed",
                   "error_class": "exit_nonzero", "exit_code": 1, "file_exts": []}] * 4
    calls_ok = [{"tool_name": "Edit", "kind": "edit", "command_head": None, "status": "completed",
                 "error_class": None, "exit_code": None, "file_exts": [".ts"]},
                {"tool_name": "Bash", "kind": "shell", "command_head": "pnpm test", "status": "completed",
                 "error_class": None, "exit_code": 0, "file_exts": []}]
    content = {
        "goal": {"text": "减少测试命令反复失败", "source": "candidate"},
        "evidence": [{"event_uid": "e1", "session_uid": "s1", "kind": "error", "text": "pnpm test failed"}],
        "friction": {"problems": [{"problem_id": "p1", "type": "tool_env_failure", "key": "pnpm test",
                                   "sessions": 3, "weekly_count": 5}],
                     "error_classes": [{"error_class": "exit_nonzero", "count": 9}], "corrections": 2},
        "tool_evidence": {"command_heads": ["pnpm test", "pnpm lint", "git commit"], "file_exts": [".ts", ".py"],
                          "verify_commands": ["pnpm test", "pnpm lint"],
                          "failure_runs": [{"command_head": "pnpm test", "error_class": "exit_nonzero", "runs": 4}]},
        "replay_calls": [{"session_uid": "s1", "title": "失败会话", "evidence": True, "calls": calls_fail},
                         {"session_uid": "s2", "title": "正常会话", "evidence": False, "calls": calls_ok}],
        "inventory": [{"type": "skill", "name": "existing-skill", "enabled": True}],
    }
    content.update(overrides.pop("content", {}))
    pack = {"task_id": "generate.hook", "goal": "减少测试命令反复失败", "goal_source": "candidate",
            "items": [{"key": k, "enabled": True} for k in content], "content": content,
            "refs": {"session": ["s1", "s2"], "event": ["e1", "e2", "e3", "e4"], "problem": ["p1"],
                     "candidate": [], "metric": []},
            "numbers": [0.23, 9, 42], "total_tokens": 3200, "redaction_hits": 1, "batches": None,
            "preview_digest": "sha256:test"}
    pack.update(overrides)
    return pack
