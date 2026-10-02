"""Shared AI test helpers (uniquely named to avoid conftest module clashes)."""
from __future__ import annotations

ANSWER = {"type": "object", "required": ["answer"], "additionalProperties": False,
          "properties": {"answer": {"type": "string"}}}




def answer_task(task_id: str = "test.echo", **overrides) -> dict:
    spec = {"task_id": task_id, "tier": "L2", "slot": "cheap", "system": "Return JSON.",
            "schema": ANSWER, "pack_items": [("goal", True)],
            "fallback": lambda pack, reason: {"answer": f"fallback:{reason}"}}
    spec.update(overrides)
    return spec
