"""SET-12: clear all data = marker now, deletion on the next start; agent dirs untouched."""

from __future__ import annotations

from orbit_data.store import Store

from orbit_backend.appdata import wipe
from orbit_backend.platform.storage import storage_report
from orbit_backend.realtime.hooks import HookFeed

from .conftest import client_for, close_gateway, make_gateway


def seed(home):
    Store(home).db.close()
    (home / "raw").mkdir(exist_ok=True)
    (home / "raw" / "blob").write_bytes(b"x" * 10)
    (home / "backups" / "1").mkdir(parents=True)
    (home / "backups" / "1" / "orbit.db").write_bytes(b"db")
    (home / "exports").mkdir(exist_ok=True)
    (home / "exports" / "diag.zip").write_bytes(b"zip")
    (home / "analysis-1.db").write_bytes(b"a")
    (home / "logs").mkdir(exist_ok=True)
    (home / "logs" / "gateway.log").write_text("keep me")


def agent_files(user_home):
    return sorted(p.relative_to(user_home) for p in user_home.rglob("*"))


def test_clear_removes_hook_history_and_checkpoint(tmp_path):
    home = tmp_path / "orbit"
    hooks = home / "hooks"
    hooks.mkdir(parents=True)
    for name in ("events.jsonl", "events.jsonl.1", "events.offset.json", ".statusline-last"):
        (hooks / name).write_text("{}")
    usage = next(c for c in storage_report(home)["components"] if c["id"] == "hooks")
    assert usage["bytes"] == 8
    wipe.mark(home)
    result = wipe.apply_pending(home)
    assert result["deleted"] == ["hooks"] and not result["failed"]
    assert not hooks.exists() and HookFeed(hooks).pending() == []


def test_describe_and_validation(client, gateway, home):
    body = client.get("/v1/app/data").json()
    assert body["confirm_word"] == "清除" and body["keeps"] == ["agent_logs", "agent_configs"]
    assert "orbit_db" in body["will_delete"] and "logs" not in body["will_delete"]
    assert {"installs_active", "ledger_entries", "jobs_active", "components"} <= body.keys()
    assert client.post("/v1/app/data/clear", json={"confirm": "delete"}).status_code == 422
    assert not (home / wipe.MARKER).exists()


def test_active_job_blocks_clear(client, gateway, home, tmp_path):
    root = tmp_path / "agents" / "codex"
    root.mkdir(parents=True)
    source = gateway.state.configure("codex", str(root), True, home)
    gateway.state.create_job("import", [source["id"]])
    response = client.post("/v1/app/data/clear", json={"confirm": "清除"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "job_active"
    gateway.jobs.runner.cancel = lambda _job_id: None  # No worker in tests.
    accepted = client.post("/v1/app/data/clear", json={"confirm": "清除", "cancel_jobs": True})
    assert accepted.status_code == 202


def test_clear_marks_then_restart_deletes(home, user_home):
    seed(home)
    (user_home / ".claude" / "projects" / "s.jsonl").write_text("{}\n")
    (user_home / ".codex" / "config.toml").write_text("model = 'x'\n")
    before_agents = agent_files(user_home)
    gw = make_gateway(home)
    try:
        client = client_for(gw)
        client.patch("/v1/app/settings", json={"onboarded": True})
        response = client.post("/v1/app/data/clear", json={"confirm": "清除"})
        assert response.status_code == 202
        body = response.json()
        assert body["restart_required"] is True and body["marker"].endswith(wipe.MARKER)
        # Nothing is deleted while running.
        assert (home / "orbit.db").exists() and (home / "app.db").exists()
        assert client.get("/v1/app/data").json()["pending"] is True
    finally:
        close_gateway(gw)
    gw = make_gateway(home)  # Restart: apply_pending runs first.
    try:
        assert gw.cleared is not None and not gw.cleared["refused"]
        # Recreated empty by the new gateway, so check what the clear removed.
        assert {"cache", "app.db", "app-state.json"} <= set(gw.cleared["deleted"])
        for name in ("raw", "backups", "exports", "analysis-1.db"):
            assert not (home / name).exists(), name
        assert not (home / "orbit.db").exists() and not (home / wipe.MARKER).exists()
        assert (home / "logs" / "gateway.log").read_text() == "keep me"
        status = client_for(gw).get("/v1/status").json()
        assert status["state"] == "onboarding" and status["settings"]["onboarded"] is False
    finally:
        close_gateway(gw)
    assert agent_files(user_home) == before_agents


def test_symlink_out_of_home_is_refused(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (home / "backups").symlink_to(outside, target_is_directory=True)
    (home / "app.db").symlink_to(outside / "keep.txt")
    (home / "orbit.db").write_bytes(b"x")
    wipe.mark(home)
    summary = wipe.apply_pending(home)
    assert sorted(summary["refused"]) == ["app.db", "backups"]
    assert summary["deleted"] == ["orbit.db"]
    assert (outside / "keep.txt").read_text() == "keep"


def test_no_marker_is_noop(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "orbit.db").write_bytes(b"x")
    assert wipe.apply_pending(home) is None and (home / "orbit.db").exists()
