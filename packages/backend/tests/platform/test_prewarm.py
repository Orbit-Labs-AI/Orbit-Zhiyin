"""Prewarm queues recommend_inputs for the scope /v1/recommendations uses by default."""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

from tandem_backend.services.gateway import Gateway, Revisions
from tandem_backend.services.routes_analytics import analytics_scope
from tandem_backend.services.snapshots import scope_hash


def fake(heavy: bool):
    submitted = []

    def submit(name, scope, params, h, priority, rev, rules):
        submitted.append((name, h))
        return SimpleNamespace(id=f"t{len(submitted)}")

    revisions = Revisions()
    revisions.update(data_rev=1, inventory_rev=0)
    gw = SimpleNamespace(
        revisions=revisions, stopping=SimpleNamespace(is_set=lambda: False), prewarm_mru=0,
        prewarm_heavy=heavy, snapshots=SimpleNamespace(get=lambda key: None),
        state=SimpleNamespace(snapshot=lambda: {"settings": {}, "mru_scopes": []}),
        supervisor=SimpleNamespace(analysis=SimpleNamespace(submit=submit)))
    return gw, submitted


def test_prewarm_adds_recommend_inputs_on_heavy_pass():
    rec = ("recommend_inputs", scope_hash(asdict(analytics_scope()), {}))
    gw, submitted = fake(heavy=False)
    Gateway.prewarm(gw)
    assert rec not in submitted
    gw, submitted = fake(heavy=True)
    Gateway.prewarm(gw)
    assert submitted[-1] == rec
