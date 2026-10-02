"""Synthetic canonical stores for cache tests: fictional Codex logs, never local history."""

import json
from pathlib import Path

from tandem_backend.data_access.ingest import ingest

PROMPTS = (
    "请修复 src/app.py 的测试并运行 pytest。",
    "以后这个项目都用中文回答。",
    "没看懂，换个直观的例子。",
    "只修改 docs/guide.md，不要推送。",
)


def write_session(folder: Path, index: int, *, follow_up: str | None = None) -> None:
    sid = f"synthetic-{index:05d}"
    day = 1 + index % 28

    def ts(second: int) -> str:
        return f"2026-02-{day:02d}T{(index // 60) % 24:02d}:{index % 60:02d}:{second:02d}Z"

    rows = [
        {"type": "session_meta", "timestamp": ts(0), "payload": {
            "id": sid, "cwd": f"/fictional/project-{index % 3}", "source": "cli",
            "thread_source": "user", "cli_version": "synthetic"}},
        {"type": "event_msg", "timestamp": ts(1), "payload": {"type": "task_started", "turn_id": f"turn-{index}"}},
        {"type": "turn_context", "timestamp": ts(1), "payload": {
            "turn_id": f"turn-{index}", "model": f"fixture-model-{index % 2}"}},
        {"type": "response_item", "timestamp": ts(2), "metadata": {"user_input_order": 3}, "payload": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": PROMPTS[index % len(PROMPTS)]}]}},
        {"type": "response_item", "timestamp": ts(3), "payload": {
            "type": "function_call", "name": "exec_command", "call_id": f"c-{index}",
            "arguments": '{"cmd":"pytest"}'}},
        {"type": "response_item", "timestamp": ts(4), "payload": {
            "type": "function_call_output", "call_id": f"c-{index}", "output": '{"exit_code":%d}' % (index % 2)}},
        {"type": "response_item", "timestamp": ts(5), "payload": {
            "type": "message", "role": "assistant", "channel": "final",
            "content": [{"type": "output_text", "text": "已完成。"}]}},
    ]
    if follow_up is not None:
        rows.append({"type": "response_item", "timestamp": ts(6), "metadata": {"user_input_order": 7}, "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": follow_up}]}})
    (folder / f"{sid}.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def build_home(tmp_path: Path, count: int) -> tuple[Path, Path]:
    """Ingest ``count`` fictional sessions; returns (home, source root)."""
    source = tmp_path / "synthetic-source"
    folder = source / "sessions"
    folder.mkdir(parents=True)
    for index in range(count):
        write_session(folder, index)
    home = tmp_path / "home"
    ingest(home, "codex", source)
    return home, source


def reingest(home: Path, source: Path) -> None:
    ingest(home, "codex", source)


def normalized(result: dict) -> str:
    """Canonical JSON without the per-request freshness block."""
    return json.dumps({k: v for k, v in result.items() if k != "freshness"},
                      ensure_ascii=False, sort_keys=True)
