"""Orbit hook template post-edit-check@1 (stdlib only). Usage: python3 post-edit-check@1.py --config cfg.json < event.json

After an Edit/Write on a file matching `file_glob`, reminds the agent to run `command`.
Pure decision logic lives in `decide(event, config, state) -> (allow|warn|block, message)`;
`_main()` only handles stdin, config and the per-session state file.
"""

from __future__ import annotations

import json
import re
import sys

HOOK_ID = "post-edit-check"
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

_EDITS = {"Edit", "Write", "MultiEdit"}


def decide(event: dict, config: dict, state: dict) -> tuple[str, str | None]:
    import fnmatch

    if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") not in _EDITS:
        return "allow", None
    path = str((event.get("tool_input") or {}).get("file_path") or "")
    glob = config.get("file_glob") or "*"
    if not (fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], glob)):
        return "allow", None
    hint = config.get("message") or "改完记得验证。"
    command = config.get("command")
    return "warn", f"{hint}（{command}）" if command else hint


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
    folder = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "orbit-hooks"
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
        print(message or "blocked by orbit hook", file=sys.stderr)
        return 2
    if decision == "warn" and message:
        print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
