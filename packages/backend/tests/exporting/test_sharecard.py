"""Share-card gate (EXP-04), copy lookup and hide_numbers; snapshot storage and pruning."""

from __future__ import annotations

import pytest

from tandem_backend.exporting import report, sharecard, snapshots
from tandem_backend.exporting.type_copy import TYPES, copy_for

OVERVIEW = {"overview": {"counts": {"main_sessions": 42}, "activity_rhythm": {"active_days": 10}}}


def profile(code="DPMV", n=30):
    return {"axes": {f"axis{i}": {"direction": None if ch == "?" else ch, "effective_task_n": n}
                     for i, ch in enumerate(code)},
            "headline": "h", "coverage": {"task_n": 50}}


@pytest.fixture
def canned(monkeypatch):
    state = {"profile": profile(), "overview": OVERVIEW}
    monkeypatch.setattr(sharecard, "persona_profile", lambda bodies: state["profile"])

    def fetch(gw, names, scope_dict, wait_ms=3000):
        return ({n: (state["overview"] if n == "overview" else {}, "fresh") for n in names},
                "h" * 32)

    monkeypatch.setattr(report, "fetch_sections", fetch)
    return state


def card(client, **body):
    response = client.post("/v1/export/share_card", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_eligible_card_with_copy_and_snapshot(env, canned):
    client, _, _ = env
    body = card(client, theme="dark")
    assert body["eligible"] and body["blocked_reason"] is None and body["code"] == "DPMV"
    assert body["type_name"] == TYPES["DPMV"][0] == "总设计师"
    assert body["copy"]["headline"] == "先把规格写清楚，再让每个 Agent 各司其职。"
    assert body["disclaimer"] == "实验性画像，仅供参考" and body["theme"] == "dark"
    assert body["gate"]["min_units"] == 30 and body["gate"]["active_days"] == 10
    assert {s["label"]: s["value"] for s in body["stats"]} == {"会话": 42, "活跃天数": 10, "任务": 50}
    items = client.get("/v1/export/snapshots", params={"kind": "share_card"}).json()["items"]
    assert [i["snapshot_id"] for i in items] == [body["snapshot_id"]]
    assert items[0]["summary"] == "DPMV 总设计师"
    assert "snapshot_id" not in card(client, save=False)


@pytest.mark.parametrize(("code", "n", "days", "reason"), [
    ("DPMV", 29, 10, "insufficient_data"), ("DPMV", 30, 9, "insufficient_data"),
    ("DPMV", 30, 10, None), ("DP?V", 30, 10, "unsettled_code"),
    ("DP?V", 29, 10, "insufficient_data")])
def test_gate_boundaries(env, canned, code, n, days, reason):
    client, _, _ = env
    canned["profile"] = profile(code, n)
    canned["overview"] = {"overview": {"counts": {}, "activity_rhythm": {"active_days": days}}}
    body = card(client)
    assert body["blocked_reason"] == reason and body["eligible"] is (reason is None)
    if reason:
        assert body["code"] is None and body["copy"] is None and body["stats"] == []
        assert "snapshot_id" not in body
    assert [a["n_units"] for a in body["gate"]["axes"]] == [n] * 4


def test_persona_unavailable_and_unknown_code(env, canned):
    client, _, _ = env
    canned["profile"] = None
    assert card(client)["blocked_reason"] == "persona_unavailable"
    canned["profile"] = profile("CEAS")
    body = card(client)
    assert body["eligible"] and body["code"] == "CEAS"
    assert body["type_name"] is None and body["copy"] is None
    assert copy_for("CEAS") == (None, None)


def test_hide_numbers(env, canned):
    client, _, _ = env
    stats = card(client, hide_numbers=True)["stats"]
    assert stats and all(s["hidden"] and s["value"] is None for s in stats)


def test_real_profile_from_empty_sections_is_gated():
    bodies = {"tasks": {"scope": {"display_timezone": "UTC"}, "tasks": {"records": []},
                        "coverage": {}},
              "instruction": {"instruction": {"records": []}},
              "preferences": {"preferences": {"records": []}}, "overview": OVERVIEW}
    result = sharecard.payload(bodies)
    assert result["blocked_reason"] == "insufficient_data"
    assert [a["n_units"] for a in result["gate"]["axes"]] == [0, 0, 0, 0]
    assert sharecard.payload({**bodies, "tasks": None})["blocked_reason"] == "persona_unavailable"


def test_snapshot_crud_and_prune(env):
    client, gw, _ = env
    ids = [snapshots.save(gw.appdb, "report", {}, "h", {"sections": []}, now_ms=i)
           for i in range(55)]
    other = snapshots.save(gw.appdb, "share_card", {}, "h", {"code": "X"}, now_ms=1)
    listed = client.get("/v1/export/snapshots", params={"kind": "report", "limit": 100}).json()
    assert [i["snapshot_id"] for i in listed["items"]] == ids[::-1][:50]
    assert client.get(f"/v1/export/snapshots/{ids[0]}").status_code == 404
    assert client.get(f"/v1/export/snapshots/{other}").json()["payload"] == {"code": "X"}
    assert client.delete(f"/v1/export/snapshots/{other}").json() == {"ok": True}
    assert client.delete(f"/v1/export/snapshots/{other}").status_code == 404
    assert client.get("/v1/export/snapshots", params={"kind": "nope"}).status_code == 422
    assert len(client.get("/v1/export/snapshots").json()["items"]) == 20
