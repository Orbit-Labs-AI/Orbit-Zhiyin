"""DT-18 read-only reader for Claude Code ``/insights`` artefacts at an explicit path.

Reads ``<path>/session-meta/*.json`` and ``<path>/facets/*.json`` (``path`` is the
``usage-data`` directory, or a directory containing one). There is no default location:
the caller must pass the directory the user enabled. Files are never modified; malformed,
oversized or symlinked files are reported in ``errors`` and skipped. Values pass through
``privacy.sanitize`` because facets can quote user text.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from tandem_data.privacy import sanitize
from tandem_data.store import readonly_connection

KINDS = ("session-meta", "facets")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 20_000


def read_usage_data(path: str | Path) -> dict:
    if path is None or str(path) == "":
        raise ValueError("an explicit usage-data path is required")
    root = Path(path).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory")
    if not any((root / kind).is_dir() for kind in KINDS) and (root / "usage-data").is_dir():
        root = root / "usage-data"
    sessions: dict[str, dict] = {}
    errors: list[dict] = []
    counts = dict.fromkeys(KINDS, 0)
    seen = 0
    for kind in KINDS:
        folder = root / kind
        if not folder.is_dir() or folder.is_symlink():
            continue
        for entry in sorted(os.scandir(folder), key=lambda item: item.name):
            if not entry.name.endswith(".json"):
                continue
            seen += 1
            if seen > MAX_FILES:
                errors.append({"file": f"{kind}/{entry.name}", "error": "file limit reached"})
                break
            relative = f"{kind}/{entry.name}"
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                errors.append({"file": relative, "error": "not a regular file"})
                continue
            if info.st_size > MAX_FILE_BYTES:
                errors.append({"file": relative, "error": "file too large"})
                continue
            try:
                data = json.loads(Path(entry.path).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as error:
                errors.append({"file": relative, "error": f"unreadable: {type(error).__name__}"})
                continue
            if not isinstance(data, dict):
                errors.append({"file": relative, "error": "top level is not an object"})
                continue
            session_id = data.get("session_id") or data.get("sessionId") or Path(entry.name).stem
            if not isinstance(session_id, str):
                session_id = Path(entry.name).stem
            item = sessions.setdefault(
                session_id, {"session_id": session_id, "meta": None, "facets": None}
            )
            item["meta" if kind == "session-meta" else "facets"] = sanitize(data)
            counts[kind] += 1
    return {
        "path": str(root),
        "counts": {**counts, "sessions": len(sessions), "errors": len(errors)},
        "sessions": [sessions[key] for key in sorted(sessions)],
        "errors": errors,
    }


def numeric_summary(meta: dict | None) -> dict:
    """Top-level numbers plus numeric maps (e.g. tool_counts) for a side-by-side check."""
    if not isinstance(meta, dict):
        return {}
    summary = {}
    for key, value in meta.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            summary[key] = value
        elif (
            isinstance(value, dict)
            and value
            and all(
                isinstance(item, int | float) and not isinstance(item, bool)
                for item in value.values()
            )
        ):
            summary[key] = dict(value)
    return summary


def match_sessions(home: str | Path, report: dict) -> list[dict]:
    """Attach the Tandem Claude Code session (same native id) and its observed counts."""
    db_path = Path(home).expanduser() / "tandem.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"No Tandem database at {db_path}")
    rows = []
    with readonly_connection(db_path) as db:
        for item in report["sessions"]:
            found = db.execute(
                "SELECT s.session_uid FROM session s JOIN source src USING(source_id) "
                "WHERE src.agent='claude_code' AND s.native_id=? AND s.kind='main' "
                "ORDER BY s.session_uid LIMIT 1",
                (item["session_id"],),
            ).fetchone()
            tandem = None
            if found:
                uid = found["session_uid"]
                tools = dict(
                    db.execute(
                        "SELECT name, COUNT(*) FROM tool_call WHERE session_uid=? GROUP BY name",
                        (uid,),
                    ).fetchall()
                )
                human = db.execute(
                    "SELECT COUNT(*) FROM v_human_message WHERE session_uid=?", (uid,)
                ).fetchone()[0]
                tandem = {
                    "session_uid": uid,
                    "tool_calls": sum(tools.values()),
                    "tool_counts": tools,
                    "human_messages": human,
                }
            rows.append(
                {
                    "session_id": item["session_id"],
                    "insights": numeric_summary(item["meta"]),
                    "outcome": (item["facets"] or {}).get("outcome"),
                    "tandem": tandem,
                }
            )
    return rows
