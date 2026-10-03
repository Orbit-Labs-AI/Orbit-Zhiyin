"""Fixtures for realtime tests over a tmp orbit.db."""

from __future__ import annotations

from pathlib import Path

import pytest
from realtime_fixtures import Orbit


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def orbit(home):
    t = Orbit(home)
    yield t
    t.db.close()
