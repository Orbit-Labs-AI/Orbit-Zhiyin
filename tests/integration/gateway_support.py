"""Gateway test helpers shared by tests/integration and tests/e2e (fixtures live in
tests/conftest.py). A uniquely named module, because several ``conftest`` modules exist in the
repository and importing ``conftest`` by name would be ambiguous."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

TOKEN = "synthetic-test-token-0123456789abcdef"
BASE = "http://127.0.0.1:8765"


def no_network(*args, **kwargs):
    raise AssertionError("cross-package tests must not reach the network")


def no_spawn(argv, **kwargs):
    raise AssertionError(f"cross-package tests must not spawn {argv}")


def wait_for(predicate, timeout=90.0, interval=0.05, what=""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what or predicate}")


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@dataclass
class GatewayHarness:
    """One running gateway: ``client`` is authenticated; ``home`` is the temporary HOME."""

    client: object
    gateway: object
    home: Path
    orbit_home: Path
    jobs: list[dict] = field(default_factory=list)

    ok = staticmethod(ok)
    wait_for = staticmethod(wait_for)

    def get(self, path: str, **params):
        return ok(self.client.get(path, params=params or None))

    def configure(self, agent: str, root: Path | str) -> str:
        return ok(self.client.post("/v1/app/sources", json={"agent": agent, "root": str(root)}))["id"]

    def run_job(self, source_ids: list[str], kind: str = "import", timeout: float = 120) -> dict:
        job = ok(self.client.post("/v1/app/jobs", json={"kind": kind, "source_ids": source_ids}), 202)

        def finished():
            state = self.client.get(f"/v1/app/jobs/{job['id']}").json()
            return state if state["status"] not in ("queued", "running") else None

        state = wait_for(finished, timeout, 0.1, f"{kind} job")
        assert state["status"] == "completed", state
        self.jobs.append(state)
        return state

    def import_source(self, agent: str, root: Path | str) -> dict:
        return self.run_job([self.configure(agent, root)])
