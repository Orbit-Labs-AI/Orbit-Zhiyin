"""EV-13 suite: clean run passes; a revert that writes nothing fails the roundtrip check."""

from tandem_backend.evalrun.contract import EvalContext
from tandem_backend.evalrun.suites import install_roundtrip as suite
from tandem_backend.install import service


def test_clean_matrix_passes(tmp_path):
    result = suite.run(EvalContext(tmp=tmp_path))
    assert result.skipped is None
    failed = [c for c in result.checks if not c.passed]
    assert not failed, failed
    ids = {c.id for c in result.checks}
    assert "install.rule.claude_code.roundtrip" in ids
    assert "install.mcp.codex.edit_refused" in ids
    assert "install.real_home_untouched" in ids
    assert result.metrics["cells"] == 10


def test_broken_revert_is_caught(tmp_path, monkeypatch):
    def fake_revert(records, **_kw):
        return [{"idx": r["idx"], "path": r["path"], "status": "reverted"} for r in records]

    monkeypatch.setattr(service.applier, "revert_records", fake_revert)
    result = suite.run(EvalContext(tmp=tmp_path))
    failed = {c.id for c in result.checks if not c.passed}
    assert "install.rule.claude_code.roundtrip" in failed


def test_real_flag_adds_no_always_true_check(tmp_path):
    result = suite.run(EvalContext(tmp=tmp_path, real=True))
    assert not [c for c in result.checks if c.id == "install.real_smoke"]
    assert result.metrics["real_smoke"] == "not_implemented"
