"""Static context-window table per agent and model family (DT-14.1).

Every number below is 待验证: taken from public model cards and agent defaults, not measured
from local logs. ``agent=None`` rows match any agent. Users can override a window per model
prefix through app.db ``platform_kv['realtime.context_windows']`` ({prefix: window}).
"""

from __future__ import annotations

import json
import sqlite3

# (agent, model_prefix, window_tokens, auto_compact_ratio) — all 待验证.
WINDOWS: tuple[tuple[str | None, str, int, float | None], ...] = (
    ("claude_code", "claude-", 200_000, 0.92),  # Claude Code auto-compact near 92% 待验证
    (None, "claude-", 200_000, None),  # Claude 3.x / 4.x families 待验证
    ("codex", "gpt-5", 272_000, 0.9),  # Codex model_context_window default 待验证
    (None, "gpt-5", 400_000, None),  # 待验证
    (None, "gpt-4.1", 1_047_576, None),  # 待验证
    (None, "o3", 200_000, None),  # 待验证
    (None, "o4-mini", 200_000, None),  # 待验证
)
ONE_M_SUFFIX = "[1m]"  # Claude 1M-context variants, e.g. claude-sonnet-4-5[1m] 待验证
ONE_M_WINDOW = 1_000_000
KV_KEY = "realtime.context_windows"


def normalize(model: str | None) -> str:
    text = (model or "").strip().lower()
    return text.rpartition("/")[2] if "/" in text else text


def lookup(agent: str | None, model: str | None, overrides: dict | None = None) -> dict | None:
    """Longest-prefix match on the normalized model id; None when unknown (never guessed)."""
    name = normalize(model)
    if not name:
        return None
    best: tuple[int, int, float | None] | None = None
    for prefix, window in (overrides or {}).items():
        prefix = normalize(prefix)
        if prefix and name.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), int(window), None)
    if best is not None:
        return {"window_tokens": best[1], "auto_compact_ratio": None, "basis": "override"}
    for row_agent, prefix, window, ratio in WINDOWS:
        if row_agent not in (None, agent) or not name.startswith(prefix):
            continue
        rank = len(prefix) + (1 if row_agent else 0)  # agent-specific wins a tie
        if best is None or rank > best[0]:
            best = (rank, window, ratio)
    if best is None:
        return None
    window = ONE_M_WINDOW if name.endswith(ONE_M_SUFFIX) else best[1]
    return {"window_tokens": window, "auto_compact_ratio": best[2], "basis": "table"}


def load_overrides(appdb) -> dict:
    """Read the optional override dict; a missing table, key or bad JSON yields {}."""
    if appdb is None:
        return {}
    try:
        with appdb.read() as db:
            row = db.execute("SELECT value FROM platform_kv WHERE key = ?", (KV_KEY,)).fetchone()
        value = json.loads(row[0]) if row else {}
    except (sqlite3.Error, ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(k): int(v) for k, v in value.items() if isinstance(v, int | float) and v > 0}
