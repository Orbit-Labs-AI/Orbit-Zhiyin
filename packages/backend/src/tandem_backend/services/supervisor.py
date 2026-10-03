"""Worker supervision: lazy spawn, heartbeats, exponential-backoff restarts, timeouts.

Each worker is a child process speaking stdio JSON Lines (``worker_protocol``). The
gateway launches ``<python> -m tandem_backend.services worker <role>`` in development
and ``<frozen executable> worker <role>`` from a PyInstaller build.

- heartbeat every ``heartbeat_s`` (5 s); no message for ``stale_s`` (15 s) → kill + restart
- crash restarts back off 0.5 / 1 / 2 / 4 s; more than 5 within 60 s → ``degraded``
- analysis tasks time out (light 20 s, heavy 120 s; ``TANDEM_ANALYSIS_HEAVY_TIMEOUT_S``
  overrides the heavy base) plus a per-event allowance once the worker reports the scope's
  event count; each timed-out retry of the same key doubles that budget, all capped at
  ``max_budget_s``: kill, task ``failed(timeout)``, the previous snapshot keeps serving;
  three failures (one for on-demand legacy sections) open a circuit for that key, after
  which routes answer 503 without re-running it. A task whose budget already hit the cap
  fails ``analysis_scope_too_large`` (narrow the scope) instead of a bare timeout; sections
  with their own ``timeout_s`` use it as the base
- analysis RSS (the worker and its process-pool children) above 1.5 GB recycles the worker
  after the task; above ``rss_kill_bytes`` (¾ of RAM, 4–24 GB) while running (heartbeat
  RSS) kills it and fails the task ``analysis_scope_too_large``; idle 5 min recycles too
- analysis runs a killed or crashed worker left ``running`` in ``analysis.sqlite`` are
  failed (the worker reports open runs); at start, runs older than ``max_budget_s`` are too
- an import with no progress frame for ``ingest_stall_s`` (15 min) is stopped and recorded
  ``interrupted(job_stalled)``; the next job starts a fresh worker
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .sections import SECTIONS
from .snapshots import SnapshotKey, SnapshotStore
from .worker_protocol import HEARTBEAT_ENV, decode, encode

HEAVY_TIMEOUT_ENV = "TANDEM_ANALYSIS_HEAVY_TIMEOUT_S"


def _heavy_timeout_default() -> float:
    try:
        return float(os.environ.get(HEAVY_TIMEOUT_ENV) or 120.0)
    except ValueError:
        return 120.0


def physical_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def default_rss_kill_bytes() -> int:
    """Three quarters of the machine's memory, within 4–24 GB. Measured on a real home
    (1.9k sessions / 770k events): the all-time analysis peaks near 17 GB, 30 days near
    10 GB; the guard protects the machine (a smaller Mac fails that window explicitly
    with ``analysis_scope_too_large`` instead of swapping) without failing normal work."""
    total = physical_memory_bytes() or 8 * 2**30
    return int(min(max(total * 3 // 4, 4 * 2**30), 24 * 2**30))


@dataclass
class SupervisorConfig:
    heartbeat_s: float = 5.0
    stale_s: float = 15.0
    term_grace_s: float = 3.0
    backoff_s: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)
    restart_window_s: float = 60.0
    max_restarts: int = 5
    light_timeout_s: float = 20.0
    heavy_timeout_s: float = field(default_factory=_heavy_timeout_default)
    # Seconds per 1 000 selected events on top of the base budget (sized after start).
    # Measured: ~0.39 s/k for a light section on a 772k-event home (read + analyse).
    light_s_per_kevent: float = 0.6
    heavy_s_per_kevent: float = 1.2
    # Ceiling of every budget (sized allowance and per-timeout doubling included).
    max_budget_s: float = 900.0
    rss_limit_bytes: int = 1_500_000_000
    rss_kill_bytes: int = field(default_factory=lambda: default_rss_kill_bytes())
    analysis_idle_s: float = 300.0
    # A running import that reports no progress for this long is stopped (job_stalled) so
    # the user can retry it; every stage reports at least per file or per session, and the
    # longest silent steps measured on a 7 GB home (deleting a source's facts, committing)
    # take minutes, not a quarter of an hour.
    ingest_stall_s: float = 900.0
    max_failures: int = 3
    max_preemptions: int = 2  # an interactive task may interrupt the same prewarm this often
    tick_s: float = 0.2
    worker_env: dict[str, str] = field(default_factory=dict)
    plan: dict = field(default_factory=dict)  # ingest_plan overrides (head_sessions, …)


def worker_command(role: str, home: Path) -> list[str]:
    if getattr(sys, "frozen", False):  # PyInstaller: re-enter the same executable.
        return [sys.executable, "worker", role, "--home", str(home)]
    return [sys.executable, "-m", "tandem_backend.services", "worker", role, "--home", str(home)]


class WorkerProcess:
    """One supervised child. ``ensure()`` spawns lazily; crashes restart with backoff."""

    def __init__(self, role: str, home: Path, config: SupervisorConfig,
                 on_message: Callable[[dict], None], on_exit: Callable[[str | None], None],
                 on_state: Callable[[str, str], None], on_spawn: Callable[[], None]):
        self.role, self.home, self.config = role, home, config
        self.on_message, self.on_exit, self.on_state, self.on_spawn = (
            on_message, on_exit, on_state, on_spawn)
        self.lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.state = "idle"
        self.restarts: deque[float] = deque()
        self.restarts_total = 0
        self.last_hb = 0.0
        self.last_activity = time.monotonic()
        self.expected_exit: str | None = None
        self.timer: threading.Timer | None = None
        self.niced = False

    @property
    def pid(self) -> int | None:
        proc = self.proc
        return proc.pid if proc is not None and proc.poll() is None else None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def info(self) -> dict:
        with self.lock:
            age = time.monotonic() - self.last_hb if self.running() else None
            return {"state": self.state, "pid": self.pid, "restarts": self.restarts_total,
                    "last_hb_age_s": round(age, 3) if age is not None else None}

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.on_state(self.role, state)

    def ensure(self) -> bool:
        with self.lock:
            if self.running():
                return True
            if self.state in ("degraded", "stopped") or self.timer is not None:
                return False
            self._spawn()
            return True

    def _spawn(self) -> None:
        (self.home / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {**os.environ, HEARTBEAT_ENV: str(self.config.heartbeat_s),
               **self.config.worker_env}
        with open(self.home / "logs" / f"{self.role}.log", "ab") as log:
            self.proc = subprocess.Popen(worker_command(self.role, self.home),
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=log, env=env)
        self.expected_exit = None
        self.niced = False
        self.last_hb = self.last_activity = time.monotonic()
        threading.Thread(target=self._read, args=(self.proc,), daemon=True,
                         name=f"{self.role}-reader").start()
        self._set_state("ok")

    def send(self, message: dict) -> bool:
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                return False
            try:
                proc.stdin.write(encode(message))
                proc.stdin.flush()
                self.last_activity = time.monotonic()
                return True
            except (BrokenPipeError, ValueError, OSError):
                return False

    def _read(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, b""):
            message = decode(line)
            if message is None:
                continue
            with self.lock:
                if proc is self.proc:
                    self.last_hb = time.monotonic()
            self.on_message(message)  # Heartbeats too: analysis reads their live RSS.
        proc.wait()
        with self.lock:
            if proc is not self.proc:
                return
            reason = self.expected_exit
            self.proc = None
        self.on_exit(reason)
        with self.lock:
            if reason is None and self.state != "stopped":
                self._schedule_restart()
            elif self.state not in ("stopped", "degraded"):
                self._set_state("idle")

    def _schedule_restart(self) -> None:
        now = time.monotonic()
        while self.restarts and now - self.restarts[0] > self.config.restart_window_s:
            self.restarts.popleft()
        if len(self.restarts) >= self.config.max_restarts:
            self._set_state("degraded")
            return
        delay = self.config.backoff_s[min(len(self.restarts), len(self.config.backoff_s) - 1)]
        self.restarts.append(now)
        self.restarts_total += 1
        self._set_state("restarting")
        self.timer = threading.Timer(delay, self._respawn)
        self.timer.daemon = True
        self.timer.start()

    def _respawn(self) -> None:
        with self.lock:
            self.timer = None
            if self.state in ("degraded", "stopped") or self.running():
                return
            self._spawn()
        self.on_spawn()

    def kill(self, reason: str | None) -> None:
        """``reason`` marks an intentional stop (no backoff); ``None`` counts as a crash."""
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                return
            self.expected_exit = reason
        proc.terminate()

        def force():
            if proc.poll() is None:
                proc.kill()

        timer = threading.Timer(self.config.term_grace_s, force)
        timer.daemon = True
        timer.start()

    def reset(self) -> None:
        """Leave ``degraded`` after a user retry; the next ensure() spawns again."""
        with self.lock:
            self.restarts.clear()
            if self.state == "degraded":
                self._set_state("idle")

    def stop(self) -> None:
        with self.lock:
            self._set_state("stopped")
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            proc = self.proc
            self.expected_exit = "stopped"
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()  # Workers exit on EOF; ingest stops at a file boundary.
            proc.wait(self.config.term_grace_s)
        except (subprocess.TimeoutExpired, OSError):
            proc.terminate()
            try:
                proc.wait(self.config.term_grace_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


class IngestRunner:
    """``JobRunner`` backed by the ingest worker subprocess."""

    def __init__(self, home: Path, config: SupervisorConfig, on_state, on_published):
        self.config = config
        self.jobs = None  # JobService, bound after construction.
        self.on_published = on_published
        self.current: str | None = None
        self.pending: dict | None = None
        self.paused = False
        self.last_progress = time.monotonic()
        self.lock = threading.RLock()
        self.on_state = on_state
        self.worker = WorkerProcess("ingest", home, config, self._message, self._exit,
                                    self._state, self._send_pending)

    def start(self, job: dict, sources: list[dict]) -> None:
        with self.lock:
            if self.current is not None:
                raise RuntimeError("ingest worker busy")
            if not self.worker.ensure() and self.worker.state != "restarting":
                raise RuntimeError(f"ingest worker {self.worker.state}")
            self.current = job["id"]
            self.last_progress = time.monotonic()
            # During a backoff restart the job waits and is sent once the worker respawns.
            self.pending = {"op": "run", "job": {**job, "sources": sources,
                                                 "plan": {**self.config.plan,
                                                          **(job.get("plan") or {})}}}
            self._send_pending()

    def _state(self, role: str, state: str) -> None:
        self.on_state(role, state)
        if state == "degraded":
            with self.lock:
                job_id = self.current if self.pending is not None else None
                if job_id is not None:
                    self.pending = self.current = None
            if job_id is not None:
                self.jobs.finished(job_id, "failed", [], {
                    "code": "service_unavailable", "message": "ingest worker degraded",
                    "retryable": True})

    def _send_pending(self) -> None:
        with self.lock:
            if self.pending is not None and self.worker.send(self.pending):
                self.pending = None

    def cancel(self, job_id: str) -> None:
        with self.lock:
            if self.current == job_id:
                self.worker.send({"op": "cancel", "job_id": job_id})

    def pause(self, paused: bool) -> None:
        with self.lock:
            if paused != self.paused and self.worker.running():
                self.worker.send({"op": "pause" if paused else "resume"})
            self.paused = paused

    def check(self, now: float) -> None:
        """Watchdog tick: stop an import that made no progress for ``ingest_stall_s``.

        The heartbeat only proves the worker process is alive; a job thread stuck inside
        one step would otherwise keep the job ``running`` (and every sync behind it)
        forever. Time spent paused for interactive analysis does not count.
        """
        with self.lock:
            if self.paused or self.current is None or self.pending is not None:
                self.last_progress = now
                return
            stalled = now - self.last_progress > self.config.ingest_stall_s
        if stalled:
            self.worker.kill("stalled")

    def _message(self, message: dict) -> None:
        kind, job_id = message.get("t"), message.get("job")
        if kind in ("started", "progress", "published"):
            self.last_progress = time.monotonic()
        if kind == "ready" and self.paused:
            self.worker.send({"op": "pause"})
        elif kind == "started" and job_id:
            self.jobs.started(job_id)
        elif kind == "progress" and job_id:
            self.jobs.progress(job_id, message.get("progress") or {}, message.get("phase"))
        elif kind == "published":
            entry = {k: message.get(k) for k in ("phase", "source_id", "data_rev",
                                                 "inventory_rev", "counts", "freshness")}
            self.jobs.published(job_id, entry)
            self.on_published(entry)
        elif kind == "done" and job_id:
            with self.lock:
                if self.current == job_id:
                    self.current = None
            self.jobs.finished(job_id, message.get("status", "failed"),
                               message.get("results") or [], message.get("error"))

    def _exit(self, reason: str | None) -> None:
        with self.lock:
            if self.pending is not None:
                return  # Not yet delivered: the job is sent to the next worker.
            job_id, self.current = self.current, None
        if job_id is None:
            return
        if reason == "stalled":
            minutes = round(self.config.ingest_stall_s / 60)
            self.jobs.interrupted(job_id, "job_stalled",
                                  f"导入 {minutes} 分钟没有任何进展，已停止；可以重试")
            return
        self.jobs.interrupted(job_id, "worker_exited",
                              f"ingest worker exited ({reason or 'crash'})")

    def stop(self) -> None:
        self.worker.stop()


@dataclass
class AnalysisTask:
    id: str
    section: str
    scope: dict
    params: dict
    scope_hash: str
    priority: str
    data_rev: int
    inventory_rev: int
    rules: str
    attempts: int = 0
    status: str = "queued"
    error: dict | None = None
    dispatched_at: float | None = None
    events: int | None = None
    rss: int | None = None
    preemptions: int = 0
    done: threading.Event = field(default_factory=threading.Event)

    @property
    def merge_key(self) -> tuple:
        return (self.section, self.scope_hash, self.data_rev, self.inventory_rev, self.rules)

    @property
    def snapshot_key(self) -> SnapshotKey:
        return SnapshotKey(self.section, self.scope_hash, self.data_rev, self.inventory_rev,
                           self.rules)


RECENT_JOBS = 256


class AnalysisQueue:
    """Priority queue (interactive > prewarm) with same-key merging and a circuit breaker."""

    def __init__(self, home: Path, config: SupervisorConfig, snapshots: SnapshotStore,
                 publish, on_state, ingest: IngestRunner | None = None):
        self.config, self.snapshots, self.publish, self.ingest = config, snapshots, publish, ingest
        self.lock = threading.RLock()
        self.pending: list[AnalysisTask] = []
        self.tasks: dict[tuple, AnalysisTask] = {}
        self.running: AnalysisTask | None = None
        self.failures: dict[tuple, dict] = {}
        self.dispatched: dict[tuple, int] = {}
        self.home = home
        self.open_runs: set[str] = set()
        self.recent: dict[str, AnalysisTask] = {}  # job_id → task, newest RECENT_JOBS kept.
        self.worker = WorkerProcess("analysis", home, config, self._message, self._exit,
                                    on_state, self._dispatch)

    # -- submission ------------------------------------------------------------------------
    def failure(self, section: str, scope_hash: str, rev: tuple[int, int]) -> dict | None:
        with self.lock:
            record = self.failures.get((section, scope_hash))
            return dict(record) if record and record["rev"] == rev else None

    def progress_of(self, job_id: str | None) -> dict | None:
        """``progress`` for a queued or running job id (None once it finished)."""
        with self.lock:
            task = next((t for t in self.tasks.values() if t.id == job_id), None)
        return self.progress(task) if task is not None else None

    def progress(self, task: AnalysisTask) -> dict:
        """What a 202 reports: queue position or elapsed time against the budget, the sized
        event count and the previous failure of the same key, so a client sees progress
        and a bounded end instead of an open-ended ``computing``."""
        with self.lock:
            record = self.failures.get((task.section, task.scope_hash))
            info = {"status": task.status, "attempt": self.dispatched.get(task.merge_key, 0),
                    "events": task.events,
                    "last_error": (record or {}).get("error", {}).get("code")
                    if record and record["rev"] == (task.data_rev, task.inventory_rev) else None}
            if task.status == "queued":
                order = sorted(self.pending, key=lambda t: t.priority != "interactive")
                info["queue_position"] = order.index(task) if task in order else None
            elif task.dispatched_at is not None:
                info["elapsed_s"] = round(time.monotonic() - task.dispatched_at, 1)
                info["budget_s"] = round(self._budget(task)[0], 1)
                info["rss_bytes"] = task.rss
            return info

    def circuit_open(self, section: str, scope_hash: str, rev: tuple[int, int]) -> bool:
        record = self.failure(section, scope_hash, rev)
        spec = SECTIONS.get(section)
        limit = (spec.max_failures if spec is not None and spec.max_failures is not None
                 else self.config.max_failures)
        return bool(record and record["count"] >= limit)

    def job(self, job_id: str) -> dict | None:
        """Status of a recent analysis task (the ``job_id`` a 202 response carries)."""
        with self.lock:
            task = self.recent.get(job_id)
            if task is None:
                return None
            started = task.dispatched_at
            return {"id": task.id, "kind": "analysis", "section": task.section,
                    "scope_hash": task.scope_hash, "status": task.status,
                    "priority": task.priority, "data_rev": task.data_rev,
                    "elapsed_s": (round(time.monotonic() - started, 1)
                                  if started is not None and task.status == "running" else None),
                    "timeout_s": self._timeout_for(task), "error": task.error}

    def clear_failures(self, section: str, scope_hash: str) -> None:
        with self.lock:
            self.failures.pop((section, scope_hash), None)

    def submit(self, section: str, scope: dict, params: dict, scope_hash: str, priority: str,
               rev: tuple[int, int], rules: str) -> AnalysisTask | None:
        if section not in SECTIONS:
            raise KeyError(section)
        with self.lock:
            if self.circuit_open(section, scope_hash, rev):
                return None
            task = AnalysisTask(uuid.uuid4().hex, section, scope, params, scope_hash, priority,
                                rev[0], rev[1], rules)
            existing = self.tasks.get(task.merge_key)
            if existing is not None:
                if priority == "interactive" and existing.priority == "prewarm":
                    existing.priority = "interactive"  # Promote; the same computation serves both.
                return existing
            self.tasks[task.merge_key] = task
            self.recent[task.id] = task
            while len(self.recent) > RECENT_JOBS:
                self.recent.pop(next(iter(self.recent)))
            self.pending.append(task)
            running = self.running
            if (priority == "interactive" and running is not None
                    and running.priority == "prewarm"
                    and running.preemptions < self.config.max_preemptions):
                # The prewarm goes back to the queue (behind the interactive task) instead
                # of being lost; after ``max_preemptions`` it is allowed to finish.
                running.preemptions += 1
                running.status, running.dispatched_at = "queued", None
                self.pending.append(running)
                self.running = None
                self.worker.kill("preempted")
                return task  # The exit callback dispatches the interactive task.
            self._dispatch()
            return task

    def _drop(self, task: AnalysisTask, status: str) -> None:
        task.status = status
        self.tasks.pop(task.merge_key, None)
        task.done.set()

    def _budget(self, task: AnalysisTask) -> tuple[float, bool]:
        """(seconds, capped): base budget plus the per-event allowance, doubled for each
        earlier timeout of the same key and revision, at most ``max_budget_s``."""
        section = SECTIONS[task.section]
        heavy = section.cost == "heavy"
        base = self.config.heavy_timeout_s if heavy else self.config.light_timeout_s
        if section.timeout_s is not None:
            base = section.timeout_s  # sections that declare their own budget
        wanted = base
        if task.events:
            rate = self.config.heavy_s_per_kevent if heavy else self.config.light_s_per_kevent
            wanted += rate * task.events / 1000
        record = self.failure(task.section, task.scope_hash, (task.data_rev, task.inventory_rev))
        # A scope that outgrew the budget gets more time on each retry instead of being
        # killed at the same point three times in a row.
        wanted *= 2 ** (record or {}).get("timeouts", 0)
        cap = max(base, self.config.max_budget_s)
        return min(wanted, cap), wanted > cap

    def _timeout_for(self, task: AnalysisTask) -> float:
        return self._budget(task)[0]

    def _dispatch(self) -> None:
        with self.lock:
            if self.running is not None:
                return
            if not self.pending:
                if self.ingest is not None:
                    self.ingest.pause(False)
                return
            task = next((t for t in self.pending if t.priority == "interactive"), self.pending[0])
            if task.priority == "interactive" and self.worker.niced and self.worker.running():
                self.worker.kill("renice")  # A lowered-priority worker cannot raise itself.
                return
            if not self.worker.ensure():
                if self.worker.state == "degraded":
                    for waiting in list(self.pending):
                        waiting.error = {"code": "service_unavailable",
                                         "message": "analysis worker degraded", "retryable": True}
                        self._drop(waiting, "failed")
                    self.pending.clear()
                return
            self.pending.remove(task)
            task.status, task.dispatched_at = "running", time.monotonic()
            self.running = task
            self.dispatched[task.merge_key] = self.dispatched.get(task.merge_key, 0) + 1
            if task.priority == "interactive" and self.ingest is not None:
                self.ingest.pause(True)  # rest batches yield to interactive analysis.
            self.worker.send({"op": "run", "job": {
                "id": task.id, "section": task.section, "scope": task.scope,
                "params": task.params, "priority": task.priority, "rev": task.data_rev}})

    # -- worker callbacks -----------------------------------------------------------------
    def _record_failure(self, task: AnalysisTask, error: dict) -> None:
        key = (task.section, task.scope_hash)
        rev = (task.data_rev, task.inventory_rev)
        record = self.failures.get(key)
        if record is None or record["rev"] != rev:
            record = {"rev": rev, "count": 0}
        record.update(count=record["count"] + 1, error=error)
        if error.get("code") == "timeout":
            record["timeouts"] = record.get("timeouts", 0) + 1
        self.failures[key] = record

    def _abort_running(self, error: dict, reason: str) -> None:
        """Fail the in-flight task without a rerun and kill its worker (lock held)."""
        task, self.running = self.running, None
        if task is None:
            return
        task.error = error
        self._record_failure(task, error)
        self._drop(task, "failed")
        self.publish("analysis", "analysis.failed", {
            "section": task.section, "scope_hash": task.scope_hash,
            "code": error["code"], "job_id": task.id})
        self.worker.kill(reason)

    def _fail_open_runs(self, reason: str) -> None:
        """A killed worker never reaches the run's ``except``: close its runs here."""
        with self.lock:
            runs, self.open_runs = self.open_runs, set()
        if not runs:
            return
        try:
            from tandem_data.analysis_history import AnalysisHistory

            AnalysisHistory(self.home / "analysis.sqlite").fail_runs(
                runs, f"analysis worker exited ({reason})")
        except Exception:  # noqa: BLE001  history is best effort; never break supervision
            pass

    def fail_stale_runs(self) -> int:
        """Gateway start: runs older than any budget belong to a process that is gone."""
        path = self.home / "analysis.sqlite"
        if not path.exists():
            return 0
        try:
            from tandem_data.analysis_history import AnalysisHistory

            older = int((self.config.max_budget_s + 60) * 1000)
            return AnalysisHistory(path).fail_stale(
                older_than_ms=older, reason="analysis process exited before finishing")
        except Exception:  # noqa: BLE001
            return 0

    def _message(self, message: dict) -> None:
        kind = message.get("t")
        if kind == "run" and message.get("run_id"):
            with self.lock:
                (self.open_runs.add if message.get("active") else self.open_runs.discard)(
                    message["run_id"])
            return
        if kind == "hb":
            rss = int(message.get("rss") or 0)
            with self.lock:
                task = self.running
                if task is None or message.get("job") != task.id or not message.get("live"):
                    return
                task.rss = rss
                if rss > self.config.rss_kill_bytes:
                    self._abort_running({
                        "code": "analysis_scope_too_large", "retryable": False,
                        "message": f"analysis used {rss // 1_000_000} MB, over the "
                                   f"{self.config.rss_kill_bytes // 1_000_000} MB worker limit; "
                                   "narrow the time window, projects or sessions"}, "rss_limit")
            return
        if message.get("t") == "sized":
            with self.lock:
                task = self.running
                if task is not None and task.id == message.get("job"):
                    events = message.get("events")
                    task.events = events if isinstance(events, int) and events >= 0 else None
            return
        if message.get("t") != "done":
            return
        with self.lock:
            task = self.running
            if task is None or task.id != message.get("job"):
                return
            self.running = None
            self.worker.niced = bool(message.get("niced"))
            if message.get("status") == "completed":
                self.snapshots.put(task.snapshot_key, message.get("body") or {},
                                   duration_ms=int(message.get("duration_ms") or 0))
                self.failures.pop((task.section, task.scope_hash), None)
                self._drop(task, "completed")
                self.publish("analysis", "analysis.ready", {
                    "section": task.section, "scope_hash": task.scope_hash,
                    "rev": task.data_rev, "job_id": task.id})
            else:
                error = message.get("error") or {"code": "analysis_failed", "retryable": True}
                task.error = error
                if error.get("code") != "projection_pending":  # Transient: not a strike.
                    self._record_failure(task, error)
                self._drop(task, "failed")
                self.publish("analysis", "analysis.failed", {
                    "section": task.section, "scope_hash": task.scope_hash,
                    "code": error.get("code"), "job_id": task.id})
            # Prefer the live tree RSS: the peak never drops once one large task ran.
            rss = message.get("rss_now")
            if int(rss if rss is not None else message.get("rss") or 0) > self.config.rss_limit_bytes:
                self.worker.kill("rss_recycle")
                return
        self._dispatch()

    def _exit(self, reason: str | None) -> None:
        self._fail_open_runs(reason or "crash")
        with self.lock:
            task, self.running = self.running, None
            if task is not None:
                task.attempts += 1
                if task.attempts <= 1:
                    task.status = "queued"  # Idempotent: rerun once after a crash.
                    self.pending.insert(0, task)
                else:
                    task.error = {"code": "worker_crashed", "message": "analysis worker exited",
                                  "retryable": True}
                    self._record_failure(task, task.error)
                    self._drop(task, "failed")
                    self.publish("analysis", "analysis.failed", {
                        "section": task.section, "scope_hash": task.scope_hash,
                        "code": "worker_crashed", "job_id": task.id})
        if reason is not None:
            self._dispatch()  # Intentional stops respawn at once; crashes wait for backoff.

    def check(self) -> None:
        """Watchdog tick: enforce the per-task timeout and recycle an idle worker."""
        with self.lock:
            task = self.running
            now = time.monotonic()
            if task is not None and task.dispatched_at is not None and (
                    now - task.dispatched_at > self._timeout_for(task)):
                self.running = None
                budget, capped = self._budget(task)
                size = f" ({task.events} events)" if task.events is not None else ""
                if capped:
                    task.error = {"code": "analysis_scope_too_large", "retryable": False,
                                  "events": task.events, "message":
                                  f"Scope too large{size}: analysis exceeded {budget:.0f} s; "
                                  "narrow the time window, projects or sessions"}
                else:
                    task.error = {"code": "timeout", "retryable": True, "events": task.events,
                                  "message": f"analysis exceeded its {budget:.0f} s budget{size}"}
                self._record_failure(task, task.error)
                self._drop(task, "failed")
                self.publish("analysis", "analysis.failed", {
                    "section": task.section, "scope_hash": task.scope_hash,
                    "code": task.error["code"], "job_id": task.id})
                self.worker.kill("timeout")
            elif (task is None and not self.pending and self.worker.running()
                  and now - self.worker.last_activity > self.config.analysis_idle_s):
                self.worker.kill("idle")

    def stop(self) -> None:
        self.worker.stop()
        with self.lock:
            for task in [*self.pending, *([self.running] if self.running else [])]:
                task.error = {"code": "service_stopped", "retryable": True}
                self._drop(task, "failed")
            self.pending.clear()
            self.running = None


