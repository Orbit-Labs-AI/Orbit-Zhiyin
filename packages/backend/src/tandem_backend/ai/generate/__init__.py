"""Generative recommendation tasks: templates + typed slots + three self-checks.

Exports `TASKS` (contract C1 TaskSpec dicts) for the ai registry. This package never imports
recommend / install / features; they call the AI service instead.
"""

from __future__ import annotations

from . import diagnose, rerank
from .tasks import TASKS as _GENERATE

TASKS: dict[str, dict] = {**_GENERATE, diagnose.TASK["task_id"]: diagnose.TASK, rerank.TASK["task_id"]: rerank.TASK}

__all__ = ["TASKS"]
