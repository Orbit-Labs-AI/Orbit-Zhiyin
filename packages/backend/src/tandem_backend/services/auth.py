"""Gateway request guard: Bearer token, Host / Origin checks and security headers.

The token comes from the native host through ``TANDEM_API_TOKEN`` (never argv or URLs)
and must be at least 32 characters. Pages are served same-origin, so a foreign Origin
or a Host other than loopback is rejected before routing (DNS-rebinding defence).
"""

from __future__ import annotations

import hmac
import json

TOKEN_ENV = "TANDEM_API_TOKEN"
MIN_TOKEN_LENGTH = 32
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
SECURITY_HEADERS = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"content-security-policy", b"default-src 'self'; connect-src 'self'; frame-ancestors 'none'"),
)


def validate_token(token: str | None) -> str:
    if not token or len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"{TOKEN_ENV} must be set to at least {MIN_TOKEN_LENGTH} characters")
    return token


def error_body(code: str, message: str, retryable: bool = False) -> bytes:
    return json.dumps({"error": {"code": code, "message": message, "retryable": retryable}},
                      ensure_ascii=False).encode()


class ApiError(Exception):
    """Uniform ``{"error": {code, message, retryable}}`` response raised by gateway routes."""

    def __init__(self, status: int, code: str, message: str, retryable: bool = False,
                 retry_after: int | None = None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable, self.retry_after = retryable, retry_after

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message,
                          "retryable": self.retryable}}

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)} if self.retry_after is not None else {}


class GuardMiddleware:
    """Pure ASGI middleware so SSE streams are not buffered."""

    def __init__(self, app, token: str, port: int | None, hosts=LOOPBACK_HOSTS,
                 public_paths=()):
        self.app = app
        self.public_paths = frozenset(public_paths)  # GET pages loaded before the token exists.
        self.token = validate_token(token).encode()
        self.port = port
        self.hosts = tuple(hosts)
        authorities = [h if port is None else f"{h}:{port}" for h in self.hosts]
        self.authorities = set(authorities) | (set(self.hosts) if port in (None, 80) else set())
        self.origins = {f"http://{a}" for a in self.authorities}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        public = scope.get("method") in ("GET", "HEAD") and scope.get("path") in self.public_paths
        failure = self.check(headers, require_token=not public)

        async def secured(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in SECURITY_HEADERS if k not in present]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        if failure is not None:
            status, code, message = failure
            body = error_body(code, message)
            await secured({"type": "http.response.start", "status": status, "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *([(b"www-authenticate", b"Bearer")] if status == 401 else [])]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, secured)

    def check(self, headers: dict[str, str],
              require_token: bool = True) -> tuple[int, str, str] | None:
        host = headers.get("host", "")
        if host not in self.authorities:
            return 403, "invalid_host", "Host is not this local gateway"
        origin = headers.get("origin")
        if origin is not None and origin not in self.origins:
            return 403, "invalid_origin", "Cross-origin requests are not allowed"
        if not require_token:
            return None
        scheme, _, supplied = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(),
                                                                   self.token):
            return 401, "unauthorized", "Missing or invalid bearer token"
        return None
