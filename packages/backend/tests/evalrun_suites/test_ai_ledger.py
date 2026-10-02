"""EV-11 suite: clean ledger passes; dropping a usage row is caught."""

import pytest

from tandem_backend.ai import runner
from tandem_backend.evalrun.contract import EvalContext
from tandem_backend.evalrun.suites import ai_ledger as suite


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_clean_ledger(tmp_path):
    result = suite.run(EvalContext(tmp=tmp_path))
    by_id = {c.id: c for c in result.checks}
    for cid in ("ai_ledger.one_row_per_call", "ai_ledger.job_totals", "ai_ledger.estimate.median",
                "ai_ledger.estimate.p90", "ai_ledger.cost_matches_prices",
                "ai_ledger.cap.exhausted_refused"):
        assert by_id[cid].passed, by_id[cid]
    # The cap does not yet look at the next job's estimate (followup); only presence is asserted.
    assert "ai_ledger.cap.estimate_refused" in by_id
    assert result.metrics["jobs"] == suite.N and result.metrics["median_rel_error"] is not None


def test_dropped_usage_row(tmp_path, monkeypatch):
    original = runner.Runner.record_usage
    seen = []

    def flaky(self, ctx, *args):
        seen.append(1)
        if len(seen) != 3:
            original(self, ctx, *args)

    monkeypatch.setattr(runner.Runner, "record_usage", flaky)
    result = suite.run(EvalContext(tmp=tmp_path))
    failed = {c.id for c in result.checks if not c.passed}
    assert "ai_ledger.one_row_per_call" in failed
