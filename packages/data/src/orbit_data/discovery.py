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
    desktop = home / "Library/Application Support/Claude/local-agent-mode-sessions"
    if desktop.is_dir():
        roots["claude_code"].extend(desktop.glob("**/.claude"))
    found = {
        (agent, str(root.resolve()))
        for agent, paths in roots.items()
        for root in paths
        if root.is_dir()
    }
    return [{"agent": agent, "root": root} for agent, root in sorted(found)]


def inputs(agent: str, root: Path):
    patterns = {
        "claude_code": (
            "projects/**/*.jsonl",
            "projects/**/agent-*.meta.json",
            "projects/**/custom-title.json",
        ),
        "codex": (
            "sessions/**/*.jsonl",
            "sessions/**/*.jsonl.zst",
            "archived_sessions/**/*.jsonl",
            "archived_sessions/**/*.jsonl.zst",
            "session_index.jsonl",
            "state_*.sqlite",
            "external_agent_session_imports.json",
        ),
        "dsh": ("sessions/**/session*.jsonl", "sessions/**/session*.jsonl.zstd"),
        "pi": ("sessions/**/*.jsonl",),
        # Hermes profiles are full homes at <root>/profiles/<name> (hermes_constants.py);
        # inventory/hermes.py scans the same set.
        "hermes": ("state.db", "profiles/*/state.db"),
        # opencode stores opencode.db, or opencode-<channel>.db for non-default
        # installation channels (packages/core/src/database/database.ts).
        "opencode": ("opencode*.db",),
        "kimi": ("session_index.jsonl", "sessions/*/*/agents/*/wire.jsonl"),
    }
    if agent not in patterns:
        raise ValueError(
            f"No discovery rules for {agent}; use capture_stream with a registered mapper"
        )
    # Resolve the root and each directory once: a non-symlink file resolves to its
    # resolved parent plus its name. String prefixes avoid Path.is_relative_to.
    resolved_root = os.path.join(str(root.resolve()), "")
    folders = {}

    def real(folder):
        hit = folders.get(folder)
        if hit is None:
            if folder == folder.parent or folder.name == ".." or os.path.islink(folder):
                hit = os.path.realpath(folder)
            else:
                hit = os.path.join(real(folder.parent), folder.name)
            folders[folder] = hit
        return hit

    def contained(path):
        return os.path.join(real(path.parent), path.name).startswith(resolved_root)

    found = sorted(
        {
            path
            for pattern in patterns[agent]
            for path in root.glob(pattern)
            if path.is_file()
            and not path.is_symlink()
            and contained(path)
            # Dot-named Hermes profile folders are tombstones (profiles/.deleted).
            and not (agent == "hermes" and path.parent.name.startswith("."))
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
        if agent == "codex":
            states = [p for p in found if re.fullmatch(r"state_\d+\.sqlite", p.name)]
            latest = max(states, key=lambda p: int(p.stem.split("_")[-1]), default=None)
            found = [p for p in found if p.suffix != ".sqlite" or p == latest]
        for path in found:
            yield InputFile(
                path,
                "subagent_metadata"
                if path.name.endswith(".meta.json") and agent == "claude_code"
                else "session_title"
                if path.name == "custom-title.json" and agent == "claude_code"
                else "session_index"
                if path.name == "session_index.jsonl" and agent == "kimi"
                else "title_index"
                if path.name == "session_index.jsonl" and agent == "codex"
                else "state_index"
                if agent == "codex" and path.suffix == ".sqlite"
                else "import_ledger"
                if path.name == "external_agent_session_imports.json"
                else "subagent_transcript"
                if "subagents" in path.parts
                else "transcript",
            )
