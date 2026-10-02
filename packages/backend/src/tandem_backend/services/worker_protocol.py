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
import sys
import threading
import time
from collections.abc import Iterator
from typing import BinaryIO

PROTOCOL = "tandem-worker-v1"
HEARTBEAT_ENV = "TANDEM_WORKER_HEARTBEAT_S"
DEBUG_DELAY_ENV = "TANDEM_WORKER_DEBUG_DELAY_MS"


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
                self.send("hb", job=self.current_job, rss=peak_rss_bytes())

        thread = threading.Thread(target=beat, daemon=True, name=f"{self.role}-hb")
        thread.start()
        return thread

    def ops(self) -> Iterator[dict]:
        for line in iter(self.stdin.readline, b""):
            message = decode(line)
            if message is not None:
                yield message
        self.stopping.set()
