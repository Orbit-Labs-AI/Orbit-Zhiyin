"""Application state and the job state machine, persisted atomically to app-state.json.

Same paths, job fields and statuses as ``orbit_data``'s DesktopService. Execution goes
through the ``JobRunner`` seam, which the gateway binds to the ingest worker subprocess.

A damaged ``app-state.json`` (truncated, not JSON, not an object) never stops the app: it is
renamed to ``app-state.json.corrupt-<ms>`` for the user/support to inspect and the state
starts from defaults (onboarding shows again). A leftover ``app-state.tmp`` from a crash
before the atomic replace is only used when the main file is missing and the temporary
file parses completely (it was fsynced before replace); otherwise it is discarded.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from orbit_data.contract import now_ms, uid

from orbit_backend.platform.logs import log_event

log = logging.getLogger(__name__)
STATUSES = ("queued", "running", "completed", "partial", "cancelled", "failed", "interrupted")
ACTIVE = frozenset({"queued", "running"})
TRANSITIONS = {
    "queued": {"running", "cancelled", "failed", "interrupted"},
    "running": {"completed", "partial", "cancelled", "failed", "interrupted"},
}
KINDS = ("import", "inventory", "rebuild", "verify", "backup")
IMPORT_PHASES = ("auto", "full", "head", "window", "rest")
SETTINGS_KEYS = {"onboarded": bool, "recent_days": int, "default_range_days": int,
                 "sync_mode": str, "weekly_report": bool, "onboarding_step": int}
SYNC_MODES = ("off", "hour", "live")
# (minimum, maximum) for integer settings; ``None`` is accepted where listed in NULLABLE.
INT_RANGES = {"recent_days": (1, 36_500), "default_range_days": (0, 36_500),
              "onboarding_step": (0, 4)}
NULLABLE = frozenset({"recent_days"})  # None: import the whole history.
JOURNAL_LIMIT = 100


class JobConflict(RuntimeError):
    """Another write job is already queued or running."""


class JobRunner(Protocol):
    """Seam between the state machine and whatever executes a job."""

    def start(self, job: dict, sources: list[dict]) -> None: ...

    def cancel(self, job_id: str) -> None: ...


def _default_state() -> dict:
    return {"sources": {}, "jobs": {}, "mru_scopes": [],
            "settings": {"onboarded": False, "recent_days": 90, "default_range_days": 30,
                         "sync_mode": "off", "weekly_report": False, "onboarding_step": 0}}


class AppState:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.last_save = 0.0
        state = _default_state()
        self.recovered: dict | None = None
        loaded = self._load()
        if loaded is not None:
            state.update({k: v for k, v in loaded.items() if k in state})
            state["settings"] = {**_default_state()["settings"], **loaded.get("settings", {})}
        self.state = state
        for job in self.state["jobs"].values():
            if job["status"] in ACTIVE:
                # Restart never resumes or widens a job silently; the user retries it.
                job.update(status="interrupted", finished_at=now_ms(),
                           error={"code": "app_restarted", "message": "应用重启时任务未完成",
                                  "retryable": True})
        self.save()

    def _read(self, path: Path) -> dict:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not all(
                isinstance(loaded.get(k, {}), dict) for k in ("sources", "jobs", "settings")):
            raise ValueError("app state is not an object of the expected shape")
        return loaded

    def _load(self) -> dict | None:
        temporary = self.path.with_suffix(".tmp")
        if not self.path.exists():
            if not temporary.exists():
                return None
            try:
                loaded = self._read(temporary)
            except (OSError, ValueError):
                temporary.unlink(missing_ok=True)
                return None
            temporary.replace(self.path)
            self.recovered = {"reason": "restored_tmp"}
            return loaded
        temporary.unlink(missing_ok=True)  # half-written leftover; the main file is the truth
        try:
            return self._read(self.path)
        except (OSError, ValueError) as error:  # UnicodeDecodeError / JSONDecodeError are ValueError
            backup = self.path.with_name(f"{self.path.name}.corrupt-{now_ms()}")
            try:
                self.path.replace(backup)
            except OSError:
                backup = None
            log.warning("app-state.json unreadable (%s); starting from defaults, backup=%s", error, backup)
            self.recovered = {"reason": "corrupt", "backup": backup and backup.name,
                              "error": f"{type(error).__name__}: {error}"[:200]}
            return None

    def save(self) -> None:
        """Atomic replace so a crash never leaves a half-written journal."""
        with self.lock:
            temporary = self.path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(self.state, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            self.last_save = time.monotonic()

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state))

    # -- sources and settings ------------------------------------------------------------
    def configure(self, agent: str, root: str, enabled: bool, home: Path) -> dict:
        from orbit_data.connectors import MAPPERS

        if agent not in MAPPERS:
            raise ValueError("Unsupported agent")
        path = Path(root).expanduser().resolve(strict=enabled)
        if ((enabled and not path.is_dir()) or path == Path.home()
                or home.is_relative_to(path) or path.is_relative_to(home)):
            raise ValueError("Choose a separate Agent directory, not the user home or Orbit storage")
        key = uid("source", agent, str(path))
        with self.lock:
            self.state["sources"][key] = {**self.state["sources"].get(key, {}), "id": key,
                                          "agent": agent, "root": str(path), "enabled": enabled}
            self.save()
            return dict(self.state["sources"][key])

    def update_settings(self, values: dict) -> dict:
        for key, value in values.items():
            expected = SETTINGS_KEYS.get(key)
            if expected is None:
                raise ValueError(f"Invalid setting {key}")
            if value is None and key in NULLABLE:
                continue
            if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
                raise ValueError(f"Invalid setting {key}")
            if key in INT_RANGES and not INT_RANGES[key][0] <= value <= INT_RANGES[key][1]:
                low, high = INT_RANGES[key]
                raise ValueError(f"{key} must be within {low}..{high}")
            if key == "sync_mode" and value not in SYNC_MODES:
                raise ValueError("sync_mode must be off, hour or live")
        with self.lock:
            self.state["settings"].update(values)
            self.save()
            return dict(self.state["settings"])

    def _plan(self) -> dict:
        """Import plan overrides from settings: ``recent_days`` bounds file age (None: all)."""
        days = self.state["settings"].get("recent_days")
        return {"max_age_days": days} if days else {}

    def remember_scope(self, scope: dict, limit: int = 5) -> None:
        """MRU of analysed scopes for prewarm; persisted with the next save."""
        with self.lock:
            mru = [s for s in self.state["mru_scopes"] if s != scope]
            self.state["mru_scopes"] = [scope, *mru][:limit]

    # -- jobs ------------------------------------------------------------------------------
    def create_job(self, kind: str, source_ids=(), limit=None, files_by_source=None,
                   phase: str | None = None, origin: str = "user") -> tuple[dict, list[dict]]:
        files_by_source = files_by_source or {}
        if kind not in KINDS:
            raise ValueError("Unknown job kind")
        if set(files_by_source) - set(source_ids):
            raise ValueError("File selection must belong to selected sources")
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise ValueError("limit must be a positive integer")
        if phase is not None and (kind != "import" or phase not in IMPORT_PHASES):
            raise ValueError("phase applies to import jobs: auto, full, head, window or rest")
        with self.lock:
            if any(j["status"] in ACTIVE for j in self.state["jobs"].values()):
                raise JobConflict("An application job is already active")
            sources = [self.state["sources"].get(key) for key in source_ids]
            if any(source is None for source in sources):
                raise ValueError("Unknown source")
            if kind in ("verify", "backup") and source_ids:
                raise ValueError("This maintenance job operates on the whole data home")
            if kind in ("verify", "backup", "rebuild") and (limit or files_by_source):
                raise ValueError("Maintenance does not read selected upstream files")
            if kind in ("import", "inventory") and (
                    not sources or any(not s["enabled"] for s in sources)):
                raise ValueError("Select at least one enabled source")
            job = {"id": uuid.uuid4().hex, "kind": kind, "status": "queued",
                   "created_at": now_ms(), "source_ids": list(source_ids),
                   "selection": "sample" if limit or files_by_source else "full",
                   "limit": limit, "files_by_source": files_by_source,
                   "phase": (phase or "auto") if kind == "import" else None, "origin": origin,
                   "plan": self._plan() if kind == "import" else {},
                   "started_at": None, "finished_at": None, "cancel_requested": False,
                   "progress": {}, "results": [], "published": [], "error": None}
            self.state["jobs"][job["id"]] = job
            terminal = [k for k, v in self.state["jobs"].items() if v["status"] not in ACTIVE]
            for key in terminal[:-JOURNAL_LIMIT]:
                del self.state["jobs"][key]
            self.save()
            return dict(job), [dict(s) for s in sources]

    def job(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.state["jobs"]:
                raise KeyError(job_id)
            return json.loads(json.dumps(self.state["jobs"][job_id]))

    def jobs(self) -> list[dict]:
        with self.lock:
            return sorted(self.snapshot()["jobs"].values(), key=lambda j: j["created_at"],
                          reverse=True)

    def latest_job(self, origin: str) -> dict | None:
        """Newest job with ``origin`` (a copy), without copying the whole job table."""
        with self.lock:
            jobs = [j for j in self.state["jobs"].values() if j.get("origin") == origin]
            newest = max(jobs, key=lambda j: j["created_at"], default=None)
            return json.loads(json.dumps(newest)) if newest is not None else None

    def active_job(self) -> dict | None:
        with self.lock:
            return next((dict(j) for j in self.state["jobs"].values() if j["status"] in ACTIVE),
                        None)

    def transition(self, job_id: str, status: str, **fields) -> dict:
        with self.lock:
            job = self.state["jobs"][job_id]
            if status != job["status"]:
                if status not in TRANSITIONS.get(job["status"], ()):
                    raise ValueError(f"Illegal job transition {job['status']} -> {status}")
                job["status"] = status
                if status not in ACTIVE:
                    job["finished_at"] = now_ms()
            job.update(fields)
            self.save()
            return dict(job)

    def update(self, job_id: str, *, throttle_s: float = 0.0, **fields) -> dict:
        with self.lock:
            job = self.state["jobs"][job_id]
            job.update(fields)
            if time.monotonic() - self.last_save >= throttle_s:
                self.save()
            return dict(job)


class JobService:
    """Validates, records and dispatches jobs; reacts to runner callbacks; publishes SSE."""

    def __init__(self, state: AppState, runner: JobRunner, publish: Callable[..., int],
                 progress_interval_s: float = 0.25):
        self.state = state
        self.runner = runner
        self.publish = publish
        self.progress_interval_s = progress_interval_s
        self.progress_sent: dict[str, tuple[tuple, float]] = {}
        self.progress_counts: dict[str, dict[str, int]] = {}

    def _event(self, job: dict) -> None:
        self.publish("job", "job", {k: job.get(k) for k in (
            "id", "kind", "status", "progress", "phase", "origin", "error")})

    def submit(self, kind: str, source_ids=(), limit=None, files_by_source=None,
               phase: str | None = None, origin: str = "user") -> dict:
        job, sources = self.state.create_job(kind, source_ids, limit, files_by_source, phase,
                                             origin)
        self._event(job)
        try:
            self.runner.start(job, sources)
        except Exception as error:  # Runner unavailable (degraded): record, never hang queued.
            job = self.state.transition(job["id"], "failed", error={
                "code": "service_unavailable", "message": str(error), "retryable": True})
            self._event(job)
        return self.state.job(job["id"])

    def retry(self, job_id: str) -> dict:
        job = self.state.job(job_id)
        if job["status"] in ACTIVE:
            raise JobConflict("Job is still active")
        # Same sources, file selection, limit and phase: retry never widens the scope.
        return self.submit(job["kind"], job["source_ids"], job.get("limit"),
                           job.get("files_by_source"), job.get("phase"), origin="retry")

    def cancel(self, job_id: str) -> dict:
        job = self.state.job(job_id)
        if job["status"] in ACTIVE:
            job = self.state.update(job_id, cancel_requested=True)
            self.runner.cancel(job_id)
        return job

    # -- runner callbacks (worker reader thread) --------------------------------------
    def started(self, job_id: str) -> None:
        job = self.state.transition(job_id, "running", started_at=now_ms())
        self._event(job)

    def progress(self, job_id: str, progress: dict, phase: str | None = None) -> None:
        job = self.state.update(job_id, progress=progress, throttle_s=0.5,
                                **({"current_phase": phase} if phase else {}))
        # Coalesce: per-file progress would flood the 1000-frame SSE buffer. A new stage,
        # phase, source, batch or rebuild attempt and completion always go out; otherwise at
        # most one frame per interval.
        marker = (progress.get("stage"), phase, progress.get("step"), progress.get("batch"),
                  progress.get("attempt"))
        last = self.progress_sent.get(job_id)
        # Persist meaningful file outcomes before SSE coalescing. Unchanged files only
        # increment the final summary; routine syncs never log every unchanged path.
        counts = self.progress_counts.setdefault(job_id, {
            "captured": 0, "unchanged": 0, "failed": 0, "retries": 0})
        status = progress.get("status")
        if progress.get("stage") == "capture" and status in counts:
            counts[status] += 1
        retrying = progress.get("stage") == "capture_retry"
        if retrying:
            counts["retries"] += 1
        keys = ("stage", "source_agent", "source_id", "step", "batch", "attempt",
                "attempts", "completed", "total", "path", "status", "exception",
                "source_status", "errno", "sqlite_errorname", "retryable")
        fields = {key: value[:1024] if isinstance(value, str) else value
                  for key in keys if isinstance(value := progress.get(key), (str, int, float, bool))}
        if retrying or status in ("captured", "failed"):
            log_event("import_file_retry" if retrying else "import_file",
                      level=logging.WARNING if retrying or status == "failed" else logging.INFO,
                      job_id=job_id, origin=job.get("origin"), **fields)
        elif last is None or last[0] != marker:
            log_event("import_stage", job_id=job_id, origin=job.get("origin"),
                      **{key: value for key, value in fields.items() if key != "path"})
        now = time.monotonic()
        final = progress.get("total") is not None and progress.get("completed") == progress.get(
            "total")
        if last is not None and last[0] == marker and not final and (
                now - last[1] < self.progress_interval_s):
            return
        self.progress_sent[job_id] = (marker, now)
        # ``origin`` lets the UI tell a background sync (origin=sync) from an import the user
        # started; every job frame carries it, not only the status frames.
        self.publish("job", "job", {"id": job_id, "kind": job["kind"], "status": job["status"],
                                    "progress": progress, "phase": phase,
                                    "origin": job.get("origin")})

    def published(self, job_id: str | None, entry: dict) -> None:
        if job_id is None:
            return
        with self.state.lock:
            job = self.state.state["jobs"].get(job_id)
            if job is not None:
                job["published"] = [*job.get("published", []), entry]

    def finished(self, job_id: str, status: str, results: list, error: dict | None) -> None:
        self.progress_sent.pop(job_id, None)
        counts = self.progress_counts.pop(job_id, None)
        if counts is not None:
            log_event("import_summary", job_id=job_id, **counts)
        job = self.state.job(job_id)
        if job["status"] not in ACTIVE:
            return
        if job["status"] == "queued":
            self.state.transition(job_id, "running", started_at=now_ms())
        job = self.state.transition(job_id, status, results=results, error=error)
        self._event(job)
        if job["kind"] == "import" and status in ("completed", "partial"):
            with self.state.lock:
                for result in results:
                    source = self.state.state["sources"].get(result.get("source_id"))
                    if source is not None:
                        source.update(last_import_at=now_ms(), last_result=result)
                self.state.save()

    def interrupted(self, job_id: str, code: str, message: str) -> None:
        self.progress_sent.pop(job_id, None)
        counts = self.progress_counts.pop(job_id, None)
        if counts is not None:
            log_event("import_summary", job_id=job_id, **counts)
        job = self.state.job(job_id)
        if job["status"] not in ACTIVE:
            return
        job = self.state.transition(job_id, "interrupted", error={
            "code": code, "message": message, "retryable": True})
        self._event(job)
