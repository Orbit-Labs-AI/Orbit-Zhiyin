from datetime import UTC

import pytest

from tandem_backend.uiview import compare, sessions, trajectory

from .l1_builder import *  # noqa: F403 - pytest fixtures
from .l1_builder import DAY, MIN, T0, codex_unknown, handwritten_cc


def smooth(l1, uid="cc-ok", started=T0 + DAY):
    l1.session(uid, started=started, title="小改动")
    l1.user(uid, started, "把按钮改成蓝色")
    l1.reply(uid, started + MIN)
    l1.call(uid, started + 2 * MIN, name="Edit", kind="file.edit")
    l1.call(uid, started + 3 * MIN, head="pnpm test", status="success")
    l1.reply(uid, started + 4 * MIN, final=True)
    return uid


def test_table_matches_hand_computation(l1):
    a, b = handwritten_cc(l1), smooth(l1)
    da = trajectory.build_detail(l1.db, a, tz=UTC)
    db_ = trajectory.build_detail(l1.db, b, tz=UTC)
    body = compare.compare(da, db_)
    table = {r["metric"]: r for r in body["table"]}
    # A: 12 min, 3 msgs, 8 tools, 3 errors, 2 corr, steps 10 -> auto 3.33
    # B: 4 min, 1 msg, 2 tools, 0 errors, 0 corr, steps 2 tools + 2 reply spans -> auto 4
    assert table["dur"] == {"metric": "dur", "label": "时长", "a": 12.0, "b": 4.0,
                            "delta": -8.0, "pct": -67, "better": "b"}
    assert table["errors"]["delta"] == -3 and table["errors"]["pct"] == -100
    assert table["errors"]["better"] == "b"
    assert table["corr"]["better"] == "b" and table["corr"]["delta"] == -2
    assert table["msgs"]["delta"] == -2 and table["msgs"]["better"] is None
    assert table["tools"]["pct"] == -75 and table["tools"]["better"] is None
    assert table["auto"]["a"] == 3.33 and table["auto"]["b"] == 4.0
    assert table["auto"]["delta"] == 0.67 and table["auto"]["better"] is None
    assert body["T"] == 12.0 and body["a"]["T"] == 12.0 and body["b"]["T"] == 4.0
    for side in ("a", "b"):
        assert 98 <= sum(p["pct"] for p in body["phase_pct"][side]) <= 102
    reverse = {r["metric"]: r for r in compare.compare(db_, da)["table"]}
    assert reverse["dur"]["better"] == "a" and reverse["dur"]["delta"] == 8.0


def test_unknown_metric_has_no_direction(l1):
    handwritten_cc(l1)
    codex_unknown(l1)
    body = compare.compare(trajectory.build_detail(l1.db, "cc-fix", tz=UTC),
                           trajectory.build_detail(l1.db, "cx-1", tz=UTC))
    errors = next(r for r in body["table"] if r["metric"] == "errors")
    assert errors["b"] is None and errors["delta"] is None and errors["better"] is None


def test_same_session_rejected(l1):
    handwritten_cc(l1)
    d = trajectory.build_detail(l1.db, "cc-fix", tz=UTC)
    with pytest.raises(compare.SameSession):
        compare.compare(d, d)


def test_routes_compare_and_suggest_b(client, l1):
    handwritten_cc(l1)
    smooth(l1, "p1-new", started=T0 + DAY)
    smooth(l1, "p1-old", started=T0 - 2 * DAY)
    codex_unknown(l1)
    assert client.get("/v1/uiview/sessions/compare?a=cc-fix&b=cc-fix").status_code == 422
    body = client.get("/v1/uiview/sessions/compare?a=cc-fix&b=p1-old").json()
    assert body["a"]["id"] == "cc-fix" and body["b"]["id"] == "p1-old"
    assert {"table", "phase_pct", "T"} <= body.keys()
    assert client.get("/v1/uiview/sessions/compare?a=cc-fix&b=zzz").status_code == 404
    # Most recent earlier session of the same project; fall back to a later one.
    assert client.get("/v1/uiview/sessions/cc-fix/suggest_b").json()["b"] == "p1-old"
    assert client.get("/v1/uiview/sessions/p1-old/suggest_b").json()["b"] == "p1-new"
    assert client.get("/v1/uiview/sessions/cx-1/suggest_b").json()["b"] is None
    assert client.get("/v1/uiview/sessions/zzz/suggest_b").status_code == 404


def test_suggest_b_pure():
    rows = [{"id": "x", "p": "p", "started_at": 3}, {"id": "y", "p": "q", "started_at": 2},
            {"id": "z", "p": "p", "started_at": 1}]
    assert compare.suggest_b(rows, "x") == "z"
    assert compare.suggest_b(rows, "z") == "x"
    assert compare.suggest_b(rows, "y") is None
    assert sessions.agent_name("codex") == "Codex"
