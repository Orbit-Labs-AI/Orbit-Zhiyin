"""Import pipeline regressions of Orbit v0.0.2 (docs/development/import-pipeline.md).

RC-1 sync imports back to back, RC-4 pending projection failing reads and a status that
claimed ``ready``, RC-5 WAL never truncated, RC-6 spill directories of killed imports,
RC-7 one whole-source rebuild per rest chunk, RC-8 progress without meaning, plus the
stall watchdog and the import retry entry. Synthetic Codex trees only.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest
from conftest import add_codex, wait_for, wait_job
from orbit_data.service import ImportRequest, ImportService
from orbit_data.store import Store
from synthetic import write_codex_tree

from orbit_backend.services.gateway import Gateway, sync_wait
from orbit_backend.services.jobs import AppState
from orbit_backend.services.supervisor import IngestRunner, SupervisorConfig
from orbit_backend.services.worker_ingest import IngestWorker, remove_stale_spills


def test_pending_capture_serves_the_published_snapshot(client_factory, tmp_path):
    root = tmp_path / "agents" / "codex"
    write_codex_tree(root, 6)
    home = tmp_path / "home"
    with Store(home) as store:
        ImportService(store, maintenance="off").import_source(ImportRequest("codex", root))
    write_codex_tree(root, 1, start=6)  # One more rollout: captured, not published yet.
    with Store(home) as store:
        ImportService(store, maintenance="off").import_source(
            ImportRequest("codex", root, rebuild=False))
    client, gateway = client_factory(home)
    page = client.get("/v1/sessions", params={"limit": 50})
    # v0.0.2: 503 projection_pending (the overview showed 0 sessions) unless this exact URL
    # had been answered before.
    assert page.status_code == 200, page.text
    assert page.headers["x-orbit-freshness"] == "stale"
    assert page.headers["x-orbit-projection"] == "pending"
    assert page.headers["x-total-count"] == "6"
    status = client.get("/v1/status").json()
    # v0.0.2: "ready", whatever the reads answered.
    assert status["projection"] == "pending"
    info = status["projection_info"]
    assert info["pending_files"] == 1 and info["stuck"] is False and "retry" not in info
    gateway.stuck_after_s = 0  # Pending and no import running: offer the retry.
    time.sleep(0.01)
    info = client.get("/v1/status").json()["projection_info"]
    assert info["stuck"] is True
    assert info["retry"] == {"method": "POST", "path": "/v1/app/jobs", "body": {"kind": "import"}}


def test_sync_wait_never_runs_sync_imports_back_to_back():
    bounds, now = (2.0, 30.0), 1_790_000_000_000
    took_150 = {"status": "completed", "started_at": now - 150_000, "finished_at": now,
                "results": [{"changed": 3}]}
    # v0.0.2 started the next full import 2 s after one that saw a change; an agent in use
    # changes something every round, so imports ran back to back.
    assert sync_wait("live", took_150, now, 2.0, bounds) == 150.0
    assert sync_wait("live", took_150, now + 140_000, 2.0, bounds) == 10.0
    quick = {**took_150, "started_at": now - 1_000}
    assert sync_wait("live", quick, now, 2.0, bounds) == 2.0
    assert sync_wait("live", {**quick, "results": [{"changed": 0}]}, now, 16.0, bounds) == 16.0
    for status in ("failed", "interrupted", "cancelled"):
        failed = {**quick, "status": status, "results": []}
        assert sync_wait("live", failed, now, 2.0, bounds) == 30.0
    assert sync_wait("hour", quick, now + 600_000, 2.0, bounds, 3600.0) == 3000.0
    assert sync_wait("live", None, now, 2.0, bounds) == 0.0


class Rounds:
    """``stopping`` stand-in that lets the sync loop run a number of rounds."""

    def __init__(self, rounds: int):
        self.rounds = rounds

    def wait(self, _interval: float) -> bool:
        self.rounds -= 1
        return self.rounds < 0

    def is_set(self) -> bool:
        return self.rounds < 0


def _sync_gateway(tmp_path, took_s: float, ended_ago_s: float):
    tmp_path.mkdir(parents=True, exist_ok=True)
    state = AppState(tmp_path / "app-state.json")
    root = tmp_path / "codex"
    root.mkdir()
    source = state.configure("codex", str(root), True, tmp_path / "home")
    state.update_settings({"sync_mode": "live"})
    job, _ = state.create_job("import", [source["id"]], phase="full", origin="sync")
    now = int(time.time() * 1000)
    state.transition(job["id"], "running", started_at=now - int((took_s + ended_ago_s) * 1000))
    state.transition(job["id"], "completed", results=[{"changed": 2}])
    state.state["jobs"][job["id"]]["finished_at"] = now - int(ended_ago_s * 1000)
    calls = []
    collection = SimpleNamespace(paused=False, catch_up_pending=False,
                                 consume_catch_up=lambda: False)
    gw = SimpleNamespace(
        state=state, platform=SimpleNamespace(collection=collection),
        jobs=SimpleNamespace(submit=lambda *args, **kwargs: calls.append((args, kwargs))),
        sync_interval_s=(0.0, 0.0), hourly_sync_s=3600.0)
    return gw, calls


def test_sync_loop_waits_as_long_as_the_last_sync_import_took(tmp_path):
    gw, calls = _sync_gateway(tmp_path, took_s=120, ended_ago_s=1)
    gw.stopping = Rounds(5)
    Gateway._sync_loop(gw)
    assert calls == []  # 2 s after a 120 s import that saw changes: not yet.
    gw, calls = _sync_gateway(tmp_path / "later", took_s=120, ended_ago_s=125)
    gw.stopping = Rounds(1)
    Gateway._sync_loop(gw)
    assert len(calls) == 1 and calls[0][1] == {"phase": "full", "origin": "sync"}


def test_worker_start_removes_spill_directories_of_killed_imports(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    legacy = home / "import-1caqqqr8"  # v0.0.2 name, no owner recorded
    legacy.mkdir()
    (legacy / "results.pkl").write_bytes(b"spilled")
    (home / "import-999999-dead").mkdir()  # owner pid no longer exists
    live = home / f"import-{os.getpid()}-live"
    live.mkdir()
    assert sorted(remove_stale_spills(home)) == ["import-1caqqqr8", "import-999999-dead"]
    assert live.is_dir()


class FakeIO:
    def __init__(self):
        self.messages: list[dict] = []
        self.current_job = None

    def send(self, t, **fields):
        self.messages.append({"t": t, **fields})


def test_import_progress_explains_itself_and_never_moves_backwards(tmp_path):
    root = tmp_path / "agents" / "codex"
    write_codex_tree(root, 70)  # 35 days of history: head, window and rest batches.
    home = tmp_path / "home"
    io = FakeIO()
    job = {"id": "job-1", "kind": "import", "phase": "auto", "files_by_source": {},
           "limit": None, "plan": {"max_age_days": 400, "rest_chunk": 2},
           "sources": [{"id": "source-codex", "agent": "codex", "root": str(root)}]}
    IngestWorker(home, io).run(job)
    done = next(m for m in io.messages if m["t"] == "done")
    assert done["status"] == "completed", done
    # RC-7: rest chunks of 2 files used to rebuild the whole Codex source once per chunk.
    assert [r["phase"] for r in done["results"]] == ["head", "window", "rest"]
    frames = [m["progress"] for m in io.messages if m["t"] == "progress"]
    assert all(f["label"] and "detail" in f and f["steps"] == 1 for f in frames)
    capture = next(f for f in frames if f["stage"] == "capture" and f.get("total"))
    assert capture["unit"] == "files" and capture["label"] == "读取会话文件"
    assert capture["detail"].startswith("Codex · 第 1/3 批")
    mapped = [f for f in frames if f["stage"] == "map" and f.get("records")]
    assert mapped and mapped[-1]["unit"] == "files" and "条记录" in mapped[-1]["detail"]
    assert {f["scope"] for f in frames if f["stage"] == "prepare"} == {"source"}
    assert {f["batch_phase"] for f in frames} == {"head", "window", "rest"}
    overall = [f["overall"] for f in frames]
    assert overall == sorted(overall) and overall[-1] == 1.0
    # RC-5: the job folds its WAL back and truncates it; a new store caps resets at 64 MiB.
    assert done["wal"]["busy"] is False and done["wal"]["wal_bytes"] == 0
    with Store(home) as store:
        assert store.db.execute("PRAGMA journal_size_limit").fetchone()[0] == 64 << 20


class FakeWorker:
    def __init__(self):
        self.killed: list[str | None] = []

    def kill(self, reason):
        self.killed.append(reason)

    def running(self):
        return True


def test_stalled_import_is_stopped_with_a_retryable_error(tmp_path):
    runner = IngestRunner(tmp_path, SupervisorConfig(ingest_stall_s=10.0),
                          on_state=lambda *_: None, on_published=lambda _: None)
    runner.worker = FakeWorker()
    interrupted = []
    runner.jobs = SimpleNamespace(interrupted=lambda *args: interrupted.append(args))
    runner.current, runner.pending = "job-1", None
    now = time.monotonic()
    runner.last_progress = now - 5
    runner.check(now)
    assert runner.worker.killed == []  # Still within the budget.
    runner.paused = True
    runner.last_progress = now - 60
    runner.check(now)
    assert runner.worker.killed == []  # Paused for interactive analysis: not a stall.
    runner.paused = False
    runner.last_progress = now - 60
    runner.check(now)
    assert runner.worker.killed == ["stalled"]
    runner._exit("stalled")
    assert interrupted and interrupted[0][:2] == ("job-1", "job_stalled")
    assert runner.current is None


@pytest.mark.serial
def test_import_without_sources_reindexes_every_enabled_source(client_factory, codex_root):
    client, _ = client_factory()
    source = add_codex(client, codex_root)
    # v0.0.2: 设置 › 立即重新索引 sent this and got 422 "Select at least one enabled source".
    response = client.post("/v1/app/jobs", json={"kind": "import"})
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["source_ids"] == [source]
    assert wait_job(client, job["id"])["status"] == "completed"
    wait_for(lambda: client.get("/v1/status").json()["projection"] == "ready", 10,
             message="freshness re-read after the import")


def test_progress_frames_carry_origin_and_every_new_source(tmp_path):
    from orbit_backend.services.jobs import JobService

    state = AppState(tmp_path / "app-state.json")
    root = tmp_path / "codex"
    root.mkdir()
    source = state.configure("codex", str(root), True, tmp_path / "home")
    frames = []
    service = JobService(state, SimpleNamespace(start=lambda *_: None, cancel=lambda *_: None),
                         lambda topic, event, data: frames.append(data), progress_interval_s=60)
    job = service.submit("import", [source["id"]], phase="full", origin="sync")
    service.started(job["id"])
    frames.clear()
    capture = {"stage": "capture", "completed": 0, "total": 5}
    service.progress(job["id"], {**capture, "step": 1})
    service.progress(job["id"], {**capture, "completed": 1, "step": 1})  # coalesced
    service.progress(job["id"], {**capture, "step": 2})  # next source: always sent
    service.progress(job["id"], {"stage": "reset_projection", "step": 2, "attempt": 1})
    service.progress(job["id"], {"stage": "reset_projection", "step": 2, "attempt": 2})
    assert [f["progress"].get("step") for f in frames] == [1, 2, 2, 2]
    assert [f["progress"].get("attempt") for f in frames][-2:] == [1, 2]
    assert {f["origin"] for f in frames} == {"sync"}  # the UI shows it as 后台同步


def test_freshness_reload_never_moves_the_published_revision_back(tmp_path, monkeypatch):
    from orbit_backend.services import worker_ingest
    from orbit_backend.services.gateway import Revisions

    (tmp_path / "orbit.db").write_bytes(b"")
    revisions = Revisions()
    revisions.update(data_rev=7, counts={"sessions": 3}, freshness={"projection": "ready"})
    stale = {"data_rev": 6, "inventory_rev": 0, "counts": {"sessions": 2},
             "freshness": {"projection": "pending", "pending_files": 1, "retained_files": 0}}
    monkeypatch.setattr(worker_ingest, "revision", lambda home: dict(stale))
    revisions.load(tmp_path)  # read before run 7 landed, applied after it
    assert revisions.snapshot()["data_rev"] == 7 and revisions.snapshot()["projection"] == "ready"
    monkeypatch.setattr(worker_ingest, "revision", lambda home: {**stale, "data_rev": 7})
    revisions.load(tmp_path)
    snap = revisions.snapshot()
    assert snap["projection"] == "pending" and snap["pending_files"] == 1 and snap["pending_since"]


def test_inventory_job_republishes_tool_names_its_mcp_servers_resolve(tmp_path):
    """opencode splits ``<server>_<tool>`` only with inventoried server names: an inventory
    job after the import republishes those sessions instead of leaving them stale or
    unresolved until some later import."""
    import json

    from orbit_data.contract import canonical

    home, root = tmp_path / "home", tmp_path / "agents" / "opencode"
    root.mkdir(parents=True)
    (root / "opencode.json").write_text(
        json.dumps({"mcp": {"my-server": {"type": "local", "command": ["x"]}}}))
    part = {"type": "tool", "callID": "c", "tool": "my-server_search", "state": {}}
    rows = [
        {"table": "session", "key": {"id": "s"}, "row": {"id": "s", "directory": "/fixture"}},
        {"table": "part", "key": {"id": "p"}, "row": {
            "id": "p", "message_id": "m", "session_id": "s", "time_created": 1790900000000,
            "data": canonical(part)}},
    ]
    with Store(home) as store:
        source = store.add_source("opencode", root)
        store.capture_stream(source, "opencode.db",
                             [(canonical(r) + "\n").encode() for r in rows],
                             format_name="sqlite_rows")
        other = store.add_source("claude_code", tmp_path / "agents" / "claude")
        store.capture_stream(other, "p/s.jsonl", [b'{"type":"summary","summary":"x"}\n'],
                             format_name="jsonl")
        store.rebuild()
        # Stale for an unrelated reason (e.g. a reducer bump): the inventory job leaves it
        # for its own import instead of re-reducing the whole library.
        store.db.execute("UPDATE source_file SET watermark=json_set(watermark,"
                         "'$.reducer_version','old') WHERE source_id=?", (other,))
        store.db.commit()
    io = FakeIO()
    job = {"id": "job-inv", "kind": "inventory",
           "sources": [{"id": source, "agent": "opencode", "root": str(root),
                        "allowed_roots": []}]}
    IngestWorker(home, io).run(job)
    done = next(m for m in io.messages if m["t"] == "done")
    assert done["status"] == "completed", done
    assert done["results"][0]["remap_files"] == 1 and done["results"][-1]["kind"] == "remap"
    assert [m["phase"] for m in io.messages if m["t"] == "published"] == ["inventory", "rebuild"]
    with Store(home) as store:
        row = store.db.execute(
            "SELECT kind, mcp_server, mcp_tool FROM tool_call WHERE native_call_id='c'").fetchone()
        assert tuple(row) == ("mcp", "my-server", "search")
        stale = store.db.execute(
            "SELECT json_extract(watermark,'$.reducer_version') FROM source_file "
            "WHERE source_id=?", (other,)).fetchone()[0]
        assert stale == "old"
