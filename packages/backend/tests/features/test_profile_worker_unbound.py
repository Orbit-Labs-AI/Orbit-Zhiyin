"""recommend_inputs profile in the analysis worker (no FeatureService bound)."""

from __future__ import annotations

from orbit_backend import features
from orbit_backend.recommend import section


def test_unbound_worker_builds_profile_readonly(home, seeded, make_service, monkeypatch):
    bound = make_service().profile()  # gateway side materialized sess_feat earlier
    monkeypatch.setattr(features, "_service", None)
    diagnostics: list = []
    body = section._profile(None, diagnostics, home)
    assert diagnostics == []
    assert body["n_sessions"] == bound["n_sessions"] == 3
    assert [t["id"] for t in body["tags"]] == [t["id"] for t in bound["tags"]]


def test_unbound_without_home_reports_diagnostic(monkeypatch):
    monkeypatch.setattr(features, "_service", None)
    diagnostics: list = []
    assert section._profile(None, diagnostics) is None
    assert diagnostics[0]["source"] == "features.profile"
