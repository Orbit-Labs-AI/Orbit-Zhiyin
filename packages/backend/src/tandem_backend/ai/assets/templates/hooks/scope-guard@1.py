"""Tandem hook template scope-guard@1 (stdlib only). Usage: python3 scope-guard@1.py --config cfg.json < event.json

Blocks Bash commands that start with any configured prefix in `command_heads`.
Pure decision logic lives in `decide(event, config, state) -> (allow|warn|block, message)`;
`_main()` only handles stdin, config and the per-session state file.
"""

from __future__ import annotations

import json
import re
import sys

HOOK_ID = "scope-guard"
_TWO_WORD = {"git", "npm", "pnpm", "yarn", "uv", "cargo", "go", "make", "python", "python3", "npx", "bun"}


def command_head(command: str) -> str:
    words = str(command or "").split()
    if len(words) > 1 and words[0] in _TWO_WORD:
        return " ".join(words[:2])
    return words[0] if words else ""


def failed(event: dict) -> bool:
    if event.get("hook_event_name") == "PostToolUseFailure":
        return True
    response = event.get("tool_response")
    if not isinstance(response, dict):
        return False
    code = response.get("exit_code", response.get("exitCode"))
    return response.get("success") is False or bool(response.get("is_error")) or code not in (None, 0)


def matches(command: str, heads) -> bool:
    command = " ".join(str(command or "").split())
    return any(command == h or command.startswith(h + " ") for h in heads or [] if h)


def decide(event: dict, config: dict, state: dict) -> tuple[str, str | None]:
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "Bash":
        return "allow", None
    command = (event.get("tool_input") or {}).get("command", "")
    if matches(command, config.get("command_heads")):
        return "block", config.get("message") or "这个命令超出约定范围，先和用户确认。"
    return "allow", None


def _main() -> int:
    import argparse
    import os
    import tempfile
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args, _ = parser.parse_known_args()
    try:
        config = json.loads(Path(args.config).read_text()) if args.config else {}
        event = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return 0  # fail open: a broken hook must never stop the agent
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("session_id") or "none"))[:80]
    folder = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "tandem-hooks"
    path = folder / f"{sid}-{HOOK_ID}.json"
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    decision, message = decide(event, config, state)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))
    except OSError:
        pass
    if decision == "block":
        print(message or "blocked by tandem hook", file=sys.stderr)
        return 2
    if decision == "warn" and message:
        print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
