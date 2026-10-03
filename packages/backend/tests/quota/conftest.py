"""Synthetic tandem.db (reuses the sessionops builder) + gateway under tmp_path."""

from __future__ import annotations

import sqlite3

import pytest
from sessionops.conftest import Tandem, client, gateway, home  # noqa: F401

NOW = 1_760_000_000_000
HOUR = 3_600_000
DAY = 24 * HOUR


class QuotaTandem(Tandem):
    def model_call(self, session_uid, *, ts, model="claude-sonnet-4-5", inp=100, out=50,
                   cache_read=0, cache_write=0, reasoning=0, cost=None):
        event = self.event(session_uid, ts=ts, kind="model.usage", attrs={
            "usage_scope": "call", "measurement": "delta", "request_key": []})
        self.db.execute(
            "INSERT INTO model_call(call_uid, session_uid, usage_event_uid, model_raw, model_id, "
            "model_resolution, coverage, input_tokens, cache_read_tokens, cache_write_tokens, "
            "output_tokens, reasoning_tokens, cost_usd, ts) "
            "VALUES (?, ?, ?, ?, ?, 'exact', 'self', ?, ?, ?, ?, ?, ?, ?)",
            (f"m-{event}", session_uid, event, model, model, inp, cache_read, cache_write, out,
             reasoning, cost, ts))

    def limits(self, session_uid, *, ts, windows):
        return self.event(session_uid, ts=ts, kind="ui.state",
                          attrs={"state_kind": "rate_limits", "snapshot": windows})

    def connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db


@pytest.fixture
def tandem(home, tmp_path):  # noqa: F811
    t = QuotaTandem(home, tmp_path / "agents")
    t.db_path = home / "tandem.db"
    yield t
    t.db.close()


@pytest.fixture(autouse=True)
def _reset_exclusion_provider():
    """Every gateway registers the process-wide exclusion provider; exclusion.merged is
    fail-closed, so a provider left over from an earlier test's closed app.db must not leak."""
    from tandem_backend.sessionops import exclusion

    exclusion.set_provider(None)
    yield
    exclusion.set_provider(None)
