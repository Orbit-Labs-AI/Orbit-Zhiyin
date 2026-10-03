"""Shell-feed fixtures: real gateways over temporary homes, synthetic data only.

Helpers come from uniquely named sibling modules (realtime_fixtures, synthetic,
ai_support); no test here reads a real agent home or touches the network.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TESTS = Path(__file__).resolve().parent.parent
for sub in ("realtime", "services", "ai"):
    if str(TESTS / sub) not in sys.path:
        sys.path.insert(0, str(TESTS / sub))

from tandem_backend.services.gateway import Gateway  # noqa: E402
from tandem_backend.services.supervisor import SupervisorConfig  # noqa: E402

TOKEN = "synthetic-test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def fast_config() -> SupervisorConfig:
    return SupervisorConfig(heartbeat_s=0.3, stale_s=3.0, term_grace_s=1.0,
                            backoff_s=(0.1, 0.2, 0.4, 0.8), tick_s=0.05,
                            light_timeout_s=60.0, heavy_timeout_s=120.0)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """A throwaway HOME so nothing can reach the real ~/.claude or ~/.codex."""
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def gateway_factory(tmp_path, isolated_home):
    """``make(home=None, started=True, **options)`` → (client, gateway)."""
    opened: list[tuple[TestClient, Gateway, bool]] = []

    def make(home: Path | None = None, started: bool = True, **options):
        options.setdefault("discovery", lambda: [])
        options.setdefault("prewarm_debounce_s", 3600.0)
        gateway = Gateway(home or tmp_path / "tandem", config=fast_config(), **options)
        client = TestClient(gateway.app(token=TOKEN, port=PORT), base_url=BASE, headers=AUTH)
        if started:
            client.__enter__()
        opened.append((client, gateway, started))
        return client, gateway

    yield make
    for client, gateway, started in opened:
        if started:
            client.__exit__(None, None, None)
        else:
            gateway.close()
    logging.getLogger("tandem").handlers.clear()


@pytest.fixture(autouse=True)
def _reset_exclusion_provider():
    """Every gateway registers the process-wide exclusion provider; exclusion.merged is
    fail-closed, so a provider left over from an earlier test's closed app.db must not leak."""
    from tandem_backend.sessionops import exclusion

    exclusion.set_provider(None)
    yield
    exclusion.set_provider(None)
