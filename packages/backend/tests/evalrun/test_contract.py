import sys
import types

import pytest

from orbit_backend.evalrun import registry
from orbit_backend.evalrun.contract import Check, SuiteResult


def test_score_is_fraction_of_passed_checks():
    result = SuiteResult("x", [Check("a", True), Check("b", False), Check("c", True), Check("d", True)])
    assert result.score == 0.75


def test_skipped_or_empty_suite_has_no_score():
    assert SuiteResult("x").score is None
    assert SuiteResult("x", [Check("a", True)], skipped="no data").score is None


def test_registry_discovers_modules_lazily(monkeypatch):
    module = types.ModuleType("orbit_backend.evalrun.suites.fake_one")
    module.__doc__ = "Fake suite.\n\nMore text."
    module.ID, module.TITLE, module.EV = "fake_one", "Fake", ("EV-12",)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(registry, "ids", lambda: ["fake_one"])
    assert registry.get("fake_one") is module
    assert registry.list_suites() == [{"id": "fake_one", "title": "Fake", "ev": ["EV-12"],
                                       "description": "Fake suite."}]
    with pytest.raises(ValueError):
        registry.get("nope")


def test_real_suites_follow_the_protocol():
    for suite_id in registry.ids():
        module = registry.get(suite_id)
        assert module.ID == suite_id and module.TITLE and module.EV and callable(module.run)
