"""Keep Tandem's own AI runs out of the data it analyses.

Every engine call runs in one dedicated cwd (``<home>/agent-cwd``, marked with
``.tandem-ai``), with sessions not persisted, a marker on the first prompt line and a
minimal environment. Ingestion (``tandem_data.pipeline.exclude_tandem_ai_sessions``) drops
any run that leaked; ``is_tandem_ai_session`` is the same test for in-process callers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Shared with ingestion, which drops these sessions from canonical data (tandem_data.pipeline).
from tandem_data.pipeline import TANDEM_AI_MARKER as MARKER
from tandem_data.pipeline import TANDEM_AI_MARKER_FILE as MARKER_FILE

ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR", "SHELL")
ENV_OPTIONAL = ("CLAUDE_CONFIG_DIR", "CODEX_HOME")
# Network plumbing the CLIs need behind a corporate proxy / custom CA (both CLIs honour these;
# Node reads NODE_EXTRA_CA_CERTS). Never credentials: no *_API_KEY, tokens, ANTHROPIC_* or OPENAI_*.
ENV_NETWORK = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY",
               "https_proxy", "http_proxy", "all_proxy", "no_proxy",
               "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS")


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
    result = {key: os.environ[key] for key in (*ENV_KEEP, *ENV_OPTIONAL, *ENV_NETWORK)
              if key in os.environ}
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