class Supervisor:
    """Owns both workers and the watchdog thread; publishes ``service`` events."""

    def __init__(self, home: Path, config: SupervisorConfig, snapshots: SnapshotStore,
                 publish, on_published):
        self.config = config
        self.publish = publish
        self.ingest = IngestRunner(home, config, self._state, on_published)
        self.analysis = AnalysisQueue(home, config, snapshots, publish, self._state, self.ingest)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True, name="supervisor")

    def _state(self, role: str, state: str) -> None:
        self.publish("service", "service", {"name": role, "state": state})

    def start(self) -> None:
        self.thread.start()
        threading.Thread(target=self.analysis.fail_stale_runs, daemon=True,
                         name="analysis-stale-runs").start()

    def _watch(self) -> None:
        while not self.stopping.wait(self.config.tick_s):
            now = time.monotonic()
            for worker in (self.ingest.worker, self.analysis.worker):
                with worker.lock:
                    hung = (worker.running() and worker.expected_exit is None
                            and now - worker.last_hb > self.config.stale_s)
                if hung:
                    worker.kill(None)  # Counts as a crash: backoff restart, in-flight requeue.
            self.ingest.check(now)
            self.analysis.check()

    def services(self) -> dict:
        return {"ingest": self.ingest.worker.info(), "analysis": self.analysis.worker.info()}

    def stop(self) -> None:
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join()
        self.ingest.stop()
        self.analysis.stop()
