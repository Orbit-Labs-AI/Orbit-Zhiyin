"""Bounded HTTPS reads and conditional cache; never executes source content."""

import base64
import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import digest

ALLOWED_HOSTS = {
    "api.github.com", "raw.githubusercontent.com", "registry.modelcontextprotocol.io",
    "api.mcp.github.com", "models.dev", "geminicli.com", "clawhub.ai", "openrouter.ai",
}


class FetchError(RuntimeError):
    def __init__(self, code: str, retry_after: int = 0):
        super().__init__(code)
        self.retry_after = retry_after


def validate_url(url: str):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username
            or parsed.password or parsed.port not in (443, None)):
        raise FetchError("source_url_not_allowed")


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        if urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            raise FetchError("cross_host_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    def __init__(self, cache_dir: str | Path, github_token: str | None = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")

    def get(self, url: str, immutable: bool = False) -> bytes:
        validate_url(url)
        path = self.cache_dir / (digest(url) + ".json")
        cached = None
        if path.is_file():
            try:
                cached = json.loads(path.read_bytes())
                body = base64.b64decode(cached["body"], validate=True)
                if cached["sha256"] != digest(body.hex()):
                    raise ValueError("cache_digest_mismatch")
                if immutable:
                    return body
            except (ValueError, TypeError, KeyError, OSError):
                cached = None
        headers = {"User-Agent": "Tandem-catalog/1", "Accept": "application/json"}
        if urlsplit(url).hostname == "api.github.com" and self.github_token:
            headers["Authorization"] = "Bearer " + self.github_token
        if cached:
            for field, header in (("etag", "If-None-Match"), ("modified", "If-Modified-Since")):
                if cached.get(field):
                    headers[header] = cached[field]
        try:
            with build_opener(SafeRedirect).open(Request(url, headers=headers), timeout=30) as response:
                body = response.read(25_000_001)
                if len(body) > 25_000_000:
                    raise FetchError("source_response_too_large")
                payload = {"etag": response.headers.get("ETag"), "modified": response.headers.get("Last-Modified"),
                           "sha256": digest(body.hex()), "body": base64.b64encode(body).decode()}
            temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_text(json.dumps(payload))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            return body
        except HTTPError as exc:
            if exc.code == 304 and cached:
                return base64.b64decode(cached["body"])
            delay = exc.headers.get("Retry-After", "0")
            raise FetchError(f"http_{exc.code}", int(delay) if delay.isdigit() else 0) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise FetchError("source_network_error") from exc

    def json(self, url: str, immutable: bool = False):
        try:
            return json.loads(self.get(url, immutable))
        except (ValueError, UnicodeError) as exc:
            raise FetchError("invalid_json_response") from exc
