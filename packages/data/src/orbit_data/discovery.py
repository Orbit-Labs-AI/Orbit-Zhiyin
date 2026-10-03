"""Path allowlists. Discovery lists candidates; scan requires an explicit agent/root."""

import os
import re
import sqlite3
from contextlib import closing
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


def _codex_index_paths(index: Path, root: Path):
    """Read only rollout pointers; an unavailable index must not block glob discovery.

    The regular capture path still reads this index and records its failure. Never
    follow pointers outside the explicitly enabled home or through symlink files.
    """
    try:
        with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute("SELECT rollout_path FROM threads").fetchall()
    except sqlite3.Error:
        return
    for (value,) in rows:
        if not isinstance(value, str) or not value:
            continue
        path = root / value
        if not re.fullmatch(r"rollout-.*\.jsonl(?:\.zst)?", path.name):
            continue
        if path.is_symlink():
            continue
        path = path.resolve()
        if path.is_relative_to(root) and path.is_file():
            yield path


def inputs(agent: str, root: Path):
    root = root.resolve()
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
            if latest is not None:
                found = sorted(set(found).union(_codex_index_paths(latest, root)))
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
