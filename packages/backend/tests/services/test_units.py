"""Pure units: batch planning, event buffer, snapshot cache, job state, wire protocol."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from synthetic import write_codex_tree

from tandem_backend.services.events import EventBus
from tandem_backend.services.ingest_plan import plan_batches
from tandem_backend.services.jobs import AppState, JobConflict
from tandem_backend.services.snapshots import SnapshotKey, SnapshotStore, scope_hash
from tandem_backend.services.worker_protocol import decode, encode


def test_plan_head_window_rest(tmp_path):
    now = time.time()
    root = tmp_path / "codex"
    files = write_codex_tree(root, 90, now=now, spacing_hours=12)  # 45 days of history.
    batches = plan_batches("codex", root, now=now, rest_chunk=4)
    phases = [b.phase for b in batches]
    assert phases[:2] == ["head", "window"] and set(phases[2:]) == {"rest"}
    head, window = batches[0].files, batches[1].files
    rest = [f for b in batches[2:] for f in b.files]
    resolved = [f.resolve() for f in files]
    assert list(head) == resolved[:50]  # newest 50 (more than the last 7 days)
    assert list(window) == resolved[50:60]  # until 30 days
    assert rest == resolved[60:] and all(len(b.files) <= 4 for b in batches[2:])
    # A short history is all head when 7 days hold more than 50 sessions.
    dense = tmp_path / "dense"
    write_codex_tree(dense, 60, now=now, spacing_hours=1)
    assert [b.phase for b in plan_batches("codex", dense, now=now)] == ["head"]
    with pytest.raises(ValueError):
        plan_batches("codex", root, head_sessions=0)


def test_event_bus_ring_buffer_and_resume():
    bus = EventBus(capacity=5, heartbeat_s=0.05)
    ids = [bus.publish("job", "job", {"n": n}) for n in range(8)]
    assert ids == list(range(1, 9))
    frames, gap = bus.since(5)
    assert [f.id for f in frames] == [6, 7, 8] and not gap
    frames, gap = bus.since(1)  # Ids 2 and 3 were evicted.
    assert gap and [f.id for f in frames] == [4, 5, 6, 7, 8]
    with pytest.raises(ValueError):
        bus.publish("other", "x", {})

    async def collect():
        chunks = []
        async for chunk in bus.stream(1, {"job"}):
            chunks.append(chunk.decode())
            if len(chunks) == 7:
                break
        return chunks

    chunks = asyncio.run(collect())
    assert chunks[0].startswith("retry:")
    assert "event: resync" in chunks[1] and "id:" not in chunks[1]
    assert [int(c.split("\n")[0][4:]) for c in chunks[2:]] == [4, 5, 6, 7, 8]
    assert chunks[-1].endswith("\n\n") and json.loads(chunks[-1].split("data: ")[1]) == {"n": 7}

    async def heartbeat():
        async for chunk in bus.stream(None, {"job"}):
            if chunk.startswith(b": hb"):
                return True

    assert asyncio.run(asyncio.wait_for(heartbeat(), 2))


def test_snapshot_store_lru_retention_and_disk(tmp_path):
    path = tmp_path / "cache" / "ui.sqlite"
    store = SnapshotStore(path, memory_bytes=10_000)
    h = scope_hash({"project_ids": ["b", "a"]})
    assert h == scope_hash({"project_ids": ["a", "b"]})  # list order is not meaningful
    assert h != scope_hash({"project_ids": ["a"]})
    for rev in (1, 2, 3):
        store.put(SnapshotKey("overview", h, rev, 0, "r1"), {"overview": {"rev": rev}})
        time.sleep(0.002)
    assert store.get(SnapshotKey("overview", h, 1, 0, "r1")) is None  # keep newest two
    assert store.latest("overview", h, "r1").key.data_rev == 3
    assert store.latest("overview", h, "other-rules") is None
    store.close()
    reopened = SnapshotStore(path, memory_bytes=10_000)
    assert reopened.get(SnapshotKey("overview", h, 2, 0, "r1")).body == {"overview": {"rev": 2}}
    assert reopened.db.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 2
    # The memory tier never exceeds its budget; disk still serves evicted entries.
    big = {"blob": "x" * 6000}
    reopened.put(SnapshotKey("tools", h, 1, 0, "r1"), big)
    reopened.put(SnapshotKey("tasks", h, 1, 0, "r1"), big)
    assert reopened.memory_used <= 10_000
    assert reopened.get(SnapshotKey("tools", h, 1, 0, "r1")).body == big
    reopened.close()
    # Total disk cap evicts least recently used rows; a corrupt file is replaced.
    capped = SnapshotStore(path, disk_bytes=1)
    capped.put(SnapshotKey("overview", "other", 9, 0, "r1"), {"x": 1})
    assert capped.db.execute("SELECT count(*) FROM snapshot").fetchone()[0] <= 1
    capped.close()
    path.write_bytes(b"not a database")
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    recovered = SnapshotStore(path)
    assert recovered.latest("overview", h, "r1") is None
    recovered.close()


def test_app_state_transitions_and_restart(tmp_path, codex_root):
    home = tmp_path / "home"
    (home / "inside").mkdir(parents=True)
    state = AppState(home / "app-state.json")
    with pytest.raises(ValueError):
        state.configure("codex", str(home / "inside"), True, home)
    with pytest.raises(ValueError):
        state.configure("unknown", str(codex_root), True, home)
    source = state.configure("codex", str(codex_root), True, home)
    with pytest.raises(ValueError):
        state.create_job("import", [])
    with pytest.raises(ValueError):
        state.create_job("verify", [source["id"]])
    with pytest.raises(ValueError):
        state.create_job("import", [source["id"]], phase="later")
    job, sources = state.create_job("import", [source["id"]], phase="head")
    assert job["status"] == "queued" and sources[0]["root"] == str(codex_root)
    with pytest.raises(JobConflict):
        state.create_job("import", [source["id"]])
    state.transition(job["id"], "running")
    with pytest.raises(ValueError):
        state.transition(job["id"], "queued")
    with pytest.raises(ValueError):
        state.update_settings({"sync_mode": "always"})
    assert state.update_settings({"sync_mode": "live"})["sync_mode"] == "live"
    state.remember_scope({"a": 1})
    state.save()
    # A restart marks the running job interrupted and keeps its original scope.
    again = AppState(home / "app-state.json")
    restored = again.job(job["id"])
    assert restored["status"] == "interrupted" and restored["error"]["code"] == "app_restarted"
    assert restored["phase"] == "head" and restored["source_ids"] == [source["id"]]
    assert again.state["mru_scopes"] == [{"a": 1}]
    assert oct((home / "app-state.json").stat().st_mode & 0o777) == "0o600"
    assert not (home / "app-state.tmp").exists()


def test_protocol_round_trip_and_garbage():
    message = {"t": "progress", "job": "j", "progress": {"stage": "capture", "completed": 1}}
    assert decode(encode(message)) == message
    assert encode(message).endswith(b"\n") and encode(message).count(b"\n") == 1
    assert decode(b"") is None and decode(b"{not json") is None and decode(b"[1]") is None
