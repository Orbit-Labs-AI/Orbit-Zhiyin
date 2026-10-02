"""App page hosting: ``GET /app`` and ``GET /lite`` serve the single-file UI, ``/`` redirects.

The native host passes the built HTML with ``--assets <file>`` (or ``TANDEM_ASSETS``). Pages
are fetched by the WebView before it has any token, so ``PAGE_PATHS`` are exempt from the
Bearer check in :class:`~.auth.GuardMiddleware`; Host / Origin loopback checks still apply.
The page CSP allows the inline script and style of the single-file build and nothing remote:
external font ``<link>`` tags are stripped so the App works offline.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .auth import error_body

ASSETS_ENV = "TANDEM_ASSETS"
PAGE_PATHS = frozenset({"/", "/app", "/lite"})
PAGE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; "
            "font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
_REMOTE_LINK = re.compile(r"""[ \t]*<link\b[^>]*\bhref\s*=\s*["']?(?:https?:)?//[^>]*>[ \t]*\r?\n?""",
                          re.IGNORECASE)


def assets_path(explicit: Path | str | None = None) -> Path | None:
    value = explicit or os.environ.get(ASSETS_ENV)
    return Path(value).expanduser() if value else None


def offline_html(text: str) -> str:
    """Drop ``<link>`` tags that point off-device (fonts, preconnect)."""
    return _REMOTE_LINK.sub("", text)


class _Cache:
    def __init__(self):
        self.key: tuple[str, float, int] | None = None
        self.body = ""

    def load(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path), stat.st_mtime, stat.st_size)
        if key != self.key:
            self.body, self.key = offline_html(path.read_text(encoding="utf-8")), key
        return self.body


def router(assets: Path | str | None = None) -> APIRouter:
    api = APIRouter(include_in_schema=False)
    cache = _Cache()

    def page(name: str):
        path = assets_path(assets)
        if path is None or not path.is_file():
            detail = (f"UI assets not found at {path}" if path else
                      f"UI assets are not configured: start the gateway with --assets <file> "
                      f"or set {ASSETS_ENV}")
            return Response(error_body("assets_missing", detail), status_code=404,
                            media_type="application/json")
        print(f"tandem-gateway: page {name} served", file=sys.stderr, flush=True)
        return HTMLResponse(cache.load(path), headers={"content-security-policy": PAGE_CSP})

    @api.get("/")
    def root():
        return RedirectResponse("/app", status_code=307)

    @api.get("/app")
    def app_page():
        return page("/app")

    @api.get("/lite")
    def lite_page():
        return page("/lite")

    return api
