"""Gateway over a temporary home and a fake user HOME; offline, no workers started."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbit_backend import privacy_rules
from orbit_backend.appdata import sources_scope
from orbit_backend.services.gateway import Gateway
from orbit_backend.services.supervisor import SupervisorConfig
from orbit_backend.sessionops import exclusion

TESTS = Path(__file__).resolve().parents[1]
for extra in (TESTS / "services", TESTS / "ai" / "generate"):  # synthetic.py, fakectx.py
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

TOKEN = "synthetic-test-token-0123456789abcdef"


@pytest.fixture
def user_home(tmp_path, monkeypatch) -> Path:
    """A fake ``~`` with fake agent dirs; the real HOME is never read."""
    path = tmp_path / "userhome" / "alice"
    (path / ".claude" / "projects").mkdir(parents=True)
    (path / ".codex" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USER", "alice")
    monkeypatch.setenv("LOGNAME", "alice")
    return path


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "orbit-home"
    path.mkdir()
    return path


def make_gateway(home: Path) -> Gateway:
    config = SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0, tick_s=0.05)
    return Gateway(home, config=config, discovery=lambda: [], prewarm_debounce_s=3600.0)


def close_gateway(gw: Gateway) -> None:
    exclusion.set_provider(None)
    sources_scope.set_provider(None)
    privacy_rules.bind(None)
    gw.platform.close()
    gw.reads.close()
    gw.appdb.close()


@pytest.fixture
def gateway(home, user_home):
    gw = make_gateway(home)
    yield gw
    close_gateway(gw)


def client_for(gw: Gateway) -> TestClient:
    # No lifespan: routes only, workers never start.
    return TestClient(gw.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                      headers={"Authorization": f"Bearer {TOKEN}"})


@pytest.fixture
def client(gateway):
    return client_for(gateway)


@pytest.fixture(autouse=True)
def _reset_exclusion_provider():
    """Every gateway registers the process-wide exclusion provider; exclusion.merged is
    fail-closed, so a provider left over from an earlier test's closed app.db must not leak."""
    from orbit_backend.sessionops import exclusion

    exclusion.set_provider(None)
    yield
    exclusion.set_provider(None)
