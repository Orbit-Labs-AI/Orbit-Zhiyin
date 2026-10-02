"""First-open fast path: 7 days first, wider windows queued behind (synthetic, no worker)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tandem_backend.services import fastpath
from tandem_backend.services.auth import ApiError
from tandem_backend.services.gateway import Revisions
from tandem_backend.services.routes_analytics import analytics_scope
from tandem_backend.services.sections import rules_digest
from tandem_backend.services.snapshots import SnapshotKey, SnapshotStore, scope_hash

NOW = datetime(2026, 10, 3, 15, 30, tzinfo=UTC)


def fake_gateway():
    submitted = []

    class Analysis:
        def __init__(self):
            self.tasks = {}

        def submit(self, name, scope, params, h, priority, rev, rules):
            task = SimpleNamespace(id=f"t{len(submitted)}", status="queued")
            submitted.append((name, scope["from_ts"], priority))
            self.tasks[(name, h, *rev, rules)] = task
            return task

        def failure(self, *args):
            return None

    revisions = Revisions()
    revisions.update(data_rev=3, inventory_rev=0)
    gw = SimpleNamespace(revisions=revisions, snapshots=SnapshotStore(None),
                         supervisor=SimpleNamespace(analysis=Analysis()))
    return gw, submitted


def put(gw, section, scope, rev=3):
    key = SnapshotKey(section, scope_hash(scope, {}), rev, 0, rules_digest())
    gw.snapshots.put(key, {"ok": True})


def test_window_starts_at_a_utc_day_boundary():
    assert fastpath.window_start(0, NOW) is None
    assert fastpath.window_start(1, NOW) == int(datetime(2026, 10, 3, tzinfo=UTC).timestamp()
                                                 * 1000)
    assert fastpath.window_start(7, NOW) == int(datetime(2026, 9, 27, tzinfo=UTC).timestamp()
                                                 * 1000)


def test_cold_auto_serves_seven_days_and_queues_wider_windows_after_it():
    gw, submitted = fake_gateway()
    base = asdict(analytics_scope())
    scope, window = fastpath.choose(gw, "uiview_facts", base, None)
    assert window["days"] == 7 and window["requested"] == "auto"
    assert scope["from_ts"] == fastpath.window_start(7)
    assert [w["days"] for w in window["wider"]] == [30, 0]
    assert window["wider"][1]["scope_hash"] == scope_hash(fastpath.windowed(base, 0), {})
    assert submitted == []  # nothing queued before the caller submits the 7-day window
    fastpath.follow_up(gw, "uiview_facts", base, window)
    seven = fastpath.window_start(7)
    assert submitted == [*((name, seven, "prewarm") for name in fastpath.FIRST_SCREEN),
                         ("uiview_facts", fastpath.window_start(30), "prewarm"),
                         ("uiview_facts", None, "prewarm")]
    assert [w["state"] for w in window["wider"]] == ["queued", "queued"]


def test_wider_overview_windows_queue_the_full_pass_first():
    gw, submitted = fake_gateway()
    base = asdict(analytics_scope())
    _, window = fastpath.choose(gw, "overview", base, None)
    fastpath.follow_up(gw, "overview", base, window)
    assert [s[0] for s in submitted] == [
        "sessions", "tools", "projects", "instruction",  # the served 7-day window first
        "uiview_facts", "uiview_facts", "overview", "overview"]
    assert {s[1] for s in submitted[:4]} == {fastpath.window_start(7)}


def test_auto_prefers_the_widest_ready_window_then_stale():
    gw, _ = fake_gateway()
    base = asdict(analytics_scope())
    put(gw, "overview", fastpath.windowed(base, 30))
    scope, window = fastpath.choose(gw, "overview", base, None)
    assert window["days"] == 30 and [w["days"] for w in window["wider"]] == [0]
    put(gw, "overview", fastpath.windowed(base, 0), rev=2)  # older revision: stale
    scope, window = fastpath.choose(gw, "overview", base, None)
    assert window["days"] == 30  # a fresh 30-day result beats a stale all-time one
    put(gw, "overview", fastpath.windowed(base, 0))
    scope, window = fastpath.choose(gw, "overview", base, None)
    assert window == {"days": 0, "requested": "auto", "wider": []}
    assert scope["from_ts"] is None


def test_explicit_days_and_validation():
    gw, submitted = fake_gateway()
    base = asdict(analytics_scope())
    scope, window = fastpath.choose(gw, "overview", base, 30)
    assert scope["from_ts"] == fastpath.window_start(30) and window["wider"] == []
    assert analytics_scope(days=7).from_ts == fastpath.window_start(7)
    assert analytics_scope(days=0).from_ts is None
    with pytest.raises(ApiError):
        analytics_scope(days=5)
    with pytest.raises(ApiError):
        analytics_scope(days=7, from_ts=1)


def test_cold_auto_skips_empty_small_windows():
    from contextlib import contextmanager

    gw, _ = fake_gateway()
    newest = {"ts": fastpath.window_start(30) + 1}  # last event 3 weeks ago

    class Reads:
        @contextmanager
        def read(self, check=True):
            class DB:
                def execute(self, sql, params=()):
                    if "DISTINCT kind" in sql:
                        return iter([("message.user",)])
                    return SimpleNamespace(fetchone=lambda: (1,) if params[1] <= newest["ts"]
                                           else None)
            yield DB()

    gw.reads = Reads()
    base = asdict(analytics_scope())
    _, window = fastpath.choose(gw, "uiview_facts", base, None)
    assert window["days"] == 30 and [w["days"] for w in window["wider"]] == [0]
    newest["ts"] = 0  # nothing within 30 days either
    _, window = fastpath.choose(gw, "uiview_facts", base, None)
    assert window["days"] == 0 and window["wider"] == []
