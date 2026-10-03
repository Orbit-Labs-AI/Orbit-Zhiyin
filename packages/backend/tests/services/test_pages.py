"""App page hosting: /app and /lite are token-free, the API is not, assets come from --assets."""

from __future__ import annotations

import pytest
from conftest import BASE, PORT
from fastapi.testclient import TestClient

from orbit_backend.services import pages

HTML = """<!doctype html>
<html><head>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X&display=swap">
<link rel="icon" href="data:image/svg+xml,x">
<style>body{}</style></head>
<body><script>window.ok = 1;</script></body></html>
"""


@pytest.fixture
def assets(tmp_path, monkeypatch):
    path = tmp_path / "orbit.html"
    path.write_text(HTML, encoding="utf-8")
    monkeypatch.setenv(pages.ASSETS_ENV, str(path))
    return path


def anonymous(client) -> TestClient:
    return TestClient(client.app, base_url=BASE)


def test_pages_served_without_token(client_factory, assets):
    client, _ = client_factory()
    web = anonymous(client)
    for path in ("/app", "/lite"):
        page = web.get(path)
        assert page.status_code == 200, page.text
        assert page.headers["content-type"].startswith("text/html")
        assert "window.ok = 1" in page.text
        assert "fonts.googleapis" not in page.text  # Offline: remote font links stripped.
        assert 'rel="icon"' in page.text
    root = web.get("/", follow_redirects=False)
    assert root.status_code in (302, 307) and root.headers["location"] == "/app"


def test_api_still_needs_token(client_factory, assets):
    client, _ = client_factory()
    web = anonymous(client)
    assert web.get("/v1/status").status_code == 401
    assert web.post("/app").status_code == 401  # Only GET/HEAD pages are public.
    assert client.get("/v1/status").status_code == 200
    # Host / Origin checks still guard the pages.
    assert web.get("/app", headers={"Host": "evil.example:%d" % PORT}).status_code == 403
    assert web.get("/app", headers={"Origin": "https://evil.example"}).status_code == 403


def test_page_csp(client_factory, assets):
    client, _ = client_factory()
    page = anonymous(client).get("/app")
    csp = page.headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "connect-src 'self'" in csp
    assert "img-src 'self' data: blob:" in csp
    assert "font-src 'self' data:" in csp
    assert page.headers["x-content-type-options"] == "nosniff"
    api = client.get("/v1/status").headers["content-security-policy"]
    assert "unsafe-inline" not in api  # The API keeps the strict default.


def test_missing_assets_404(client_factory, monkeypatch, tmp_path):
    monkeypatch.delenv(pages.ASSETS_ENV, raising=False)
    client, _ = client_factory()
    missing = anonymous(client).get("/app")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "assets_missing"
    assert "--assets" in missing.json()["error"]["message"]
    monkeypatch.setenv(pages.ASSETS_ENV, str(tmp_path / "nope.html"))
    gone = anonymous(client).get("/lite")
    assert gone.status_code == 404 and "not found" in gone.json()["error"]["message"]
