"""Shared harness for the cross-package tests under ``tests/``.

- Puts the repository root (``evals``, ``benchmarks``, ``scripts`` are repository packages, not
  installed ones) and the backend's stdlib-only synthetic writer on ``sys.path`` once, so test
  modules no longer inject paths themselves.
- ``synthetic``: the synthetic Codex tree writer (``packages/backend/tests/services/synthetic.py``).
- ``gateway_harness``: a factory for a real :class:`Gateway` under ``tmp_path`` (temporary HOME,
  no network, no spawned agent CLI) wrapped in a FastAPI ``TestClient``.

Everything stays under ``tmp_path``; no real agent home, CLI, model or network is touched.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "packages/backend/tests/services", ROOT / "tests/integration"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from gateway_support import BASE, TOKEN, GatewayHarness, no_network, no_spawn  # noqa: E402


@pytest.fixture
def synthetic():
    import synthetic as module

    return module


@pytest.fixture
def gateway_harness(tmp_path, monkeypatch) -> Callable[..., GatewayHarness]:
    """``gateway_harness(discovery=..., agent_dirs=(".claude", ".codex"))`` → GatewayHarness.

    ``discovery=None`` keeps the gateway's default discovery, which then only sees the
    temporary HOME. Agent detection for installs looks at the temporary HOME and an empty bin.
    """
    from fastapi.testclient import TestClient

    from tandem_backend import install
    from tandem_backend.ai import engines
    from tandem_backend.install import env as envmod
    from tandem_backend.services.gateway import Gateway
    from tandem_backend.services.supervisor import SupervisorConfig

    user_home = tmp_path / "user-home"
    user_home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("TANDEM_INSTALL_HOME", str(user_home))
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    # No network: the background catalog refresher still imports the bundled library seed,
    # but never schedules the first network sync.
    monkeypatch.setenv("TANDEM_CATALOG_AUTOSYNC", "0")
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "DSH_HOME", "HERMES_HOME",
                 "PI_CODING_AGENT_DIR", "KIMI_CODE_HOME", "ANTHROPIC_API_KEY", "XDG_DATA_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(engines, "FALLBACK_DIRS", ())
    monkeypatch.setattr("tandem_catalog.network.HttpClient.get", no_network)
    envmod._memo.clear()
    # The A4 tools view caches results in a process-global LRU keyed by scope and revision but
    # not by gateway home, so a second gateway in the same process at the same data_rev would
    # be served the first one's numbers (follow-up for uiview). One fresh cache per test.
    from tandem_backend.uiview import a4a6_common

    monkeypatch.setattr(a4a6_common, "CACHE", a4a6_common.LRU(32))
    stack = ExitStack()

    def make(*, discovery=lambda: [], agent_dirs=(".claude", ".codex"), fetcher=None,
             stale_s: float = 3.0) -> GatewayHarness:
        for name in agent_dirs:
            (user_home / name).mkdir(parents=True, exist_ok=True)
        config = SupervisorConfig(heartbeat_s=0.3, stale_s=stale_s, term_grace_s=1.0,
                                  backoff_s=(0.1, 0.2, 0.4, 0.8), tick_s=0.05,
                                  light_timeout_s=60.0, heavy_timeout_s=120.0)
        tandem_home = tmp_path / "tandem"
        gateway = Gateway(tandem_home, config=config, discovery=discovery,
                          prewarm_debounce_s=3600.0)
        app = gateway.app(token=TOKEN, port=8765)
        svc = install.get_default_service()
        svc.env = envmod.Env(home=user_home, environ={"PATH": str(bindir)}, search_dirs=[bindir],
                             run=no_spawn)
        if fetcher is not None:
            svc.fetcher = fetcher
        # LIFO: the client (and gateway lifespan) exits first, then the AI service closes.
        stack.callback(lambda: gateway._ai.close() if getattr(gateway, "_ai", None) else None)
        client = stack.enter_context(
            TestClient(app, base_url=BASE, headers={"Authorization": f"Bearer {TOKEN}"}))
        return GatewayHarness(client, gateway, user_home, tandem_home)

    yield make
    stack.close()
    install.set_default_service(None)
