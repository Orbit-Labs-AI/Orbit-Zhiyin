import time

from .conftest import HOUR


def test_quota_endpoints(orbit, client):
    now = int(time.time() * 1000)
    orbit.session("c1", agent="codex", started=now - 2 * HOUR)
    orbit.session("s1", agent="claude_code", started=now - 2 * HOUR)
    orbit.limits("c1", ts=now - HOUR, windows={
        "primary": {"used_percent": 20, "window_minutes": 300, "resets_at": now // 1000 + 3600}})
    orbit.model_call("s1", ts=now - HOUR, cost=0.5)
    orbit.model_call("c1", ts=now - HOUR, model="gpt-5")

    q = client.get("/v1/quota")
    assert q.status_code == 200
    assert any(w["agent"] == "codex" and w["used_percent"] == 20 for w in q.json()["quota_window"])

    a = client.get("/v1/quota/advice").json()
    assert a["recommendation"]["agent"] == "codex"

    u = client.get("/v1/usage", params={"group_by": "agent"}).json()
    assert [r["agent"] for r in u["rows"]] == ["claude_code", "codex"]
    assert u["totals"]["known_cost_usd"] == 0.5 and "quota_window" in u
    assert client.get("/v1/usage", params={"group_by": "project"}).status_code == 422

    client.post("/v1/sessions/s1/exclude", json={"reason": "test"})
    u = client.get("/v1/usage", params={"group_by": "agent"}).json()
    assert [r["agent"] for r in u["rows"]] == ["codex"]
