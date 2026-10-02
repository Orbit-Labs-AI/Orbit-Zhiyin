"""Objective validation evidence, separate from subjective acceptance."""

import re


def legacy_objective_candidates(calls):
    """Keep the v1 candidate fields; these never establish task success."""
    return {"explicit_tool_failures": sum(c.get("status") == "failed" for c in calls) if calls is not None else None,
                 "validation_command_candidates": sum(bool(re.search(r"\b(test|pytest|lint|typecheck|build)\b", c.get("command_head") or "")) for c in calls or []),
                 "task_success": None, "validation_scope": None}
