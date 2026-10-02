"""End to end: unlabelled synthetic Codex logs → import → inventory → ≥ 6 recommendation cards.

Runs the real Gateway in a temporary HOME; only the synthetic writer touches agent dirs.
"""

from __future__ import annotations

import time

from codex_friction import write_friction_codex
from conftest import add_codex, run_job, wait_job


def test_unlabelled_codex_logs_yield_cards(client_factory, tmp_path, monkeypatch):
    home = tmp_path / "user-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    codex = write_friction_codex(home / ".codex")
    client, _ = client_factory(home / "tandem-home")
    source = add_codex(client, codex)
    assert wait_job(client, run_job(client, "import", [source])["id"])["status"] == "completed"
    assert wait_job(client, run_job(client, "inventory", [source])["id"])["status"] == "completed"
    body, deadline = None, time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get("/v1/recommendations", params={"wait_ms": 3000})
        assert response.status_code in (200, 202), response.text
        body = response.json()
        if response.status_code == 200 and body.get("meta", {}).get("freshness") == "fresh":
            break
        time.sleep(0.5)
    assert body is not None and body["run"]["status"] == "ready", (body or {}).get("run")
    titles = [item.get("title") for item in body["items"]]
    assert len(body["items"]) >= 6, titles
    assert len({item.get("dim") for item in body["items"]}) >= 4, titles
