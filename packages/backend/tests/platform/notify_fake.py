"""Fake gateway pieces for platform-notify tests: tmp app.db, real EventBus, recorded jobs.

Imported by the test modules (not a conftest, so platform-core can own that file)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.platform import notify
from tandem_backend.services.events import EventBus
from tandem_backend.services.jobs import AppState, JobConflict


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


class FakeJobs:
    def __init__(self):
        self.calls: list[tuple] = []
        self.conflict = False

    def submit(self, kind, source_ids=(), limit=None, files_by_source=None, phase=None,
               origin="user"):
        if self.conflict:
            raise JobConflict("busy")
        self.calls.append((kind, list(source_ids), phase, origin))
        return {"id": f"job-{len(self.calls)}", "kind": kind}


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def gw(tmp_path):
    appdb = AppDB(tmp_path / "app.db")
    gateway = SimpleNamespace(appdb=appdb, bus=EventBus(), state=AppState(tmp_path / "x.json"),
                              jobs=FakeJobs(), platform=SimpleNamespace(settings=None),
                              home=tmp_path)
    yield gateway
    if notify._active is not None:
        notify._active.close()
    appdb.close()
