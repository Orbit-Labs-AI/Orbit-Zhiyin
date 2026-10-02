"""Export fixtures over a tmp home (helpers live in export_world.py)."""

from __future__ import annotations

import pytest
from export_world import World, client_for, fake_gateway


@pytest.fixture
def world(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    w = World(home)
    yield w
    w.db.close()


@pytest.fixture
def env(world):
    gw = fake_gateway(world.home, data_rev=1)
    yield client_for(gw), gw, world
    gw.appdb.close()
