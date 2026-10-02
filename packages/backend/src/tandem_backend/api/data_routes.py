"""HTTP surface for local data services (DT-23/24/22/15/10).

Integration adds one line to ``create_app``: ``data_routes.register(app, canonical_home)``.
All routes are read-only except the confirmed purge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from tandem_data.privacy_rules import MAX_PREVIEW_CHARS


class PurgeRequest(BaseModel):
    confirm: str = Field(max_length=200)


class PreviewRequest(BaseModel):
    text: str = Field(max_length=MAX_PREVIEW_CHARS)


def register(app: FastAPI, home: str | Path) -> FastAPI:
    home = Path(home).expanduser()

    @app.get("/v1/search")
    def search(
        q: Annotated[str, Query(min_length=1, max_length=200)],
        source_id: Annotated[list[str] | None, Query()] = None,
        from_ts: int | None = None,
        until_ts: int | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        from tandem_data.search import SearchScope
        from tandem_data.search import search as run_search

        scope = SearchScope(
            source_ids=tuple(source_id) if source_id else None, from_ts=from_ts, until_ts=until_ts
        )
        try:
            return run_search(home, q, scope, limit=limit, offset=offset)
        except FileNotFoundError as error:
            raise HTTPException(404, "本地数据库不存在，请先导入") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/v1/sessions/{session_id}/resume")
    def resume(session_id: str):
        from tandem_data.resume import session_resume

        try:
            return session_resume(home, session_id)
        except FileNotFoundError as error:
            raise HTTPException(404, "本地数据库不存在，请先导入") from error
        except KeyError as error:
            raise HTTPException(404, "会话不存在") from error

    @app.get("/v1/sources/capabilities")
    def source_capabilities(refresh: bool = False):
        from tandem_data.capabilities import capabilities

        return capabilities(home, refresh=refresh)

    @app.get("/v1/storage")
    def storage():
        from tandem_data.maintenance import storage_usage

        return storage_usage(home)

    @app.post("/v1/storage/purge")
    def purge(request: PurgeRequest):
        from tandem_data.maintenance import PurgeRefused, purge_all

        try:
            return purge_all(home, request.confirm)
        except PurgeRefused as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/v1/privacy/rules")
    def privacy_rules():
        from tandem_data.privacy_rules import rules

        return rules()

    @app.post("/v1/privacy/preview")
    def privacy_preview(request: PreviewRequest):
        from tandem_data.privacy_rules import preview

        return preview(request.text)

    return app
