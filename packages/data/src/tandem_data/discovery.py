"""Path allowlists. Discovery lists candidates; scan requires an explicit agent/root."""

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InputFile:
    path: Path
    role: str = "transcript"


def candidates(home: Path | None = None) -> list[dict]:
    home = home or Path.home()
    roots = {
        "claude_code": [home / ".claude", *sorted(home.glob(".claude-*"))],
        "codex": [home / ".codex"],
        "dsh": [home / ".dsh"],
        "pi": [home / ".pi/agent"],
        "hermes": [home / ".hermes"],
        "opencode": [
            Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) / "opencode"
        ],
        "kimi": [home / ".kimi-code"],
    }
    for agent, variable in (
        ("claude_code", "CLAUDE_CONFIG_DIR"),
        ("codex", "CODEX_HOME"),
        ("dsh", "DSH_HOME"),
        ("hermes", "HERMES_HOME"),
        ("pi", "PI_CODING_AGENT_DIR"),
        ("kimi", "KIMI_CODE_HOME"),
    ):
        if os.getenv(variable):
            roots[agent].append(Path(os.environ[variable]).expanduser())
    return [
        {"agent": agent, "root": str(root.resolve())}
        for agent, paths in roots.items()
        for root in dict.fromkeys(paths)
        if root.is_dir()
    ]


def inputs(agent: str, root: Path):
    patterns = {
        "claude_code": ("projects/**/*.jsonl",),
        "codex": (
            "sessions/**/*.jsonl",
            "sessions/**/*.jsonl.zst",
            "archived_sessions/**/*.jsonl",
            "archived_sessions/**/*.jsonl.zst",
        ),
        "dsh": ("sessions/**/session*.jsonl", "sessions/**/session*.jsonl.zstd"),
        "pi": ("sessions/**/*.jsonl",),
        "hermes": ("state.db",),
        "opencode": ("opencode.db", "opencode.dev.db"),
        "kimi": ("session_index.jsonl", "sessions/*/*/agents/*/wire.jsonl"),
    }
    if agent not in patterns:
        raise ValueError(
            f"No discovery rules for {agent}; use capture_stream with a registered mapper"
        )
    found = sorted(
        {
            path
            for pattern in patterns[agent]
            for path in root.glob(pattern)
            if path.is_file() and path.resolve().is_relative_to(root.resolve())
        }
    )
    if agent == "dsh":
        generations = {}
        for path in found:
            match = re.fullmatch(r"session(?:\.v(\d+))?\.jsonl(?:\.zstd)?", path.name)
            if match:
                generations.setdefault(path.parent, []).append((int(match[1] or 0), path))
        for entries in generations.values():
            highest = max(version for version, _ in entries)
            for version, path in entries:
                yield InputFile(path, "transcript" if version == highest else "legacy_transcript")
    else:
        for path in found:
            yield InputFile(
                path,
                "session_index"
                if path.name == "session_index.jsonl" and agent == "kimi"
                else "subagent_transcript"
                if "subagents" in path.parts
                else "transcript",
            )
