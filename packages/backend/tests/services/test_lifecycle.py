"""Process lifecycle: the helper and its workers leave no process behind and exit fast."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time

import httpx
import pytest
from conftest import AUTH, TOKEN, fast_config, wait_for

from tandem_backend.services import supervisor as supervisor_module
from tandem_backend.services.snapshots import SnapshotStore
from tandem_backend.services.supervisor import Supervisor
from tandem_backend.services.worker_protocol import ORPHAN_GRACE_S

# Wall-clock deadlines and real subprocesses: run outside the parallel (xdist) pass.
pytestmark = pytest.mark.serial


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _start_helper(home, extra_env=None):
    process = subprocess.Popen(
        [sys.executable, "-m", "tandem_backend.services", "gateway", "--home", str(home)],
        env={**os.environ, "TANDEM_API_TOKEN": TOKEN, **(extra_env or {})},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process, json.loads(process.stdout.readline())["port"]


def _ready(port: int) -> None:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=AUTH, timeout=10) as http:
        wait_for(lambda: http.get("/v1/status").status_code == 200, 30, 0.05, "status")


def test_sigterm_with_open_streams_exits_without_waiting_out_the_drain(tmp_path):
    """The realtime SSE only polled ``gateway.stopping``, which was set after uvicorn's
    3 s graceful drain: every quit waited it out and logged CancelledError tracebacks."""
    process, port = _start_helper(tmp_path / "home")
    try:
        _ready(port)
        opened = threading.Event()

        def listen(path):
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=AUTH,
                                  timeout=None) as http, http.stream("GET", path) as response:
                    for _ in response.iter_raw():
                        opened.set()
            except httpx.HTTPError:
                pass

        for path in ("/v1/events", "/v1/analytics/realtime/stream"):
            threading.Thread(target=listen, args=(path,), daemon=True).start()
        assert opened.wait(30)
        time.sleep(1.0)  # Both streams attached.
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        process.wait(15)
        elapsed = time.monotonic() - started
        stderr = process.stderr.read().decode(errors="replace")
        assert "CancelledError" not in stderr and "Traceback" not in stderr, stderr[-2000:]
        assert elapsed < 2.5, f"helper took {elapsed:.2f}s to exit"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_parent_exit_shuts_down_cleanly(tmp_path):
    """handle_exit(None, None) made uvicorn re-raise signal None: TypeError traceback, rc 1."""
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    process, port = _start_helper(tmp_path / "home", {"TANDEM_PARENT_PID": str(parent.pid)})
    try:
        _ready(port)
        parent.kill()
        parent.wait()
        assert process.wait(15) == 0
        stderr = process.stderr.read().decode(errors="replace")
        assert "Traceback" not in stderr, stderr[-2000:]
    finally:
        for proc in (parent, process):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


# A worker stuck in one long step: ignores stdin EOF, owns a "pool child".
STUCK_WORKER = textwrap.dedent("""
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    print(child.pid, file=sys.stderr, flush=True)
    sys.stdout.write('{"t": "ready"}\\n'); sys.stdout.flush()
    time.sleep(120)
""")


def test_stop_is_parallel_and_reaps_pool_children(tmp_path, monkeypatch):
    """Workers were stopped one after another (stdin grace + SIGTERM grace each), and a
    terminated worker's pool children were never signalled."""
    monkeypatch.setattr(supervisor_module, "worker_command",
                        lambda role, home: [sys.executable, "-c", STUCK_WORKER])
    config = fast_config(term_grace_s=1.0)
    snapshots = SnapshotStore(tmp_path / "ui.sqlite")
    sup = Supervisor(tmp_path, config, snapshots, lambda *a: 0, lambda entry: None)
    try:
        workers = (sup.ingest.worker, sup.analysis.worker)
        for worker in workers:
            assert worker.ensure()
        logs = [tmp_path / "logs" / f"{w.role}.log" for w in workers]
        children = [int(wait_for(lambda p=p: p.read_text().strip(), 20, 0.05, "child pid"))
                    for p in logs]
        assert all(_alive(pid) for pid in children)
        started = time.monotonic()
        sup.stop()
        elapsed = time.monotonic() - started
        # One grace for both workers (1 s), not one per worker per step (>= 2 s).
        assert elapsed < 1.8, f"stop took {elapsed:.2f}s"
        wait_for(lambda: not any(_alive(pid) for pid in children), 5, 0.05, "pool children")
    finally:
        snapshots.close()


def test_worker_exits_when_gateway_is_killed(tmp_path):
    """A worker whose gateway was SIGKILLed kept running its step (holding import.lock)."""
    worker = textwrap.dedent("""
        import time
        from tandem_backend.services.worker_protocol import WorkerIO
        io = WorkerIO("test", heartbeat_s=0.2)
        io.start_heartbeat()
        time.sleep(120)  # A long step: stdin EOF alone does not end it.
    """)
    gateway = textwrap.dedent(f"""
        import subprocess, sys, time
        proc = subprocess.Popen([sys.executable, "-c", {worker!r}], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, start_new_session=True)
        print(proc.pid, flush=True)
        time.sleep(120)
    """)
    fake = subprocess.Popen([sys.executable, "-c", gateway], stdout=subprocess.PIPE)
    pid = int(fake.stdout.readline())
    try:
        time.sleep(1.0)
        assert _alive(pid)
        fake.kill()
        fake.wait()
        wait_for(lambda: not _alive(pid), ORPHAN_GRACE_S + 5, 0.1, "orphaned worker exit")
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)
