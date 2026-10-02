"""Fabricated agent homes only: no real ~/.claude, ~/.codex, agent process or network."""

import json
import subprocess
from pathlib import Path

import pytest

from tandem_backend.install import env as envmod


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TANDEM_INSTALL_HOME", str(tmp_path / "install-home"))
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "DSH_HOME", "HERMES_HOME", "PI_CODING_AGENT_DIR",
                 "KIMI_CODE_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(name, raising=False)
    envmod._memo.clear()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


@pytest.fixture
def fake_home(tmp_path) -> Path:
    home = tmp_path / "home"
    claude = home / ".claude"
    write(claude / "settings.json", json.dumps({"permissions": {"allow": []}}))
    write(claude / "settings.local.json", "{}")
    write(claude / "CLAUDE.md", "# me\n")
    write(claude / "skills/x/SKILL.md", "---\nname: x\n---\n")
    (claude / "agents").mkdir()
    (claude / "commands").mkdir()
    write(claude / "plugins/installed_plugins.json", "{}")
    write(home / ".claude.json", json.dumps({"mcpServers": {}}))
    codex = home / ".codex"
    write(codex / "config.toml", 'model = "x"\n')
    write(codex / "AGENTS.md", "# agents\n")
    write(codex / "hooks.json", "{}")
    for d in ("rules", "prompts", "skills"):
        (codex / d).mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("claude", "codex"):
        script = write(bin_dir / name, "#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
    return home


class FakeRun:
    """Stands in for subprocess.run; records calls, never spawns anything."""

    def __init__(self, outputs=None, error=None):
        self.calls = []
        self.outputs = outputs if outputs is not None else {"claude": "2.1.3 (Claude Code)", "codex": "codex-cli 0.80.0"}
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        assert kwargs["env"].keys() == {"PATH", "HOME", "NO_COLOR"}
        if self.error:
            raise self.error
        name = Path(argv[0]).name
        if name not in self.outputs:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        return subprocess.CompletedProcess(argv, 0, self.outputs[name], "")


@pytest.fixture
def fake_run():
    return FakeRun()


@pytest.fixture
def env(fake_home, fake_run, tmp_path):
    bin_dir = tmp_path / "bin"
    return envmod.Env(home=fake_home, environ={"PATH": str(bin_dir)}, search_dirs=[bin_dir], run=fake_run)
