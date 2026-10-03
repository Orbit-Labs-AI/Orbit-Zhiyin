"""Bounded HTTPS reads with a SQLite conditional cache; never executes source content."""

import hashlib
import json
import os
import sqlite3
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_HOSTS = {
    "api.github.com", "raw.githubusercontent.com", "registry.modelcontextprotocol.io",
    "api.mcp.github.com", "models.dev", "geminicli.com", "clawhub.ai", "openrouter.ai",
}
MAX_BODY = 25_000_000
RETRIES = 4  # extra attempts after the first for 5xx/429/timeouts, waiting 1/2/4/8 s
MAX_RETRY_AFTER = 120  # honour Retry-After within one sync; longer waits fail and reschedule the source
RETRYABLE = {429, 500, 502, 503, 504}
COMPRESS_OVER = 512
CACHE_DDL = """CREATE TABLE IF NOT EXISTS http_cache(
  url_sha TEXT PRIMARY KEY, url TEXT NOT NULL, etag TEXT, modified TEXT, sha256 TEXT NOT NULL,
  codec TEXT NOT NULL, size INTEGER NOT NULL, fetched_at INTEGER NOT NULL, body BLOB NOT NULL
) WITHOUT ROWID, STRICT"""


class Interrupted(Exception):
    """A retry back-off was cut short by the caller's stop condition (cancel or time budget)."""


