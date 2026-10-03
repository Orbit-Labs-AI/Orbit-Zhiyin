"""Hook events (IN-07 collection) → approval waits and context pressure; tmp homes only."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from realtime_fixtures import NOW, Reads

from orbit_backend.realtime.hooks import HookFeed
from orbit_backend.realtime.service import Realtime
from orbit_backend.services.gateway import Gateway

TOKEN = "synthetic-test-token-0123456789abcdef"


def line(event, ts, sid="s1", agent="claude_code", **extra) -> bytes:
    rec = {"v": 1, "ts": ts, "agent": agent, "event": event, "session_id": sid, **extra}
    return (json.dumps(rec) + "\n").encode()


def append(home, *chunks: bytes) -> None:
    path = home / "hooks" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as f:
        for chunk in chunks:
            f.write(chunk)


def test_feed_is_incremental_and_resumes_from_checkpoint(home):
    feed = HookFeed(home / "hooks")
    assert feed.poll() == 0  # no file yet
    full = line("PermissionRequest", 1_000, tool="Bash", command="rm -rf build")
    append(home, full, line("PostToolUse", 4_500)[:10])  # second line still being written
    assert feed.poll() == 1 and feed.pending()[0]["command"] == "rm -rf build"
    append(home, line("PostToolUse", 4_500)[10:])
    assert feed.poll() == 1 and feed.pending() == []
    assert feed.waits() == [{"agent": "claude_code", "session_id": "s1", "started_at": 1_000, "ended_at": 4_500,
                             "wait_s": 3.5, "tool": "Bash", "closed_by": "PostToolUse"}]

    # a new reader (gateway restart) resumes: no replay, an open wait survives
    append(home, line("Notification", 6_000, notification_type="permission_prompt", sid="s2"))
    again = HookFeed(home / "hooks")
    assert again.poll() == 1 and len(again.waits()) == 1 and again.pending()[0]["session_id"] == "s2"
    assert HookFeed(home / "hooks").poll() == 0

    # truncated / rotated file restarts at 0
    (home / "hooks" / "events.jsonl").write_bytes(line("Stop", 9_000, sid="s2"))
    assert again.poll() == 1 and again.pending() == [] and again.waits()[-1]["closed_by"] == "Stop"


def test_passive_events_keep_the_wait_open(home):
    append(home, line("PermissionRequest", 1_000), line("StatusLine", 2_000, context={"used_percentage": 50}),
           line("Notification", 3_000, notification_type="permission_prompt", command="ls"),
           line("PreCompact", 3_500), b"not json\n", line("Stop", 5_000))
    feed = HookFeed(home / "hooks")
    feed.poll()
    session = feed.session("claude_code", "s1")
    assert session["compact_ts"] == 3_500 and session["context"]["ts"] == 2_000
    assert feed.waits()[0]["wait_s"] == 4.0


def test_hook_secrets_are_redacted_before_views_and_checkpoint(home):
    secret = "audit_dummy_secret_never_a_real_credential"
    append(home, line("PermissionRequest", 1000, command=f"curl --token {secret}"))
    feed = HookFeed(home / "hooks")
    feed.poll()
    assert secret not in json.dumps(feed.pending())
    assert secret not in feed.checkpoint.read_text()
    # Old checkpoints are cleaned without needing a new event.
    raw = json.loads(feed.checkpoint.read_text())
    raw["sessions"]["claude_code:s1"]["pending"]["command"] = f"curl --token {secret}"
    feed.checkpoint.write_text(json.dumps(raw))
    again = HookFeed(home / "hooks")
    assert secret not in json.dumps(again.session("claude_code", "s1"))
    assert secret not in again.checkpoint.read_text()


def test_realtime_uses_hook_approval_and_statusline_context(orbit, home):
    orbit.session("s1", started=NOW - 60_000, title="部署")
    orbit.event("s1", NOW - 20_000, actor="assistant")
    append(home, line("PermissionRequest", NOW - 10_000, tool="Bash", command="git push"),
           line("StatusLine", NOW - 9_000, context={"used_tokens": 190_000, "context_window_size": 200_000}))
    gw = SimpleNamespace(reads=Reads(orbit.path), platform=None, appdb=None, home=home)
    rt = Realtime(gw, clock=lambda: NOW / 1000, notify=lambda e: None, resolve=lambda k: None)

    item = rt.snapshot(now=NOW / 1000)["sessions"][0]
    assert item["state"] == "awaiting_approval" and item["approval"]["command"] == "git push"
    assert item["approval"]["wait_s"] == 10
    assert "context_pressure" in item["flags"] and item["context"]["basis"] == "statusline"
    assert item["context"]["ratio"] == 0.95

    append(home, line("PreCompact", NOW - 2_000), line("PostToolUse", NOW - 1_000))
    item = rt.snapshot(now=NOW / 1000)["sessions"][0]
    assert item["state"] != "awaiting_approval" and "context_pressure" not in item["flags"]
    body = rt.approvals()
    assert body["pending"] == [] and body["summary"]["n"] == 1 and body["items"][0]["wait_s"] == 9.0


def test_approvals_route(home):
    gateway = Gateway(home, discovery=lambda: [], prewarm_debounce_s=3600.0)
    now = int(time.time() * 1000)
    append(home, line("PermissionRequest", now - 3_000), line("UserPromptSubmit", now - 1_000),
           line("PermissionRequest", now - 500, sid="s9"))
    with TestClient(gateway.app(token=TOKEN, port=8765), base_url="http://127.0.0.1:8765",
                    headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        body = client.get("/v1/analytics/realtime/approvals").json()
        assert body["summary"]["n"] == 1 and body["items"][0]["closed_by"] == "UserPromptSubmit"
        assert [p["session_id"] for p in body["pending"]] == ["s9"]
        assert client.get("/v1/analytics/realtime/approvals", params={"since": now}).json()["items"] == []
    gateway.realtime.close()
