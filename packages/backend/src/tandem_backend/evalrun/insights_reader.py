"""Read-only reader for Claude Code ``/insights`` data (DT-18).

Reads ``<home>/.claude/usage-data/session-meta/*.json`` and, when present,
``<home>/.claude/usage-data/facets/*.json``. Nothing else under the home is read and nothing is
written. Unknown keys are ignored; malformed files are skipped and counted in ``warnings``.
"""

from __future__ import annotations

import json
from pathlib import Path

# normalized field -> accepted spellings, first match wins (every field is optional)
FIELDS = {
    "session_id": ("session_id", "sessionId", "id"),
    "start_time": ("start_time", "startTime", "started_at"),
    "duration_minutes": ("duration_minutes", "durationMinutes"),
    "user_message_count": ("user_message_count", "userMessageCount"),
    "assistant_message_count": ("assistant_message_count", "assistantMessageCount"),
    "tool_counts": ("tool_counts", "toolCounts"),
    "input_tokens": ("input_tokens", "inputTokens"),
    "output_tokens": ("output_tokens", "outputTokens"),
    "project_path": ("project_path", "projectPath", "cwd"),
}


def usage_dir(home: Path) -> Path:
    return Path(home) / ".claude" / "usage-data"


def _load_dir(path: Path, warnings: list[str]) -> list[dict]:
    out = []
    for file in sorted(path.glob("*.json")) if path.is_dir() else []:
        try:
            data = json.loads(file.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            warnings.append(f"{file.name}: {type(error).__name__}")
            continue
        if not isinstance(data, dict):
            warnings.append(f"{file.name}: not an object")
            continue
        out.append({**data, "_file": file.stem})
    return out


def _normalize(raw: dict) -> dict:
    row = {key: next((raw[n] for n in names if raw.get(n) is not None), None)
           for key, names in FIELDS.items()}
    row["session_id"] = row["session_id"] or raw["_file"]
    if not isinstance(row["tool_counts"], dict):
        row["tool_counts"] = None
    return row


def read_session_meta(home: Path, warnings: list[str] | None = None) -> list[dict]:
    """Normalized session-meta rows; a facet (if any) is attached under ``facet``."""
    warnings = [] if warnings is None else warnings
    base = usage_dir(home)
    facets = {}
    for raw in _load_dir(base / "facets", warnings):
        sid = next((raw[n] for n in FIELDS["session_id"] if raw.get(n)), raw["_file"])
        facets[sid] = {k: v for k, v in raw.items() if k != "_file"}
    rows = [_normalize(raw) for raw in _load_dir(base / "session-meta", warnings)]
    for row in rows:
        row["facet"] = facets.get(row["session_id"])
    return rows
