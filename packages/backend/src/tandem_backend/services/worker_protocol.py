"""stdio JSON Lines between gateway and workers.

gateway → worker: ``{"op": "run", "job": {...}}``, ``{"op": "cancel", "job_id"}``,
``{"op": "pause"}``, ``{"op": "resume"}``, ``{"op": "shutdown"}``.
worker → gateway: ``{"t": "ready"}``, ``{"t": "hb"}``, ``{"t": "progress"}``,
``{"t": "published"}``, ``{"t": "done"}``. Closing stdin makes the worker exit.
Messages carry stages, counts and analysis results; never raw session text.
"""

from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from typing import BinaryIO

PROTOCOL = "tandem-worker-v1"
HEARTBEAT_ENV = "TANDEM_WORKER_HEARTBEAT_S"
DEBUG_DELAY_ENV = "TANDEM_WORKER_DEBUG_DELAY_MS"
ORPHAN_POLL_S = 0.5
ORPHAN_GRACE_S = 3.0  # after the gateway is gone: time to reach a file boundary on EOF


def encode(message: dict) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
            + "\n").encode()


def decode(line: bytes | str) -> dict | None:
    """Return one message, or ``None`` for blank or malformed lines (never raise)."""
    text = line.decode(errors="replace") if isinstance(line, bytes) else line
    text = text.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def peak_rss_bytes() -> int:
    """Peak resident set size; macOS reports bytes and Linux KiB."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def tree_rss_bytes(pid: int | None = None) -> int | None:
    """Current resident set size of ``pid`` and all its descendants (process-pool workers
    included); ``None`` when ``ps`` is unavailable. ``ps`` reports KiB on macOS and Linux."""
    root = pid or os.getpid()
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True,
                             text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        child, parent, kib = map(int, parts)
        children.setdefault(parent, []).append(child)
        rss[child] = kib
    if root not in rss:
        return None
    total, stack, seen = 0, [root], set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        total += rss.get(current, 0)
        stack.extend(children.get(current, ()))
    return total * 1024


def debug_delay() -> None:
    """Optional fixed pause before each job, used by supervision tests to widen races."""
    delay = os.environ.get(DEBUG_DELAY_ENV)
    if delay:
        time.sleep(int(delay) / 1000)


class WorkerIO:
    """Worker side of the pipe. ``stdout`` is reserved; stray prints go to stderr."""

    def __init__(self, role: str, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None,
                 heartbeat_s: float | None = None):
        self.role = role
        self.parent = os.getppid() if stdout is None else None  # Only a real child watches.
        if stdout is None:
            # Keep fd 1 for the protocol and route any library print() to stderr.
            stdout = os.fdopen(os.dup(1), "wb", buffering=0)
            os.dup2(2, 1)
            sys.stdout = sys.stderr
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout
        self.lock = threading.Lock()
        self.heartbeat_s = heartbeat_s or float(os.environ.get(HEARTBEAT_ENV, "5"))
        self.current_job: str | None = None
        self.stopping = threading.Event()

    def send(self, t: str, **fields) -> None:
        data = encode({"t": t, **fields})
        with self.lock:
            try:
                self.stdout.write(data)
                self.stdout.flush()
            except (BrokenPipeError, ValueError):
                self.stopping.set()  # Gateway is gone; the read loop ends on EOF.

    def start_heartbeat(self) -> threading.Thread:
        def beat():
            while not self.stopping.wait(self.heartbeat_s):
                job = self.current_job
                # Live tree RSS only while a job runs (one ``ps`` per beat); idle beats
                # report the peak as before.
                live = tree_rss_bytes() if job is not None else None
                self.send("hb", job=job, rss=live if live is not None else peak_rss_bytes(),
                          live=live is not None)

        thread = threading.Thread(target=beat, daemon=True, name=f"{self.role}-hb")
        thread.start()
        if self.parent is not None:
            threading.Thread(target=self.watch_parent, daemon=True,
                             name=f"{self.role}-orphan").start()
        return thread

    def watch_parent(self, poll_s: float = ORPHAN_POLL_S, grace_s: float = ORPHAN_GRACE_S) -> None:
        """Exit when the gateway is gone (SIGKILLed after the host's quit deadline, crashed).

        Stdin EOF already asks the worker to stop at the next file boundary, but an import
        step or a long analysis can run for minutes, holding ``import.lock`` against the
        next launch. After ``grace_s`` the worker's whole process group (pool children
        included) gets SIGTERM.
        """
        while os.getppid() == self.parent:
            time.sleep(poll_s)
        self.stopping.set()
        time.sleep(grace_s)
        print(f"tandem-{self.role}: gateway {self.parent} is gone; exiting", file=sys.stderr,
              flush=True)
        try:
            if os.getpgrp() == os.getpid():
                os.killpg(os.getpid(), signal.SIGTERM)
            else:
                os.kill(os.getpid(), signal.SIGTERM)
        except OSError:
            os._exit(1)

    def ops(self) -> Iterator[dict]:
        for line in iter(self.stdin.readline, b""):
            message = decode(line)
            if message is not None:
                yield message
        self.stopping.set()
