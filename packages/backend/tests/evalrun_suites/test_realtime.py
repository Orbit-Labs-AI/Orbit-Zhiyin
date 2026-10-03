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


def test_clean_replay(tmp_path, monkeypatch):
    _inject(monkeypatch, {**GOOD, "detect_latency_s": {"failing": 4.0, "just_finished": 60.0,
                                                        "awaiting_approval": 12.0}})
    result = suite.run(EvalContext(tmp=tmp_path))
    ids = {c.id: c.passed for c in result.checks}
    assert ids == {"realtime.case.fail_streak": True, "realtime.case.approval_wait": True,
                   "realtime.false_alarms": True, "realtime.latency.failing": True,
                   "realtime.latency.just_finished": True, "realtime.latency.awaiting_approval": True}


def test_undetected_state_is_a_failed_latency_check(tmp_path, monkeypatch):
    _inject(monkeypatch, GOOD)  # awaiting_approval latency is None: never detected
    result = suite.run(EvalContext(tmp=tmp_path))
    check = next(c for c in result.checks if c.id == "realtime.latency.awaiting_approval")
    assert not check.passed and check.value is None and check.detail == "not detected"
    assert result.score == 5 / 6


@pytest.mark.parametrize("patch,check", [
    ({"false_alarms": 2}, "realtime.false_alarms"),
    ({"detect_latency_s": {"failing": 45.0}}, "realtime.latency.failing"),
    ({"cases": [{"id": "fail_streak", "passed": False, "detail": "missed"}]}, "realtime.case.fail_streak"),
])
def test_broken_replay(tmp_path, monkeypatch, patch, check):
    _inject(monkeypatch, {**GOOD, **patch})
    result = suite.run(EvalContext(tmp=tmp_path))
    assert check in {c.id for c in result.checks if not c.passed}
