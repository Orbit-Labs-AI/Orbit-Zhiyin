"""Platform fixtures: a fake gateway over a temporary home, and a real Gateway client."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from orbit_backend.appdb import AppDB
from orbit_backend.platform import logs, telemetry
from orbit_backend.platform.runtime import Platform
from orbit_backend.services.events import EventBus
from orbit_backend.services.gateway import Gateway, Revisions
from orbit_backend.services.routes_data import ReadPool
from orbit_backend.services.snapshots import SnapshotStore
from orbit_backend.services.supervisor import SupervisorConfig

TOKEN = "synthetic-test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


class FakeState:
    def __init__(self):
        self.active: dict | None = None
        self.items: list[dict] = []

    def active_job(self):
        return self.active

    def jobs(self):
        return list(self.items)


class FakeSupervisor:
    def __init__(self):
        self.info = {"ingest": {"state": "idle", "pid": None, "restarts": 0,
                                "last_hb_age_s": None},
                     "analysis": {"state": "idle", "pid": None, "restarts": 0,
                                  "last_hb_age_s": None}}

    def services(self):
        return {k: dict(v) for k, v in self.info.items()}


def fake_gateway(home: Path) -> SimpleNamespace:
    home.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        home=home, appdb=AppDB(home / "app.db"), revisions=Revisions(), state=FakeState(),
        supervisor=FakeSupervisor(), bus=EventBus(), config=SupervisorConfig(),
        snapshots=SnapshotStore(home / "cache" / "ui.sqlite"),
        reads=ReadPool(home / "orbit.db"), stopping=None, sync_thread=None)


@pytest.fixture
def platform_env(tmp_path):
    gw = fake_gateway(tmp_path / "home")
    platform = Platform(gw, maintenance_tick_s=3600)
    gw.platform = platform
    yield platform
    platform.close()
    telemetry.install(None)
    logs.teardown()
    gw.snapshots.close()
    gw.reads.close()
    gw.appdb.close()


@pytest.fixture
def started(platform_env):
    """Platform with logging and telemetry installed (maintenance thread idle)."""
    platform_env.start()
    return platform_env


@pytest.fixture
def gateway_client(tmp_path):
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, tick_s=0.05)
    gateway = Gateway(tmp_path / "gw", config=config, discovery=lambda: [],
                      prewarm_debounce_s=3600.0)
    client = TestClient(gateway.app(token=TOKEN, port=PORT), base_url=BASE, headers=AUTH)
    with client:
        yield client, gateway
    logging.getLogger("orbit").handlers.clear()


@pytest.fixture(autouse=True)
def _reset_exclusion_provider():
    """Every gateway registers the process-wide exclusion provider; exclusion.merged is
    fail-closed, so a provider left over from an earlier test's closed app.db must not leak."""
    from orbit_backend.sessionops import exclusion

    exclusion.set_provider(None)
    yield
    exclusion.set_provider(None)
