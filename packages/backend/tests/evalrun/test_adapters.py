import pytest

from tandem_backend.evalrun import registry, runner
from tandem_backend.evalrun.contract import SuiteResult

ADAPTERS = ["pipeline", "probe", "readability", "recommend_replay"]


@pytest.mark.parametrize("suite_id", ADAPTERS)
def test_adapter_returns_passing_checks(suite_id, tmp_path):
    result = runner.run_suite(suite_id, home=tmp_path)
    assert isinstance(result, SuiteResult) and result.suite == suite_id
    if result.skipped:
        pytest.skip(result.skipped)
    assert result.checks and all(c.id.startswith(f"{suite_id}.") for c in result.checks)
    assert all(c.passed for c in result.checks), [c for c in result.checks if not c.passed]
    assert result.score == 1.0


def test_adapters_are_registered_with_ev_ids():
    listed = {s["id"]: s for s in registry.list_suites()}
    for suite_id in ADAPTERS:
        assert listed[suite_id]["ev"] and listed[suite_id]["description"]


def test_replay_skips_without_evals_tree(tmp_path):
    result = runner.run_suite("recommend_replay", params={"replay_path": str(tmp_path / "none.py")})
    assert result.skipped and result.score is None
