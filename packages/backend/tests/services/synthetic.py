"""Synthetic Codex JSONL trees for service tests and benchmarks; never reads real sessions."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def codex_session_rows(index: int, started: float, turns: int = 2) -> list[dict]:
    """One small synthetic Codex rollout: human task, model usage and a tool call per turn."""
    session = f"00000000-0000-4000-8000-{index:012d}"
    cwd = f"/synthetic/project-{index % 4}"
    rows: list[dict] = [{
        "timestamp": _iso(started), "type": "session_meta",
        "payload": {"id": session, "session_id": session, "timestamp": _iso(started),
                    "cwd": cwd, "model_provider": "openai", "cli_version": "synthetic"},
    }]
    for turn in range(turns):
        at = started + turn * 30
        turn_id = f"turn-{index}-{turn}"
        call = f"call-{index}-{turn}"
        rows += [
            {"timestamp": _iso(at), "type": "event_msg",
             "payload": {"type": "task_started", "turn_id": turn_id, "started_at": int(at)}},
            {"timestamp": _iso(at), "type": "turn_context",
             "payload": {"turn_id": turn_id, "model": "synthetic-model", "cwd": cwd}},
            {"timestamp": _iso(at + 1), "type": "event_msg",
             "payload": {"type": "item_completed", "turn_id": turn_id, "item": {
                 "type": "UserMessage", "id": f"human-{index}-{turn}",
                 "content": [{"type": "text", "text": f"synthetic task {index} step {turn}"}]}}},
            {"timestamp": _iso(at + 2), "type": "response_item",
             "payload": {"type": "function_call", "name": "shell", "call_id": call,
                         "arguments": json.dumps({"command": ["echo", "synthetic"]})}},
            {"timestamp": _iso(at + 3), "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": call,
                         "output": json.dumps({"output": "synthetic",
                                               "metadata": {"exit_code": 0}})}},
            {"timestamp": _iso(at + 4), "type": "token_usage_record",
             "payload": {"response_id": f"resp-{index}-{turn}", "turn_id": turn_id,
                         "usage": {"input_tokens": 100 + index, "cached_input_tokens": 10,
                                   "output_tokens": 20 + turn}}},
            {"timestamp": _iso(at + 5), "type": "event_msg",
             "payload": {"type": "task_complete", "turn_id": turn_id,
                         "completed_at": int(at + 5)}},
        ]
    return rows


def write_codex_tree(root: Path, count: int, *, now: float | None = None, start: int = 0,
                     spacing_hours: float = 12.0) -> list[Path]:
    """Write ``count`` rollouts, newest first; mtimes step back so import batches differ."""
    now = now or datetime.now(UTC).timestamp()
    written = []
    for offset in range(count):
        index = start + offset
        started = now - (index * spacing_hours * 3600) - 60
        day = datetime.fromtimestamp(started, UTC)
        name = f"rollout-{day:%Y-%m-%dT%H-%M-%S}-{index:06d}.jsonl"
        path = root / "sessions" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = codex_session_rows(index, started)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        os.utime(path, (started, started))
        written.append(path)
    return written
