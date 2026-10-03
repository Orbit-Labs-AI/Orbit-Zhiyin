"""Background AI work a scheduler can trigger; nothing here runs on its own.

``auto_facet_new(gw)`` is meant for the platform scheduler (e.g. after each ingest or on a
timer): when the user turned on ``settings.auto_facet_new`` it queues one ``facet.session``
job for recent finished sessions that have no facet yet. Jobs carry ``params.auto`` so they
do not raise an "AI job done" notification.
"""

from __future__ import annotations

from .errors import AIError
from .runner import now_ms
from .service import service

WINDOW_DAYS = 7
BATCH = 20


def new_session_uids(gw, limit: int = BATCH) -> list[str]:
    """Recent finished main sessions (≥2 human messages) without an ``ok`` ``ai_facet`` row
    (failed / skipped / stale facets are retried)."""
    since = now_ms() - WINDOW_DAYS * 86400 * 1000
    with gw.reads.read() as db:
        uids = [row[0] for row in db.execute(
            "SELECT s.session_uid FROM session s WHERE s.kind = 'main' AND s.status <> 'active' "
            "AND COALESCE(s.ended_at, s.started_at) >= ? AND (SELECT COUNT(*) FROM "
            "v_human_message h WHERE h.session_uid = s.session_uid) >= 2 "
            "ORDER BY s.started_at DESC LIMIT 500", (since,))]
    if not uids:
        return []
    marks = ",".join("?" * len(uids))
    with gw.appdb.read() as db:
        done = {row[0] for row in db.execute(
            f"SELECT session_uid FROM ai_facet WHERE session_uid IN ({marks}) AND status = 'ok'",
            uids)}
    return [uid for uid in uids if uid not in done][:limit]


def auto_facet_new(gw, limit: int = BATCH) -> dict:
    """Queue one facet job for new sessions; ``{status: submitted|idle|skipped, ...}``."""
    svc = service(gw)
    settings = svc.consent_store.settings()
    if not settings.get("auto_facet_new") or settings["mode"] == "stats":
        return {"status": "skipped", "reason": "disabled"}
    with gw.appdb.read() as db:
        busy = db.execute("SELECT job_id FROM ai_job WHERE task_id = 'facet.session' AND "
                          "status IN ('queued', 'running') LIMIT 1").fetchone()
    if busy is not None:
        return {"status": "skipped", "reason": "busy", "job_id": busy[0]}
    uids = new_session_uids(gw, limit)
    if not uids:
        return {"status": "idle"}
    try:
        submitted = svc.submit("facet.session", {"params": {"session_uids": uids, "auto": True}},
                               skip_preview=True)
    except AIError as error:
        return {"status": "skipped", "reason": error.code}
    return {"status": "submitted", "job_id": submitted["job_id"], "sessions": len(uids)}
