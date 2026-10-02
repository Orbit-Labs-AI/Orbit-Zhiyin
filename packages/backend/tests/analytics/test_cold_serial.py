"""Serial cold-path helpers: exact Spearman without scipy, tree lookups, load-aware workers."""

import random

from scipy.stats import spearmanr

from tandem_backend.analytics import service
from tandem_backend.analytics.context import AnalysisContext
from tandem_backend.analytics.inputs import AnalysisInputBundle, Scope
from tandem_backend.analytics.products.statistics import spearman_rho


def test_spearman_rho_matches_scipy_bit_for_bit():
    rng = random.Random(3)
    for _ in range(300):
        n, k = rng.randint(5, 120), rng.choice([3, 10, 1000])
        a = [rng.choice([rng.randint(0, k), rng.random() * k]) for _ in range(n)]
        b = [rng.randint(0, k) for _ in range(n)]
        if len(set(a)) < 2 or len(set(b)) < 2:
            continue
        assert spearman_rho(a, b) == float(spearmanr(a, b).statistic)


def test_tree_lookups_keep_global_order():
    sessions = [
        {"session_uid": "b", "kind": "main"},
        {"session_uid": "a", "kind": "subagent", "root_uid": "b"},
        {"session_uid": "c", "kind": "main"},
    ]
    context_events = [
        {"session_uid": sid, "event_uid": f"{sid}{i}"} for i, sid in enumerate("acbac")
    ]
    bundle = AnalysisInputBundle(sessions, [], None, None, {})
    context = AnalysisContext(
        bundle, Scope(), sessions, [], None, None, {"context_events": context_events}
    )
    for ids in ({"a", "b"}, {"c"}, {"a", "b", "c"}, {"x"}):
        assert context.tree_context_events(ids) == [
            e for e in context_events if e["session_uid"] in ids
        ]
        assert context.tree_sessions(ids) == [s for s in sessions if s["session_uid"] in ids]


def test_busy_machine_runs_serially(monkeypatch):
    monkeypatch.delenv("TANDEM_ANALYSIS_WORKERS", raising=False)
    monkeypatch.setattr(service.os, "cpu_count", lambda: 14)
    monkeypatch.setattr(service.os, "getloadavg", lambda: (15.2, 14.0, 13.0))
    assert service._max_workers() == 1
    assert not service._wants_parallel(2500, None)
    monkeypatch.setattr(service.os, "getloadavg", lambda: (3.4, 3.0, 3.0))
    # 10 idle cores, capped for memory (each worker holds its chunk next to the parent).
    assert service._max_workers() == service.DEFAULT_MAX_WORKERS
    assert service._wants_parallel(2500, None)
    assert not service._wants_parallel(10, None)
    monkeypatch.setenv("TANDEM_ANALYSIS_WORKERS", "1")
    assert not service._wants_parallel(2500, None)
