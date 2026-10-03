import sys
import types

import pytest

from orbit_backend.evalrun import registry
from orbit_backend.evalrun.contract import Check, SuiteResult


def make_suite(suite_id: str, run):
    module = types.ModuleType(f"orbit_backend.evalrun.suites.{suite_id}")
    module.__doc__ = f"Fake suite {suite_id}."
    module.ID, module.TITLE, module.EV, module.run = suite_id, suite_id.title(), ("EV-12",), run
    return module


def _ok(ctx):
    (ctx.tmp / "scratch.txt").write_text("x")
    return SuiteResult("ok", [Check("ok.a", True, 1.0, 1.0), Check("ok.b", True)])


def _half(ctx):
    return SuiteResult("half", [Check("half.a", True), Check("half.b", False, 0.2, 0.5, "low")])


def _skip(ctx):
    return SuiteResult("skip", skipped="no data")


def _empty(ctx):
    return SuiteResult("empty", [], metrics={"pairs": 0})


def _boom(ctx):
    raise RuntimeError("kaput")


def _params(ctx):
    return SuiteResult("params", [Check("params.seen", ctx.params.get("x") == 1)],
                       metrics={"home": str(ctx.home)})


FAKES = {"ok": _ok, "half": _half, "skip": _skip, "boom": _boom, "empty": _empty, "params": _params}


@pytest.fixture
def fake_suites(monkeypatch):
    for suite_id, run in FAKES.items():
        monkeypatch.setitem(sys.modules, f"orbit_backend.evalrun.suites.{suite_id}",
                            make_suite(suite_id, run))
    monkeypatch.setattr(registry, "ids", lambda: sorted(FAKES))
    return FAKES
