import hashlib
import io
import sqlite3
import threading
from email.message import Message
from urllib.error import HTTPError

import pytest

from tandem_catalog.network import MAX_BODY, FetchError, HttpClient, SafeRedirect

URL = "https://models.dev/api.json"


class Response(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value


class FakeOpener:
    """Local stand-in for urllib's opener; records request headers, never touches the network."""

    def __init__(self, *responses, delay=None):
        self.responses, self.calls, self.delay = list(responses), [], delay

    def open(self, request, timeout=30):
        self.calls.append(dict(request.header_items()))
        if self.delay:
            self.delay.wait(2)
        result = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(result, int):
            headers = Message()
            headers["Retry-After"] = "7"
            raise HTTPError(request.full_url, result, "status", headers, None)
        body, headers = result
        return Response(body, headers)


def client(tmp_path, *responses, **kwargs):
    opener = FakeOpener(*responses, delay=kwargs.pop("delay", None))
    return HttpClient(tmp_path, opener=opener, **kwargs), opener


def test_conditional_revalidation_reuses_cached_body_on_304(tmp_path):
    http, opener = client(tmp_path, (b'{"a": 1}', {"ETag": '"v1"'}), 304)
    assert http.json(URL) == {"a": 1}
    assert http.get(URL) == b'{"a": 1}'
    assert opener.calls[1]["If-none-match"] == '"v1"'
    assert http.requests == 2


def test_immutable_and_ttl_hits_skip_network(tmp_path):
    http, opener = client(tmp_path, (b"body", {}), ttl=3600)
    http.get(URL)
    http.get(URL)
    http.get(URL, immutable=True)
    assert len(opener.calls) == 1
    nottl, opener2 = client(tmp_path, (b"body2", {}))
    assert nottl.get(URL, immutable=True) == b"body" and not opener2.calls
    assert nottl.get(URL) == b"body2" and len(opener2.calls) == 1


def test_offline_reads_only_cache(tmp_path):
    online, _ = client(tmp_path, (b"x" * 2000, {}))
    online.get(URL)
    offline, opener = client(tmp_path, (b"never", {}), offline=True)
    assert offline.get(URL) == b"x" * 2000
    with pytest.raises(FetchError, match="not_cached"):
        offline.get("https://models.dev/other.json")
    assert not opener.calls and offline.requests == 0


def test_cache_is_compressed_and_digest_is_plain_sha256(tmp_path):
    body = b"y" * 5000
    http, _ = client(tmp_path, (body, {}))
    http.get(URL)
    with sqlite3.connect(tmp_path / "http-cache.db") as conn:
        sha, codec, size, data = conn.execute("SELECT sha256,codec,size,body FROM http_cache").fetchone()
    assert sha == hashlib.sha256(body).hexdigest() and codec == "zlib" and size == 5000 and len(data) < 200


def test_concurrent_gets_of_one_url_share_one_request(tmp_path):
    gate = threading.Event()
    http, opener = client(tmp_path, (b"shared", {}), delay=gate)
    results = []
    threads = [threading.Thread(target=lambda: results.append(http.get(URL))) for _ in range(6)]
    for thread in threads:
        thread.start()
    while not http._inflight:
        pass
    gate.set()
    for thread in threads:
        thread.join()
    assert results == [b"shared"] * 6 and len(opener.calls) == 1


def test_get_many_keeps_order_and_isolates_errors(tmp_path):
    http, _ = client(tmp_path, (b"ok", {}))
    urls = [URL, "http://models.dev/insecure", "https://models.dev/b"]
    out = http.get_many(urls, workers=3)
    assert out[0] == b"ok" and isinstance(out[1], FetchError) and out[2] == b"ok"


def test_status_errors_and_oversize_bodies(tmp_path):
    http, _ = client(tmp_path, 429)
    with pytest.raises(FetchError) as caught:
        http.get(URL)
    assert str(caught.value) == "http_429" and caught.value.retry_after == 7
    big, _ = client(tmp_path / "big", (b"z" * (MAX_BODY + 1), {}))
    with pytest.raises(FetchError, match="source_response_too_large"):
        big.get(URL)


def test_redirects_stay_on_allowlisted_same_host():
    class Req:
        full_url = "https://api.github.com/repos/a/b"
    with pytest.raises(FetchError, match="source_url_not_allowed"):
        SafeRedirect().redirect_request(Req(), None, 302, "", {}, "https://evil.example/x")
    with pytest.raises(FetchError, match="cross_host_redirect"):
        SafeRedirect().redirect_request(Req(), None, 302, "", {}, "https://models.dev/x")
