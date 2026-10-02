"""Keep Tandem's own AI runs out of the data it analyses.

Every engine call runs in one dedicated cwd (``<home>/agent-cwd``, marked with
``.tandem-ai``), with sessions not persisted, a marker on the first prompt line and a
minimal environment. ``is_tandem_ai_session`` lets connectors drop any run that leaked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

MARKER = "[tandem-analysis v1"
MARKER_FILE = ".tandem-ai"
ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR", "SHELL")
ENV_OPTIONAL = ("CLAUDE_CONFIG_DIR", "CODEX_HOME")


def cwd(home: Path) -> Path:
    path = Path(home) / "agent-cwd"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    marker = path / MARKER_FILE
    if not marker.exists():
        marker.write_text(json.dumps({"origin": "tandem", "purpose": "ai-runs"}) + "\n",
                          encoding="utf-8")
    return path


def marker_line(task_id: str, job_id: str) -> str:
    return f"{MARKER} task={task_id} job={job_id}]"


def env() -> dict[str, str]:
    """Whitelisted environment: never forwards CLAUDE_CODE_*, ANTHROPIC_* or OPENAI_*."""
    result = {key: os.environ[key] for key in (*ENV_KEEP, *ENV_OPTIONAL) if key in os.environ}
    result["NO_COLOR"] = "1"
    return result


def is_tandem_ai_session(session_cwd: str | Path | None, first_text: str | None,
                         home: Path | None = None) -> bool:
    """True for sessions started by Tandem itself (by cwd, marker file or first line)."""
    if first_text and first_text.lstrip().startswith(MARKER):
        return True
    if not session_cwd:
        return False
    path = Path(session_cwd)
    if home is not None:
        root = (Path(home) / "agent-cwd").resolve()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved == root or root in resolved.parents:
            return True
    return path.name == "agent-cwd" and (path / MARKER_FILE).is_file()
