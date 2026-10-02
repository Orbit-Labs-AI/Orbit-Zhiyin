"""EV-07 tracking and outcomes on synthetic session_days; EV-05 funnel."""

from __future__ import annotations

import pytest

from tandem_backend.appdb import AppDB
from tandem_backend.recommend import outcomes, store

DAY = store.DAY
INSTALLED = 1_800_000_000_000


@pytest.fixture
def db(tmp_path):
    appdb = AppDB(tmp_path / "app.db")
    yield appdb
    appdb.close()


def seed(db, kind="hook", track=None, problem_type="tool_env_failure"):
    card = {"rec_key": "kb:retry", "kind": kind, "dim": "hook", "title": "t", "rank": 1,
            "gates": {"passed": True}, "score": {"priority": 50},
            "problem": {"type": problem_type, "key": f"{problem_type}:x"},
            "track": track or {"follow_days": 7, "extend_days": 28}}
    with db.write() as conn:
        store.insert_run(conn, {"run_id": "r1", "scope_hash": "s", "scope": {},
                                "inputs_digest": "d", "engine_version": "t", "status": "ready",
                                "created_at": INSTALLED - DAY}, [card])
    return store.candidate_id("r1", "kb:retry")


def days(before_rate, after_rate, n_before=20, n_after=20, failures_after=0):
    rows = []
    for i in range(n_before):
        hit = i < round(before_rate * n_before)
        rows.append({"session_uid": f"b{i}", "started_at": INSTALLED - (i + 1) * DAY // 2,
                     "problems": ["tool_env_failure"] if hit else [], "readonly_prompts": 0,
                     "tool_failures": 1, "tokens": 100})
    for i in range(n_after):
        hit = i < round(after_rate * n_after)
        rows.append({"session_uid": f"a{i}", "started_at": INSTALLED + i * DAY // 4,
                     "problems": ["tool_env_failure"] if hit else [], "readonly_prompts": 0,
                     "tool_failures": 1 + failures_after * (i % 2 + 1), "tokens": 100})
    return rows


def tracking(db, cid):
    tid = outcomes.register_tracking(db, "inst1", cid, INSTALLED)
    with db.read() as conn:
        return tid, dict(conn.execute("SELECT * FROM tracking").fetchone())


def test_wilson_and_newcombe_reference_values():
    # Newcombe (1998) worked examples.
    lo, hi = outcomes.wilson(81, 263)
    assert (round(lo, 4), round(hi, 4)) == (0.2553, 0.3662)
    d, lo, hi = outcomes.newcombe(56, 70, 48, 80)
    assert (round(d, 4), round(lo, 4), round(hi, 4)) == (0.2, 0.0524, 0.3339)
    d, lo, hi = outcomes.welch([1, 2, 3], [2, 3, 4, 5])
    assert d == pytest.approx(-1.5) and lo < d < hi


def test_register_tracking_defaults_pin_and_state(db):
    cid = seed(db)
    tid, row = tracking(db, cid)
    assert outcomes.register_tracking(db, "inst1", cid, INSTALLED) == tid  # idempotent
    assert row["baseline_from"] == INSTALLED - 28 * DAY and row["baseline_to"] == INSTALLED
    metrics = [m["metric"] for m in outcomes._json(row["metrics"], [])]
    assert metrics == ["problem_session_rate:tool_env_failure", "tool_failures_per_session"]
    with db.read() as conn:
        assert store.get_run(conn, "r1")["pinned"] == 1
        state = store.states(conn)["kb:retry"]
    assert state["status"] == "installed" and state["install_id"] == "inst1"
    with pytest.raises(KeyError):
        outcomes.register_tracking(db, "inst2", "missing", INSTALLED)


def test_permission_rule_uses_readonly_metric(db):
    cid = seed(db, kind="permission_rule", track={"mechanical": "readonly_prompts_per_session",
                                                  "guardrail": ["unknown_metric"]})
    _, row = tracking(db, cid)
    metrics = outcomes._json(row["metrics"], [])
    assert metrics[0] == {"metric": "readonly_prompts_per_session", "layer": "mechanical",
                          "direction": "down"}
    assert metrics[-1]["metric"] == "tool_failures_per_session"


@pytest.mark.parametrize(("rows", "now_days", "expected"), [
    (days(0.8, 0.1), 30, "positive"),
    (days(0.3, 0.3), 30, "neutral"),
    (days(0.8, 0.1, n_before=3), 30, "insufficient"),
    (days(0.3, 0.3, failures_after=2), 30, "negative"),
    (days(0.8, 0.1), 3, "tracking"),
])
def test_effect_status(db, rows, now_days, expected):
    _, row = tracking(db, seed(db))
    now = INSTALLED + now_days * DAY
    result = outcomes.compute(row, rows, now)
    assert outcomes.effect_status(row, result, now) == expected
    if expected == "tracking":
        assert result == []
    if expected == "negative":
        assert any(r["status"] == "guardrail_hit" for r in result)


def test_only_elapsed_windows(db):
    _, row = tracking(db, seed(db))
    result = outcomes.compute(row, days(0.8, 0.1), INSTALLED + 10 * DAY)
    assert {r["window"] for r in result} == {"7d"}


def test_refresh_writes_outcomes_and_scope_too_short(db):
    cid = seed(db)
    tracking(db, cid)
    now = INSTALLED + 30 * DAY
    inputs = {"sessions": {"first_ts": INSTALLED - 40 * DAY},
              "facts": {"session_days": days(0.8, 0.1)}, "scope": {}}
    with db.write() as conn:
        assert outcomes.refresh(conn, inputs, now) == 1
        result = outcomes.outcome(conn, "inst1")
    assert result["effect_status"] == "positive"
    assert [w["window"] for w in result["windows"]] == ["7d", "28d"]
    short = {**inputs, "sessions": {"first_ts": INSTALLED - DAY}}
    with db.write() as conn:
        outcomes.refresh(conn, short, now)
        result = outcomes.outcome(conn, "inst1")
    assert result["effect_status"] == "insufficient"
    assert result["confounders"] == ["scope_too_short"]


def test_revert_and_ev05_funnel(db):
    cid = seed(db)
    with db.write() as conn:
        store.record_exposure(conn, cid, "A7", 0, "view", INSTALLED - 10)
        store.record_exposure(conn, cid, "A7", 0, "preview", INSTALLED - 5)
        store.record_exposure(conn, cid, "A7", 0, "install", INSTALLED - 1)
    tracking(db, cid)
    assert outcomes.mark_reverted(db, "inst1", INSTALLED + DAY)
    assert not outcomes.mark_reverted(db, "nope", INSTALLED)
    with db.read() as conn:
        rows = outcomes.metrics_ev05(conn, now=INSTALLED + 2 * DAY)
        memory = store.memory(conn, INSTALLED + 2 * DAY)
        assert outcomes.outcome(conn, "inst1")["effect_status"] == "reverted"
    assert rows == [{"group": "kb:retry", "surface": "A7", "shown": 1, "opened": 1,
                     "installed": 1, "not_applicable": 0, "reverted": 1, "adoption_rate": 1.0,
                     "na_rate": 0.0, "revert_rate": 1.0}]
    assert memory["posteriors"]["kb:retry"]["beta"] == 2
    assert memory["state"]["kb:retry"]["status"] == "not_applicable"
