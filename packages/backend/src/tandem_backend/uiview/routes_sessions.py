"""``/v1/uiview/sessions*`` — A3 / Lite session list, detail, compare and default-B.

Mounted by P1's ``services/routes_uiview.py`` (``include_router(routes_sessions.router(gw))``
when this module exists). Reads tandem.db through ``gw.reads`` only; exclusions from app.db;
liveness from the last realtime snapshot (never forces a refresh). ``facts_provider`` may
return P1 ``uiview_facts`` rows keyed by session id; they are overlaid on the L1 rows.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from ..realtime.context_windows import load_overrides
from ..realtime.service import ACTIVE
from ..services.auth import ApiError
from ..services.routes_data import mark_empty
from ..sessionops import exclusion
from . import compare as cmp
from . import insight_session, sessions, trajectory

if TYPE_CHECKING:
    from ..services.gateway import Gateway

SEARCH_KINDS = ["session", "message", "command", "file"]
RANGES = {0, 7, 30, 90}
OUTCOMES = {"ok", "part", "fail", "live"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def router(gw: Gateway, facts_provider: Callable[[], dict | None] | None = None) -> APIRouter:
    api = APIRouter()
    cache: dict = {"key": None, "rows": None}
    lock = threading.Lock()

    def zone(tz: str | None):
        try:
            return sessions.zone(tz)
        except ValueError as error:
            raise ApiError(422, "invalid_request", str(error)) from None

    def live_uids() -> set[str]:
        rt = getattr(gw, "realtime", None)
        snap = rt.latest() if rt is not None else None
        return {s["session_uid"] for s in (snap or {}).get("sessions", [])
                if s.get("state") in ACTIVE}

    def excluded_uids() -> set[str]:
        return set(exclusion.excluded_uids(gw.appdb))

    def fact_rows(tz_name: str | None) -> list[dict]:
        tz = zone(tz_name)
        rev = getattr(getattr(gw, "revisions", None), "value", {}).get("data_rev")
        key = (rev, tz_name)
        with lock:
            if rev is not None and cache["key"] == key:
                base = cache["rows"]
            else:
                with gw.reads.read(empty=True) as db:
                    base = sessions.l1_facts(db, tz)
                cache.update(key=key, rows=base)
        live, excluded = live_uids(), excluded_uids()
        rows = [{**r, "live": r["id"] in live, "excluded": r["id"] in excluded,
                 "out": "live" if r["id"] in live else
                 (r["out"] if r["out"] != "live" else None),
                 "out_basis": "realtime" if r["id"] in live else r["out_basis"]} for r in base]
        return sessions.overlay(rows, facts_provider() if facts_provider else None)

    def search_uids(q: str) -> tuple[set[str] | None, bool]:
        from .. import features

        svc = features.current()
        if svc is None:
            return None, True
        try:
            result = svc.search(q, kinds=SEARCH_KINDS, limit=100)
        except Exception:  # noqa: BLE001 - search is best effort; substring match still runs.
            return None, True
        uids = {h.get("session_uid") or (h.get("ref") or {}).get("id")
                for h in result.get("results", [])}
        return {u for u in uids if u}, bool(result.get("partial"))

    def detail_for(session_uid: str, tz_name: str | None) -> dict:
        tz = zone(tz_name)
        overrides = load_overrides(gw.appdb)
        try:
            with gw.reads.read(empty=True) as db:  # nothing imported yet: 404, not 503
                detail = trajectory.build_detail(
                    db, session_uid, overrides=overrides,
                    live=session_uid in live_uids(),
                    excluded=session_uid in excluded_uids(), now_ms=_now_ms(), tz=tz,
                    facts=(facts_provider() or {}).get(session_uid) if facts_provider else None)
        except trajectory.NotFound:
            raise ApiError(404, "not_found", "会话不存在") from None
        return detail

    @api.get("/v1/uiview/sessions")
    def list_sessions(q: str = "", range: int = 0, agents: str = "",  # noqa: A002
                      project: str | None = None, topic: str | None = None,
                      outcome: str | None = None, fric: str | None = None,
                      hour: int | None = Query(None, ge=0, le=23),
                      offset: int = Query(0, ge=0), limit: int = Query(120, ge=1, le=200),
                      tz: str | None = None):
        if range not in RANGES:
            raise ApiError(422, "invalid_request", "range 只接受 0、7、30、90")
        if outcome is not None and outcome not in OUTCOMES:
            raise ApiError(422, "invalid_request", "outcome 只接受 ok、part、fail、live")
        q = q.strip()
        if len(q) > 200:
            raise ApiError(422, "invalid_request", "q 不超过 200 字")
        rows = fact_rows(tz)
        q_uids, partial = search_uids(q) if q else (None, False)
        with gw.reads.read(empty=True) as db:
            empty = gw.reads.is_empty(db)
            projects = dict(db.execute("SELECT project_id, name FROM project").fetchall())
            body = sessions.list_sessions(
                rows, now_ms=_now_ms(), tz=zone(tz), q=q or None, q_uids=q_uids,
                range_days=range, agents=[a for a in agents.split(",") if a] or None,
                project=project, topic=topic, outcome=outcome, fric=fric, hour=hour,
                offset=offset, limit=limit, projects=projects)
            marks = sessions.ticks(db, [r for r in rows if r["id"] in
                                        {x["id"] for x in body["rows"]}])
        for row in body["rows"]:
            row["ticks"] = marks.get(row["id"], {"t": [], "e": []})
        body["meta"]["search_partial"] = partial
        return mark_empty(body) if empty else body

    @api.get("/v1/uiview/sessions/compare")
    def compare(a: str, b: str, tz: str | None = None):
        if a == b:
            raise ApiError(422, "invalid_request", "A 与 B 不能是同一个会话")
        return cmp.compare(detail_for(a, tz), detail_for(b, tz))

    @api.get("/v1/uiview/sessions/{session_uid}/suggest_b")
    def suggest_b(session_uid: str, tz: str | None = None):
        rows = fact_rows(tz)
        if not any(r["id"] == session_uid for r in rows):
            raise ApiError(404, "not_found", "会话不存在")
        return {"a": session_uid, "b": cmp.suggest_b(rows, session_uid),
                "basis": "same_project_most_recent"}

    @api.get("/v1/uiview/sessions/{session_uid}")
    def detail(session_uid: str, tz: str | None = None, fric: str | None = None):
        body = detail_for(session_uid, tz)
        facts = body.pop("_facts")
        body["insight"] = insight_session.takeaway(facts, fric)
        return body

    return api
