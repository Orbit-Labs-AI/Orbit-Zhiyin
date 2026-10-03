"""Shared storage location for the macOS App, CLI and local service."""

import os
from pathlib import Path


def default_home() -> Path:
    return Path(
        os.environ.get("ORBIT_HOME", str(Path.home() / "Library/Application Support/Orbit"))
    ).expanduser()
