"""AI facet outcomes for the signal layer (``build_signal_layer(facets=...)``).

The ai runtime owns ``app.db``'s ``ai_facet`` table; this reader only takes the newest ``ok``
row per session and its ``outcome`` (``fully_achieved`` … ``unclear``), which
``outcome.synthesize_outcome`` maps through ``FACETS``. A missing app.db or table, an
unreadable row or a non-string outcome yields no facet: the outcome then falls back to the
structural rules exactly as before.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

CHUNK = 500


def root_session_uids(context) -> list[str]:
    """The sessions ``build_views`` makes a view for (non-agent roots)."""
    return [s["session_uid"] for s in context.sessions
            if s.get("kind") not in ("subagent", "workflow_agent")]


def facet_outcomes(app_db: str | Path | None, session_uids: Iterable[str]) -> dict[str, str]:
    """``{session_uid: outcome}`` from the newest ``ok`` ``ai_facet`` row of each session."""
    path = Path(app_db) if app_db else None
    ids = list(dict.fromkeys(session_uids))
    if path is None or not ids or not path.is_file():
        return {}
    newest: dict[str, tuple[int, str]] = {}
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        for start in range(0, len(ids), CHUNK):
            chunk = ids[start:start + CHUNK]
            marks = ",".join("?" * len(chunk))
            rows = db.execute(f"SELECT session_uid, json, created_at FROM ai_facet "
                              f"WHERE status = 'ok' AND session_uid IN ({marks})", chunk)
            for uid, body, created in rows:
                try:
                    outcome = json.loads(body or "{}").get("outcome")
                except (ValueError, AttributeError):
                    continue
                if isinstance(outcome, str) and (uid not in newest or created > newest[uid][0]):
                    newest[uid] = (created, outcome)
    except sqlite3.Error:  # ai_facet not created yet
        return {}
    finally:
        db.close()
    return {uid: outcome for uid, (_, outcome) in newest.items()}
