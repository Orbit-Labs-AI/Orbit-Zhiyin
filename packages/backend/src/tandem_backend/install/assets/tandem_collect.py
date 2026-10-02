#!/usr/bin/env python3
"""Tandem collection hook (IN-07 / DT-16): append one JSON line per agent event.

Read-only: never prints a hook decision, never blocks, always exits 0. Stdlib only.

  tandem_collect.py hook --agent claude_code --out EVENTS          (hook JSON on stdin)
  tandem_collect.py statusline --agent claude_code --out EVENTS [--wrap CMD]
  tandem_collect.py notify --agent codex --out EVENTS JSON         (Codex ``notify``)
"""

import json
import os
import subprocess
import sys
import time

VERSION = 1
MAX_BYTES = 16 * 1024 * 1024  # rotate events.jsonl to events.jsonl.1 past this size
TEXT_MAX = 300
CONTEXT_KEYS = ("used_percentage", "context_window_size", "total_input_tokens", "total_output_tokens")


def _args(argv):
    opts, rest, i = {}, [], 0
    while i < len(argv):
        if argv[i] in ("--agent", "--out", "--wrap") and i + 1 < len(argv):
            opts[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return opts, rest


def _short(value):
    return value[:TEXT_MAX] if isinstance(value, str) else None


def _append(out, record):
    record = {"v": VERSION, "ts": int(time.time() * 1000), **{k: v for k, v in record.items() if v is not None}}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        if os.path.getsize(out) > MAX_BYTES:
            os.replace(out, out + ".1")
    except OSError:
        pass
    line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(out, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)  # one write per line: O_APPEND keeps concurrent hooks whole
    finally:
        os.close(fd)


def hook(agent, out, raw):
    data = json.loads(raw or "{}")
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    _append(out, {"agent": agent, "event": data.get("hook_event_name"), "session_id": data.get("session_id"),
                  "cwd": data.get("cwd"), "transcript_path": data.get("transcript_path"),
                  "tool": data.get("tool_name"), "command": _short(tool_input.get("command")),
                  "notification_type": data.get("notification_type"), "message": _short(data.get("message")),
                  "trigger": data.get("trigger")})


def _context(data):
    ctx = data.get("context_window")
    if not isinstance(ctx, dict):
        return None
    out = {k: ctx[k] for k in CONTEXT_KEYS if isinstance(ctx.get(k), (int, float))}
    usage = ctx.get("current_usage")
    if isinstance(usage, dict):
        out["used_tokens"] = sum(usage.get(k) or 0 for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens") if isinstance(usage.get(k), int))
    return out or None


def statusline(agent, out, raw):
    data = json.loads(raw or "{}")
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    record = {"agent": agent, "event": "StatusLine", "session_id": data.get("session_id"),
              "model": model.get("id"), "context": _context(data),
              "exceeds_200k": data.get("exceeds_200k_tokens")}
    key = json.dumps(record, sort_keys=True)
    marker = os.path.join(os.path.dirname(out), ".statusline-last")
    try:
        with open(marker, encoding="utf-8") as f:
            if f.read() == key:
                return  # the status line refreshes often; only log changes
    except OSError:
        pass
    _append(out, record)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(key)


def notify(agent, out, payload):
    data = json.loads(payload or "{}")
    kind = str(data.get("type") or "")
    event = "Stop" if kind == "agent-turn-complete" else ("PermissionRequest" if "approval" in kind else kind)
    _append(out, {"agent": agent, "event": event, "native_type": kind,
                  "session_id": data.get("thread-id") or data.get("session_id"), "turn_id": data.get("turn-id"),
                  "cwd": data.get("cwd")})


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    opts, rest = _args(argv[2:])
    agent, out = opts.get("agent") or "unknown", opts.get("out")
    raw = b""
    if mode in ("hook", "statusline"):
        raw = sys.stdin.buffer.read()
    try:
        if out and mode == "hook":
            hook(agent, out, raw.decode("utf-8", "replace"))
        elif out and mode == "statusline":
            statusline(agent, out, raw.decode("utf-8", "replace"))
        elif out and mode == "notify":
            notify(agent, out, rest[-1] if rest else "{}")
    except Exception:  # noqa: BLE001 - collection must never disturb the agent
        pass
    if mode == "statusline" and opts.get("wrap"):
        try:  # keep the user's own status line: same stdin, its stdout is the line shown
            done = subprocess.run(opts["wrap"], shell=True, input=raw, stdout=subprocess.PIPE, timeout=10)
            sys.stdout.buffer.write(done.stdout)
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