class FetchError(RuntimeError):
    def __init__(self, code: str, retry_after: int = 0):
        super().__init__(code)
        self.retry_after = retry_after
        self.retryable = False


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
    """Thread-safe client: immutable/TTL hits skip the network, the rest revalidate with ETag.

    `offline=True` answers only from cache. Concurrent gets of one URL share a single request.
    Legacy `<sha>.json` cache files in `cache_dir` are ignored, not migrated.
    """

    def __init__(self, cache_dir: str | Path, github_token: str | None = None, offline: bool = False,
                 ttl: int | None = None, opener=None, retries: int = RETRIES, sleep=time.sleep):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.offline, self.ttl = offline, ttl
        self.opener = opener or build_opener(SafeRedirect)
        self.retries, self.sleep = max(0, retries), sleep
        self._local = threading.local()  # per-thread stop condition for retry back-off
        self.requests = 0  # network round trips, for budgets and tests
        self._db_lock = threading.Lock()
        self._mutex = threading.Lock()
        self._inflight: dict[str, tuple[threading.Event, dict]] = {}
        self._db = sqlite3.connect(self.cache_dir / "http-cache.db", check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(CACHE_DDL)
        self._db.commit()

    def close(self):
        with self._db_lock:
            self._db.close()

    def get(self, url: str, immutable: bool = False) -> bytes:
        validate_url(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        with self._mutex:
            pending = self._inflight.get(key)
            owner = pending is None
            if owner:
                pending = self._inflight[key] = (threading.Event(), {})
        event, box = pending
        if not owner:
            event.wait()
            if "error" in box:
                raise box["error"]
            return box["body"]
        try:
            box["body"] = self._fetch(url, key, immutable)
            return box["body"]
        except BaseException as exc:
            box["error"] = exc
            raise
        finally:
            with self._mutex:
                self._inflight.pop(key, None)
            event.set()

    def get_many(self, urls: list[str], workers: int = 12, immutable: bool = False) -> list:
        """Bounded concurrent gets; each slot is bytes or the FetchError for that URL, in input order."""
        def one(url):
            try:
                return self.get(url, immutable)
            except FetchError as exc:
                return exc
        if not urls:
            return []
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(urls)))) as pool:
            return list(pool.map(one, urls))

    def json(self, url: str, immutable: bool = False):
        try:
            return json.loads(self.get(url, immutable))
        except (ValueError, UnicodeError) as exc:
            raise FetchError("invalid_json_response") from exc

    def _cached(self, key: str) -> dict | None:
        with self._db_lock:
            row = self._db.execute("SELECT etag,modified,sha256,codec,fetched_at,body FROM http_cache WHERE url_sha=?",
                                   (key,)).fetchone()
        if not row:
            return None
        etag, modified, sha, codec, fetched_at, data = row
        try:
            body = zlib.decompress(data) if codec == "zlib" else bytes(data)
        except zlib.error:
            return None
        if hashlib.sha256(body).hexdigest() != sha:
            return None  # Corrupt entry: refetch instead of serving it.
        return {"etag": etag, "modified": modified, "fetched_at": fetched_at, "body": body}

    def _store(self, key: str, url: str, etag, modified, body: bytes):
        compressed = len(body) > COMPRESS_OVER
        data = zlib.compress(body, 6) if compressed else body
        with self._db_lock:
            self._db.execute("INSERT OR REPLACE INTO http_cache VALUES(?,?,?,?,?,?,?,?,?)",
                             (key, url, etag, modified, hashlib.sha256(body).hexdigest(), "zlib" if compressed else "raw",
                              len(body), int(time.time() * 1000), data))
            self._db.commit()

    def _touch(self, key: str):
        with self._db_lock:
            self._db.execute("UPDATE http_cache SET fetched_at=? WHERE url_sha=?", (int(time.time() * 1000), key))
            self._db.commit()

    def _fetch(self, url: str, key: str, immutable: bool) -> bytes:
        cached = self._cached(key)
        if cached:
            fresh = self.ttl is not None and time.time() * 1000 - cached["fetched_at"] < self.ttl * 1000
            if immutable or fresh or self.offline:
                return cached["body"]
        if self.offline:
            raise FetchError("not_cached")
        headers = {"User-Agent": "Orbit-catalog/1", "Accept": "application/json"}
        if urlsplit(url).hostname == "api.github.com" and self.github_token:
            headers["Authorization"] = "Bearer " + self.github_token
        if cached:
            for field, header in (("etag", "If-None-Match"), ("modified", "If-Modified-Since")):
                if cached[field]:
                    headers[header] = cached[field]
        attempt = 0
        while True:
            try:
                return self._request(url, key, headers, cached)
            except FetchError as exc:
                if attempt >= self.retries or not getattr(exc, "retryable", False) or exc.retry_after > MAX_RETRY_AFTER:
                    raise
                self._backoff(max(2 ** attempt, exc.retry_after))
                attempt += 1

    @contextmanager
    def interruptible(self, stop):
        """Within this block (this thread only), retry back-off raises ``Interrupted`` as soon
        as ``stop()`` is true instead of sleeping out the full delay."""
        previous = getattr(self._local, "stop", None)
        self._local.stop = stop
        try:
            yield self
        finally:
            self._local.stop = previous

    def _backoff(self, seconds: float):
        stop = getattr(self._local, "stop", None)
        if stop is None:
            return self.sleep(seconds)
        if self.sleep is not time.sleep:  # injected clock (tests): one call, checked around it
            if stop():
                raise Interrupted
            self.sleep(seconds)
            if stop():
                raise Interrupted
            return
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            if stop():
                raise Interrupted
            time.sleep(min(0.2, left))
        if stop():
            raise Interrupted

    def _request(self, url: str, key: str, headers: dict, cached: dict | None) -> bytes:
        with self._mutex:
            self.requests += 1
        try:
            with self.opener.open(Request(url, headers=headers), timeout=30) as response:
                body = response.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    raise FetchError("source_response_too_large")
                self._store(key, url, response.headers.get("ETag"), response.headers.get("Last-Modified"), body)
                return body
        except HTTPError as exc:
            if exc.code == 304 and cached:
                self._touch(key)
                return cached["body"]
            headers = exc.headers or {}
            delay = headers.get("Retry-After", "0") or "0"
            wait = int(delay) if delay.isdigit() else 0
            # GitHub answers an exhausted primary or secondary rate limit with 403 (docs.github.com
            # "Rate limits for the REST API": Retry-After, or x-ratelimit-remaining 0 + reset epoch).
            limited = exc.code == 403 and (wait > 0 or headers.get("x-ratelimit-remaining") == "0")
            if limited and not wait and str(headers.get("x-ratelimit-reset", "")).isdigit():
                wait = max(1, int(headers["x-ratelimit-reset"]) - int(time.time()))
            error = FetchError(f"http_{exc.code}", wait)
            error.retryable = exc.code in RETRYABLE or limited
            raise error from None
        except (URLError, TimeoutError, OSError) as exc:
            error = FetchError("source_network_error")
            error.retryable = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
            raise error from exc
