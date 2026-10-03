"""HUD / menu-bar / widget context share == session-detail ctx curve (analytics2 review).

Both surfaces pick the window through ``context_windows.resolve`` (reported > override >
table) and treat a prompt above the window as unknown via ``context_windows.usage_ratio``.
Token totals do not appear on the three realtime surfaces, so only context is compared.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC

from realtime_fixtures import NOW, Reads

from orbit_backend.realtime import classify
from orbit_backend.realtime.tail import load_tails
from orbit_backend.uiview import trajectory


def _both(orbit, uid, overrides=None):
    tail = next(t for t in load_tails(Reads(orbit.path), NOW) if t.session_uid == uid)
    rt = classify.context(tail, overrides)
    db = sqlite3.connect(orbit.path)
    try:
        body = trajectory.build_detail(db, uid, overrides=overrides, tz=UTC)
    finally:
        db.close()
    return rt, body


def test_codex_reported_window_is_used_on_both_surfaces(orbit):
    orbit.session("cx", agent="codex", started=NOW - 120_000)
    orbit.event("cx", NOW - 110_000, kind="message.user", actor="human", text="go")
    orbit.event("cx", NOW - 100_000, kind="turn.start", actor="system")
    orbit.db.execute("UPDATE event SET ext=? WHERE session_uid='cx' AND kind='turn.start'",
                     ('{"model_context_window": 258400}',))
    orbit.usage("cx", NOW - 90_000, 50_000, model="gpt-5-codex")
    orbit.usage("cx", NOW - 30_000, 100_000, cache_read=29_200, model="gpt-5-codex")
    for overrides in (None, {"gpt-5": 123_456_789}):  # the reported window beats an override
        rt, body = _both(orbit, "cx", overrides)
        assert rt["window_basis"] == "reported" and rt["window_tokens"] == 258_400
        ctx = body["trajectory"]["ctx"]
        assert ctx[-1][1] == round(rt["ratio"] * 100, 1) == 50.0  # not /272k from the table
        assert body["stats7"]["ctx_peak"] == 50.0


def test_usage_above_the_window_is_unknown_on_both_surfaces(orbit):
    orbit.session("big", started=NOW - 120_000)
    orbit.event("big", NOW - 110_000, kind="message.user", actor="human", text="go")
    orbit.usage("big", NOW - 30_000, 600_000)  # a 1M run the 200k table row cannot describe
    rt, body = _both(orbit, "big")
    assert rt["ratio"] is None and rt["basis"] == "window_exceeded"
    assert body["trajectory"]["ctx"] is None  # never capped to 100%
    assert body["stats7"]["ctx_peak"] is None


def test_table_window_matches_at_the_last_point(orbit):
    orbit.session("cc", started=NOW - 120_000)
    orbit.event("cc", NOW - 110_000, kind="message.user", actor="human", text="go")
    orbit.usage("cc", NOW - 60_000, 20_000)
    orbit.usage("cc", NOW - 30_000, 1_000, cache_read=149_000)
    rt, body = _both(orbit, "cc")
    assert rt["window_basis"] == "table"
    assert body["trajectory"]["ctx"][-1][1] == round(rt["ratio"] * 100, 1) == 75.0
