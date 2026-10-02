"""Session operations: exclusion (AN-16.1), resume commands (DT-24), raw-log locate
(AN-16.1) and the tool-call drilldown (AN-01.2). tandem.db via ``gw.reads``; app.db via
``gw.appdb``. Exclusion changes bump the ``exclusions`` revision and publish a ``data``
frame so open lists and analytics views can refresh.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import platform
from ..sessionops import exclusion, resume
from .auth import ApiError

if TYPE_CHECKING:
    from .gateway import Gateway

CHUNK = 500


class ExcludeBody(BaseModel):
    reason: Literal["test", "private", "duplicate", "other"] | None = None
    note: str | None = Field(None, max_length=200)


SESSION_SQL = """
SELECT s.session_uid, s.native_id, s.cwd, s.status, s.ended_at, s.title, s.project_id,
       s.started_at, src.agent, p.name AS project
FROM session s LEFT JOIN source src ON src.source_id = s.source_id
LEFT JOIN project p ON p.project_id = s.project_id
"""


def router(gw: Gateway) -> APIRouter:
    api = APIRouter()
    exclusion.set_provider(lambda: exclusion.excluded_uids(gw.appdb))
    platform.register_etag("/v1/sessions/excluded", lambda: _excluded_rev(gw), exact=True)

    def session_row(db, session_uid: str) -> dict:
        row = db.execute(SESSION_SQL + " WHERE s.session_uid = ?", (session_uid,)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", "会话不存在")
        return dict(row)

    def changed(session_uid: str, excluded: bool) -> None:
        platform.bump_rev("exclusions")
        gw.bus.publish("data", "exclusions.changed",
                       {"session_uid": session_uid, "excluded": excluded})

    @api.post("/v1/sessions/{session_uid}/exclude")
    def exclude(session_uid: str, body: ExcludeBody | None = None):
        body = body or ExcludeBody()
        with gw.reads.read() as db:
            session_row(db, session_uid)
        result = exclusion.add(gw.appdb, session_uid, body.reason, body.note)
        changed(session_uid, True)
        return result

    @api.delete("/v1/sessions/{session_uid}/exclude")
    def include(session_uid: str):
        if not exclusion.remove(gw.appdb, session_uid):
            raise ApiError(404, "not_found", "该会话未被排除")
        changed(session_uid, False)
        return {"session_uid": session_uid, "excluded": False}

    @api.get("/v1/sessions/excluded")
    def excluded():
        items = exclusion.list(gw.appdb)
        sessions: dict[str, dict] = {}
        try:
            with gw.reads.read() as db:
                uids = [i["session_uid"] for i in items]
                for start in range(0, len(uids), CHUNK):
                    part = uids[start:start + CHUNK]
                    sql = SESSION_SQL + f" WHERE s.session_uid IN ({','.join('?' * len(part))})"
                    sessions.update((r["session_uid"], dict(r)) for r in db.execute(sql, part))
        except ApiError:
            pass  # No projection yet: list exclusions without titles.
        fields = ("title", "agent", "project_id", "project", "started_at")
        return {"count": len(items), "items": [
            {"session_uid": i["session_uid"],
             **{k: sessions.get(i["session_uid"], {}).get(k) for k in fields},
             **{k: i[k] for k in ("reason", "note", "excluded_at", "source")}} for i in items]}

    @api.get("/v1/sessions/{session_uid}/resume")
    def resume_command(session_uid: str):
        with gw.reads.read() as db:
            row = session_row(db, session_uid)
            row["last_event_ts"] = db.execute("SELECT max(ts) FROM event WHERE session_uid = ?",
                                              (session_uid,)).fetchone()[0]
        return resume.build(row, int(time.time() * 1000))

    return api


def _excluded_rev(gw) -> str:
    data_rev = gw.revisions.value.get("data_rev")
    return f"{data_rev}.{platform.rev_token('exclusions')}"
