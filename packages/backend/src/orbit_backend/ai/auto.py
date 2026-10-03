"""Background AI work triggered by the gateway after imports.

``auto_facet_new(gw)`` is called by the gateway after every import job that finished with
new data (``JobService.on_import_done`` → ``Gateway._after_import``): when the user turned
on ``settings.auto_facet_new`` it queues one ``facet.session`` job for recent finished
sessions that have no facet yet. Jobs carry ``params.auto`` so they
do not raise an "AI job done" notification.

``auto_overview(gw)`` is the same hook for ``settings.auto_overview`` (default off; the user
turns it on in 设置 › 分析 after reading that the redacted summary goes to the chosen local
Agent): one ``narrate.overview`` job for the default overview view (近 30 天, no filter), so
the A1 card reads back a model narrative for the new data. ``AIService.submit`` applies the
usual gates (AI mode, engine, consent, daily budget); at most ``AUTO_OVERVIEW_PER_DAY`` automatic
overviews run per local day, and none while another overview job is queued or running.
"""

from __future__ import annotations

from datetime import datetime

from .consent import Consent
from .errors import AIError
from .runner import now_ms
from .service import service

WINDOW_DAYS = 7
BATCH = 20
AUTO_OVERVIEW_PER_DAY = 3
OVERVIEW_SCOPE = {"days": 30}  # the A1 default view (近 30 天, no filter); null keys are not sent


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
    # Read the setting before building the AI service: with the switch off (the default) an
    # import must not spin up engines/runner just to find out there is nothing to do.
    existing = getattr(gw, "_ai", None)
    settings = (existing.consent_store if existing is not None else Consent(gw.appdb)).settings()
    if not settings.get("auto_facet_new") or settings["mode"] == "stats":
        return {"status": "skipped", "reason": "disabled"}
    svc = service(gw)
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


def _settings(gw) -> dict:
    existing = getattr(gw, "_ai", None)
    return (existing.consent_store if existing is not None else Consent(gw.appdb)).settings()


def _local_midnight_ms() -> int:
    return int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def auto_overview(gw) -> dict:
    """Queue one ``narrate.overview`` after an import; ``{status: submitted|skipped, ...}``."""
    settings = _settings(gw)  # switch off (default): no engines spin up
    if not settings.get("auto_overview") or settings["mode"] == "stats":
        return {"status": "skipped", "reason": "disabled"}
    with gw.appdb.read() as db:
        busy = db.execute("SELECT job_id FROM ai_job WHERE task_id = 'narrate.overview' AND "
                          "status IN ('queued', 'running') LIMIT 1").fetchone()
        today = db.execute(
            "SELECT COUNT(*) FROM ai_job WHERE task_id = 'narrate.overview' AND created_at >= ? "
            "AND json_extract(request, '$.params.auto') = 1", (_local_midnight_ms(),)).fetchone()[0]
    if busy is not None:
        return {"status": "skipped", "reason": "busy", "job_id": busy[0]}
    if today >= AUTO_OVERVIEW_PER_DAY:
        return {"status": "skipped", "reason": "daily_limit"}
    svc = service(gw)
    try:
        submitted = svc.submit("narrate.overview", {"scope": dict(OVERVIEW_SCOPE),
                                                    "params": {"auto": True}}, skip_preview=True)
    except AIError as error:  # budget_exhausted / consent_required / engine_unavailable …
        return {"status": "skipped", "reason": error.code}
    return {"status": "submitted", "job_id": submitted["job_id"]}
