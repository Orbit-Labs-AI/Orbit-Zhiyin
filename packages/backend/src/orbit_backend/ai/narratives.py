"""Read side for consumers of AI narratives (no engines, safe at gateway start-up).

``latest_overview`` returns the newest *model-written* ``narrate.overview`` result for an
exact scope and the data it was written from, or ``None``. A narrative written for another
window/project, before the latest import (``data_rev`` changed), or a template fallback is
never returned: the caller keeps its own L0 text instead of showing a stale or mismatched one.
The data revision is recorded in ``ai_job.request._data`` by ``AIService.submit``.
"""

from __future__ import annotations

import json

TASK_ID = "narrate.overview"
SCAN = 20  # newest ok jobs examined; older overviews are superseded anyway.


def _norm_scope(scope: dict | None) -> dict:
    return {k: v for k, v in (scope or {}).items() if v not in (None, "", [])}


def latest_overview(appdb, scope: dict | None, data_rev) -> dict | None:
    if appdb is None or data_rev is None:
        return None
    want = _norm_scope(scope)
    with appdb.read() as db:
        rows = db.execute("SELECT job_id, engine, request, result, finished_at FROM ai_job "
                          "WHERE task_id = ? AND status = 'ok' AND result IS NOT NULL "
                          "ORDER BY finished_at DESC LIMIT ?", (TASK_ID, SCAN)).fetchall()
    for job_id, engine, request, result, finished_at in rows:
        req = json.loads(request or "{}")
        data = req.get("_data") or {}
        if _norm_scope(req.get("scope")) != want or data.get("data_rev") != data_rev:
            continue
        out = json.loads(result)
        if out.get("source") in (None, "template"):
            continue
        return {"job_id": job_id, "engine": engine, "finished_at": finished_at, "result": out}
    return None
