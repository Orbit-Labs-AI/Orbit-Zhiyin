"""Shared storage location for the macOS App, CLI and local service."""

import os
from pathlib import Path

from orbit_data import legacy


def default_home() -> Path:
    if os.environ.get("ORBIT_HOME"):
        return Path(os.environ["ORBIT_HOME"]).expanduser()
    home = Path.home() / "Library/Application Support/Orbit"
    legacy.move_app_dir(home)
    return home
