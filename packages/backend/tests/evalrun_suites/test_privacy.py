"""EV-14 suite: redacted classes stay hidden; a disabled redactor leaks and is flagged."""

from orbit_backend.ai import redact
from orbit_backend.evalrun.contract import EvalContext
from orbit_backend.evalrun.suites import privacy as suite

# Classes the current redactor covers. aws_key / ssh_key are reported gaps (see followups).
COVERED = ("api_key", "bearer", "email", "home_path", "url_auth")


def test_clean_pack(tmp_path):
    result = suite.run(EvalContext(tmp=tmp_path))
    by_id = {c.id: c for c in result.checks}
    for cls in COVERED:
        assert by_id[f"privacy.leak.{cls}"].passed, by_id[f"privacy.leak.{cls}"]
    for cid in ("privacy.token_total", "privacy.disabled_item_excluded", "privacy.digest_stable"):
        assert by_id[cid].passed, by_id[cid]
    assert {"privacy.leak.aws_key", "privacy.leak.ssh_key"} <= set(by_id)
    assert result.metrics["planted"] > 0 and result.metrics["hits"] > 0


def test_disabled_redactor_leaks(tmp_path, monkeypatch):
    monkeypatch.setattr(redact, "redact2", lambda text, **_kw: (text, 0))
    result = suite.run(EvalContext(tmp=tmp_path))
    failed = {c.id for c in result.checks if not c.passed}
    assert {"privacy.leak.api_key", "privacy.redaction_hits"} <= failed
    assert result.metrics["leaked"] > 0
