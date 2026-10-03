"""Split an allowlisted source into head / window / rest import batches by file mtime.

head: the newest ``head_sessions`` session files, extended to everything newer than
``head_days``; auxiliary indexes ride with head. window: the rest of ``window_days``.
rest: everything older, in chunks so the worker can pause between them. ``max_age_days``
(settings ``recent_days``) drops session files older than that before batching. Each batch is
passed to ``ImportService`` through ``ImportRequest.files`` and publishes atomically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from orbit_data.discovery import inputs

SESSION_ROLES = frozenset({"transcript", "subagent_transcript", "legacy_transcript"})
PHASES = ("head", "window", "rest")


@dataclass(frozen=True)
class Batch:
    phase: str
    files: tuple[Path, ...]


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0  # Unreadable stats sort last; the import reports the actual error.


def plan_batches(agent: str, root: Path, *, now: float | None = None, head_sessions: int = 50,
                 head_days: float = 7, window_days: float = 30,
                 rest_chunk: int = 200, max_age_days: float | None = None) -> list[Batch]:
    if head_sessions < 1 or rest_chunk < 1:
        raise ValueError("head_sessions and rest_chunk must be positive")
    now = time.time() if now is None else now
    root = root.expanduser().resolve(strict=True)
    sessions, auxiliary = [], []
    for item in inputs(agent, root):
        (sessions if item.role in SESSION_ROLES else auxiliary).append(item.path)
    dated = sorted(((_mtime(p), p) for p in sessions), key=lambda pair: (-pair[0], str(pair[1])))
    if max_age_days is not None:
        oldest = now - max_age_days * 86_400
        dated = [(mtime, path) for mtime, path in dated if mtime >= oldest]
    head_cut, window_cut = now - head_days * 86_400, now - window_days * 86_400
    head, window, rest = [], [], []
    for position, (mtime, path) in enumerate(dated):
        if position < head_sessions or mtime >= head_cut:
            head.append(path)
        elif mtime >= window_cut:
            window.append(path)
        else:
            rest.append(path)
    batches = []
    if head or auxiliary:
        batches.append(Batch("head", tuple(sorted(auxiliary)) + tuple(head)))
    if window:
        batches.append(Batch("window", tuple(window)))
    for start in range(0, len(rest), rest_chunk):
        batches.append(Batch("rest", tuple(rest[start:start + rest_chunk])))
    return batches
