"""AI runtime fixtures: temporary HOME, fake `claude` / `codex` CLIs, FakeEngine.

Nothing here is autouse, so sibling test packages under tests/ai keep their own setup.
Tests never run a real model, read real agent homes or touch the network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ai_support import ANSWER, answer_task  # noqa: F401

from orbit_backend.ai import engines, registry
from orbit_backend.ai.engines import FakeEngine
from orbit_backend.ai.service import AIService, service
from orbit_backend.appdb import AppDB
from orbit_backend.services.events import EventBus

BIN = Path(__file__).parent / "bin"
@pytest.fixture
def ai_env(tmp_path, monkeypatch):
    """Isolated HOME and PATH (no real CLI reachable), clean engine caches."""
    home = tmp_path / "userhome"
    home.mkdir()
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{empty}:/usr/bin:/bin")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(engines, "FALLBACK_DIRS", ())
    monkeypatch.setattr(engines, "_help_cache", {})
    return SimpleNamespace(home=home, bin=empty, tmp=tmp_path)


class FakeCli:
    def __init__(self, root: Path, bindir: Path):
        self.log = root / "fake-cli.log"
        self.mode_file = root / "fake-cli.mode"
        self.mode = "ok"
        for name in ("claude", "codex"):
            wrapper = bindir / name
            wrapper.write_text(
                "#!/bin/sh\n"
                f"FAKE_LOG='{self.log}' FAKE_MODE=\"$(cat '{self.mode_file}')\" "
                f"exec '{sys.executable}' '{BIN / name}' \"$@\"\n", encoding="utf-8")
            wrapper.chmod(0o755)

    @property
    def mode(self) -> str:
        return self.mode_file.read_text().strip()

    @mode.setter
    def mode(self, value: str) -> None:
        self.mode_file.write_text(value)

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def fake_cli(ai_env):
    return FakeCli(ai_env.tmp, ai_env.bin)


@pytest.fixture
def ai_gw(ai_env):
    home = ai_env.tmp / "orbit"
    gw = SimpleNamespace(home=home, appdb=AppDB(home / "app.db"), bus=EventBus(), reads=None)
    yield gw
    if getattr(gw, "_ai", None) is not None:
        gw._ai.close()
    gw.appdb.close()


@pytest.fixture
def ai_svc(ai_gw, monkeypatch):
    """AIService with the fallback pack, a FakeEngine and AI switched on for it."""
    monkeypatch.setattr(AIService, "_builder", lambda self: None)
    registered: list[str] = []

    def register(spec: dict) -> dict:
        registered.append(spec["task_id"])
        return registry.register(spec)

    svc = service(ai_gw)
    fake = FakeEngine({"*": {"answer": "ok"}})
    svc.register_engine("fake", fake)
    svc.set_consent({"mode": "agent", "default_engine": "fake",
                     "grants": {"fake": {"summary": True}}})
    register(answer_task())
    svc.fake, svc.register_task = fake, register
    yield svc
    for task_id in registered:
        registry.unregister(task_id)
