"""EV-15 suite against a fake realtime.replay module injected into sys.modules."""

import sys
import types

import pytest

from tandem_backend.evalrun.contract import EvalContext
from tandem_backend.evalrun.suites import realtime as suite

GOOD = {"cases": [{"id": "fail_streak", "passed": True, "detail": ""},
                  {"id": "approval_wait", "passed": True, "detail": ""}],
        "detect_latency_s": {"failing": 4.0, "just_finished": 60.0, "awaiting_approval": None},
        "false_alarms": 0}


def _inject(monkeypatch, result):
    pkg = types.ModuleType("tandem_backend.realtime")
    replay = types.ModuleType("tandem_backend.realtime.replay")
    replay.run_cases = lambda: result
    pkg.replay = replay
    monkeypatch.setitem(sys.modules, "tandem_backend.realtime", pkg)
    monkeypatch.setitem(sys.modules, "tandem_backend.realtime.replay", replay)


def test_missing_package_skips(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "tandem_backend.realtime.replay", None)
    result = suite.run(EvalContext(tmp=tmp_path))
    assert result.skipped == "realtime package not installed"


def test_clean_replay(tmp_path, monkeypatch):
    _inject(monkeypatch, GOOD)
    result = suite.run(EvalContext(tmp=tmp_path))
    ids = {c.id: c.passed for c in result.checks}
    assert ids == {"realtime.case.fail_streak": True, "realtime.case.approval_wait": True,
                   "realtime.false_alarms": True, "realtime.latency.failing": True,
                   "realtime.latency.just_finished": True}


@pytest.mark.parametrize("patch,check", [
    ({"false_alarms": 2}, "realtime.false_alarms"),
    ({"detect_latency_s": {"failing": 45.0}}, "realtime.latency.failing"),
    ({"cases": [{"id": "fail_streak", "passed": False, "detail": "missed"}]}, "realtime.case.fail_streak"),
])
def test_broken_replay(tmp_path, monkeypatch, patch, check):
    _inject(monkeypatch, {**GOOD, **patch})
    result = suite.run(EvalContext(tmp=tmp_path))
    assert check in {c.id for c in result.checks if not c.passed}
