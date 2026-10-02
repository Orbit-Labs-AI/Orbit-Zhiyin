"""Codex bundled in an app (outside PATH) and prerelease version strings."""

import os
import subprocess

from tandem_backend.install import env as envmod


def _bundle(root, version_line):
    bindir = root / "ChatGPT.app/Contents/Resources/codex-cli/bin"
    bindir.mkdir(parents=True)
    exe = bindir / "codex"
    exe.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    exe.chmod(0o755)
    return exe


def test_app_bundle_codex_found_and_prerelease_kept(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    apps = tmp_path / "Applications"
    exe = _bundle(apps, "codex-cli 0.159.0-alpha.12.1")
    monkeypatch.setattr(envmod, "APP_ROOTS", (str(apps),))
    env = envmod.Env(home=home, environ={"PATH": ""}, run=subprocess.run)
    assert envmod.find_binary("codex", env) == str(exe)
    probe = envmod.probe_version(str(exe), env)
    assert probe["version"] == "0.159.0-alpha.12.1"
    caps = envmod.capabilities("codex", probe["version"])
    assert caps["basis"] == "probed"


def test_user_applications_and_rc_suffix(tmp_path, monkeypatch):
    home = tmp_path / "home"
    exe = _bundle(home / "Applications", "0.1.1-rc.2")
    monkeypatch.setattr(envmod, "APP_ROOTS", ("~/Applications",))
    env = envmod.Env(home=home, environ={"PATH": ""}, run=subprocess.run)
    assert envmod.find_binary("codex", env) == str(exe)
    assert envmod.probe_version(str(exe), env)["version"] == "0.1.1-rc.2"
    assert envmod.probe_version(str(exe), env)["raw"] == "0.1.1-rc.2"
    assert os.access(exe, os.X_OK)


def test_engines_find_binary_globs_app_bundles(tmp_path, monkeypatch):
    from tandem_backend.ai import engines

    exe = _bundle(tmp_path / "Applications", "codex-cli 0.159.0-alpha.12.1")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(engines, "FALLBACK_DIRS",
                        (str(tmp_path / "Applications/*.app/Contents/Resources/codex-cli/bin"),))
    assert engines.find_binary("codex") == str(exe)
