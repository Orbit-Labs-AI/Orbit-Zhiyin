"""Gateway fixtures over synthetic Codex trees; tests never touch real agent homes."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

from synthetic import write_codex_tree  # noqa: E402

from tandem_backend.services.gateway import Gateway  # noqa: E402
from tandem_backend.services.supervisor import SupervisorConfig  # noqa: E402

TOKEN = "synthetic-test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
SESSIONS = 70  # head 50 (+7 days), window to 30 days, rest beyond.


def fast_config(**overrides) -> SupervisorConfig:
    values = {"heartbeat_s": 0.3, "stale_s": 3.0, "term_grace_s": 1.0,
              "backoff_s": (0.1, 0.2, 0.4, 0.8), "tick_s": 0.05,
              "light_timeout_s": 60.0, "heavy_timeout_s": 120.0, **overrides}
    return SupervisorConfig(**values)


def wait_for(predicate, timeout: float = 60.0, interval: float = 0.05, message: str = ""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {message or predicate}")


@pytest.fixture
def codex_root(tmp_path) -> Path:
    root = tmp_path / "agents" / "codex"
    write_codex_tree(root, SESSIONS)
    return root


def make_gateway(home: Path, config: SupervisorConfig | None = None, **options) -> Gateway:
    options.setdefault("discovery", lambda: [])
    options.setdefault("prewarm_debounce_s", 3600.0)
    return Gateway(home, config=config or fast_config(), **options)


@pytest.fixture
def client_factory(tmp_path):
    opened: list[TestClient] = []

    def make(home: Path | None = None, config: SupervisorConfig | None = None, **options):
        gateway = make_gateway(home or tmp_path / "home", config, **options)
        client = TestClient(gateway.app(token=TOKEN, port=PORT), base_url=BASE, headers=AUTH)
        client.__enter__()
        opened.append(client)
        return client, gateway

    yield make
    for client in opened:
        client.__exit__(None, None, None)


class LiveServer:
    """A real uvicorn server in a thread, for SSE and concurrent-read checks."""

    def __init__(self, gateway: Gateway):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(128)
        self.port = self.sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.gateway = gateway
        app = gateway.app(token=TOKEN, port=self.port)
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                                    timeout_graceful_shutdown=1))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]},
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        wait_for(lambda: self.server.started, 20, message="server start")
        return self

    def __exit__(self, *_):
        self.gateway.bus.close()  # Let open SSE streams finish before shutdown.
        self.server.should_exit = True
        self.thread.join(15)

    def client(self, **kwargs) -> httpx.Client:
        return httpx.Client(base_url=self.base, headers=AUTH, timeout=30, **kwargs)


@pytest.fixture
def live_server(tmp_path):
    servers: list[LiveServer] = []

    def make(config: SupervisorConfig | None = None, **options) -> LiveServer:
        server = LiveServer(make_gateway(tmp_path / "home", config, **options)).__enter__()
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.__exit__()


class SSEReader:
    """Collects SSE frames on a background thread from ``/v1/events``."""

    def __init__(self, base: str, topics: str = "job,data,analysis,service",
                 last_event_id: int | None = None):
        self.frames: list[dict] = []
        self.base, self.topics, self.last_event_id = base, topics, last_event_id
        self.stop = threading.Event()
        self.connected = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        assert self.connected.wait(10)

    def run(self):
        headers = dict(AUTH)
        if self.last_event_id is not None:
            headers["Last-Event-ID"] = str(self.last_event_id)
        with httpx.Client(base_url=self.base, headers=headers, timeout=None) as client:
            with client.stream("GET", "/v1/events", params={"topics": self.topics}) as response:
                assert response.status_code == 200
                self.connected.set()
                frame: dict = {}
                for line in response.iter_lines():
                    if self.stop.is_set():
                        return
                    if not line:
                        if "event" in frame:
                            self.frames.append(frame)
                        frame = {}
                    elif line.startswith("id: "):
                        frame["id"] = int(line[4:])
                    elif line.startswith("event: "):
                        frame["event"] = line[7:]
                    elif line.startswith("data: "):
                        frame["data"] = json.loads(line[6:])

    def events(self, name: str) -> list[dict]:
        return [f for f in self.frames if f["event"] == name]

    def close(self):
        self.stop.set()


def add_codex(client, root: Path) -> str:
    response = client.post("/v1/app/sources", json={"agent": "codex", "root": str(root)})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def run_job(client, kind: str = "import", source_ids=(), **fields) -> dict:
    response = client.post("/v1/app/jobs", json={"kind": kind, "source_ids": list(source_ids),
                                                 **fields})
    assert response.status_code == 202, response.text
    return response.json()


def wait_job(client, job_id: str, timeout: float = 120.0) -> dict:
    def finished():
        job = client.get(f"/v1/app/jobs/{job_id}").json()
        return job if job["status"] not in ("queued", "running") else None

    return wait_for(finished, timeout, 0.1, f"job {job_id}")


def bus_events(gateway: Gateway, name: str) -> list:
    frames, _ = gateway.bus.since(0)
    return [f for f in frames if f.event == name]


# The overview without a window serves the first-open fast path (7 days first); tests that
# assert the all-time snapshot lifecycle ask for all time explicitly.
ALL_TIME = {"days": 0}
