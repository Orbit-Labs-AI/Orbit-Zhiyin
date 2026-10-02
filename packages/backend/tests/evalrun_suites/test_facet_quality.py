"""EV-04.1 suite: scripted facets pass; a gate that accepts anything stores foreign evidence."""

import pytest

from tandem_backend.ai import tasks_analysis
from tandem_backend.evalrun.contract import EvalContext
from tandem_backend.evalrun.suites import facet_quality as suite


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_clean_facets(tmp_path):
    result = suite.run(EvalContext(tmp=tmp_path))
    failed = [c for c in result.checks if not c.passed]
    assert not failed, failed
    assert result.metrics["validity"] == 1.0 and result.metrics["hallucination_rate"] == 0.0
    assert {"facet.repeat_cached", "facet.broken.wrong_enum"} <= {c.id for c in result.checks}


def test_gate_disabled_stores_foreign_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks_analysis, "check_facet", lambda item, payload: (item, []))
    result = suite.run(EvalContext(tmp=tmp_path))
    failed = {c.id for c in result.checks if not c.passed}
    assert "facet.broken.foreign_evidence" in failed
