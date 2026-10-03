"""Share-card gate (EXP-04) over the A2 persona payload, copy lookup and hide_numbers;
snapshot storage and pruning."""

from __future__ import annotations

import pytest

from tandem_backend.exporting import snapshots
from tandem_backend.exporting.type_copy import TYPES, copy_for
from tandem_backend.uiview import fetch


def page(code="DPMV", n=30, days=10, units=30, ok=True):
    axes = [{"k": k, "value": 70.0, "letter": ch, "left": "l", "right": "r",
             "n_units": units, "state": "settled" if units else "no_data"}
            for k, ch in zip("DIMV", code, strict=True)]
    return {"meta": {"period": "30", "method": "uiview-persona-v0", "scope_hash": "h" * 32},
            "ok": ok and n >= 1, "n": n, "days": days, "code": code, "zh": "页面类型",
            "axes": axes}


@pytest.fixture
def canned(monkeypatch):
    state = {"page": page(), "freshness": "fresh", "calls": []}

    def persona_page(gw, scope, params, today, wait_ms=0):
        state["calls"].append(params)
        return state["page"], state["freshness"], None

    monkeypatch.setattr(fetch, "persona_page", persona_page)
    return state


def card(client, **body):
    response = client.post("/v1/export/share_card", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_eligible_card_with_copy_and_snapshot(env, canned):
    client, _, _ = env
    body = card(client, theme="dark", agents=["codex"], period="90")
    assert canned["calls"][-1] == {"period": "90", "agents": ["codex"], "project": None,
                                   "vs": None}
    assert body["eligible"] and body["blocked_reason"] is None and body["code"] == "DPMV"
    assert body["type_name"] == TYPES["DPMV"][0] == "总设计师"
    assert body["copy"]["headline"] == "先把规格写清楚，再让每个 Agent 各司其职。"
    assert body["disclaimer"] == "实验性画像，仅供参考" and body["theme"] == "dark"
    assert body["gate"]["min_sessions"] == 1 and body["gate"]["active_days"] == 10
    assert body["method"] == "uiview-persona-v0" and [a["k"] for a in body["axes"]] == list("DIMV")
    assert {s["label"]: s["value"] for s in body["stats"]} == {"会话": 30, "活跃天数": 10,
                                                              "对话轮次": 30}
    items = client.get("/v1/export/snapshots", params={"kind": "share_card"}).json()["items"]
    assert [i["snapshot_id"] for i in items] == [body["snapshot_id"]]
    assert items[0]["summary"] == "DPMV 总设计师"
    assert "snapshot_id" not in card(client, save=False)


@pytest.mark.parametrize(("code", "n", "days", "units", "reason"), [
    ("DPMV", 0, 0, 0, "insufficient_data"), ("DPMV", 1, 1, 1, None),
    ("DPMV", 1, 1, 0, None), ("DPMV", 30, 10, 30, None),
    ("DP?V", 30, 10, 30, "unsettled_code")])
def test_gate_boundaries(env, canned, code, n, days, units, reason):
    client, _, _ = env
    canned["page"] = page(code, n, days, units)
    body = card(client)
    assert body["blocked_reason"] == reason and body["eligible"] is (reason is None)
    if reason:
        assert body["code"] is None and body["copy"] is None and body["stats"] == []
        assert body["axes"] == [] and "snapshot_id" not in body
    assert [a["n_units"] for a in body["gate"]["axes"]] == [units] * 4


def test_persona_unavailable_computing_and_unknown_code(env, canned):
    client, _, _ = env
    canned["page"], canned["freshness"] = None, "computing"
    body = card(client)
    assert body["blocked_reason"] == "persona_unavailable" and body["freshness"] == "computing"
    canned["page"], canned["freshness"] = page("CEAS"), "fresh"
    body = card(client)
    assert body["eligible"] and body["code"] == "CEAS"
    assert body["type_name"] == "页面类型" and body["copy"] is None  # page copy as fallback
    assert copy_for("CEAS") == (None, None)


def test_hide_numbers(env, canned):
    client, _, _ = env
    stats = card(client, hide_numbers=True)["stats"]
    assert stats and all(s["hidden"] and s["value"] is None for s in stats)


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
