"""Persisted session exclusions (AN-16.1) in app.db ``session_exclusion``.

Analytics reads them through a module-level provider (``set_provider``) because its scope
dependency has no gateway; ``merged`` never fails a request over a missing provider.
"""

from __future__ import annotations

import time
from collections.abc import Callable

REASONS = ("test", "private", "duplicate", "other")
_provider: Callable[[], list[str]] | None = None


def excluded_uids(appdb) -> list[str]:
    with appdb.read() as db:
        return [r[0] for r in db.execute(
            "SELECT session_uid FROM session_exclusion ORDER BY session_uid")]


def add(appdb, session_uid: str, reason: str | None = None, note: str | None = None,
        source: str = "user", now_ms: int | None = None) -> dict:
    """Idempotent: a repeated call keeps the first ``excluded_at`` and updates reason/note."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    with appdb.write() as db:
        db.execute("INSERT INTO session_exclusion(session_uid, reason, note, excluded_at, source) "
                   "VALUES (?, ?, ?, ?, ?) ON CONFLICT(session_uid) DO UPDATE SET "
                   "reason = excluded.reason, note = excluded.note",
                   (session_uid, reason, note, now_ms, source))
        at = db.execute("SELECT excluded_at FROM session_exclusion WHERE session_uid = ?",
                        (session_uid,)).fetchone()[0]
    return {"session_uid": session_uid, "excluded": True, "excluded_at": at}


def remove(appdb, session_uid: str) -> bool:
    with appdb.write() as db:
        return db.execute("DELETE FROM session_exclusion WHERE session_uid = ?",
                          (session_uid,)).rowcount > 0


def list(appdb) -> list[dict]:  # noqa: A001 - module API name from the spec.
    """Newest exclusion first."""
    with appdb.read() as db:
        return [dict(r) for r in db.execute(
            "SELECT session_uid, reason, note, excluded_at, source FROM session_exclusion "
            "ORDER BY excluded_at DESC, session_uid")]


def set_provider(fn: Callable[[], list[str]] | None) -> None:
    global _provider
    _provider = fn


def merged(explicit: list[str] | None) -> list[str]:
    """``explicit`` (order kept) plus persisted uids not already in it."""
    values = [*(explicit or [])]
    try:
        persisted = _provider() if _provider is not None else []
    except Exception:  # noqa: BLE001 - a closed/missing app.db must not break analytics.
        persisted = []
    seen = set(values)
    return values + [v for v in persisted if v not in seen]
