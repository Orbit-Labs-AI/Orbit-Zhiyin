"""Fixtures for realtime tests over a tmp tandem.db."""

from __future__ import annotations

from pathlib import Path

import pytest
from realtime_fixtures import Tandem


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def tandem(home):
    t = Tandem(home)
    yield t
    t.db.close()
