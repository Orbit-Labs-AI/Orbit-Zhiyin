"""Task registry: plain-dict TaskSpecs (contract C1) from the task modules, with defaults."""

from __future__ import annotations

import importlib
import json
import logging

log = logging.getLogger(__name__)

TASK_MODULES = ("orbit_backend.ai.tasks_analysis", "orbit_backend.ai.tasks_v1", "orbit_backend.ai.tasks_expert", "orbit_backend.ai.generate")
ENGINES = ("claude_code", "codex", "api_key", "fake")
STAGES = ("pack", "analyse", "draft", "check", "replay", "review", "cross")
_extra: dict[str, dict] = {}
_missing: set[str] = set()


def _prompt(pack: dict) -> str:
    return json.dumps(pack.get("content", {}), ensure_ascii=False, sort_keys=True, indent=1)


def normalize(spec: dict) -> dict:
    """Fill C1 defaults; returns a new dict."""
    tier = spec.get("tier", "L2")
    slot = spec.get("slot", "cheap")
    task = {"tier": tier, "slot": slot, "prompt_version": "1", "schema_version": "1",
            "input_budget": 8000, "out_budget": 2000,
            "max_budget_usd": 0.1 if slot == "cheap" else 0.5,
            "timeout_s": 120 if tier == "L2" else 180, "engines": ENGINES, "pack_items": [],
            "requires_preview": False, "cache_ttl_s": None, "stages": ["pack", "draft"],
            "system": "", "schema": {"type": "object"}, "build_prompt": _prompt,
            "validate": None, "fallback": None, "finalize": None, "run": None}
    task.update({key: value for key, value in spec.items() if value is not None})
    task["engines"] = tuple(task["engines"])
    task["stages"] = [stage for stage in task["stages"] if stage in STAGES]
    return task


def tasks() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for name in TASK_MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError as error:
            if name not in _missing:
                _missing.add(name)
                log.info("AI task module %s unavailable: %s", name, error)
            continue
        for task_id, spec in (getattr(module, "TASKS", None) or {}).items():
            found[task_id] = normalize({**spec, "task_id": task_id})
    found.update(_extra)
    return found


def get(task_id: str) -> dict | None:
    return tasks().get(task_id)


def register(spec: dict) -> dict:
    task = normalize(spec)
    _extra[task["task_id"]] = task
    return task


def unregister(task_id: str) -> None:
    _extra.pop(task_id, None)
