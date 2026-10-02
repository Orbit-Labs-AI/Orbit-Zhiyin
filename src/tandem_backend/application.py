"""Single-process desktop lifecycle. Personal state is atomic, private and local."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tandem_data.contract import now_ms, uid
from tandem_data.discovery import candidates, inputs
from tandem_data.query import current_projection
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store, readonly_connection


class DesktopService:
    """Own one task queue; each worker opens its own canonical database connection."""

    def __init__(self, home: Path):
        self.home = home.expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_file = open(self.home / "desktop.lock", "a+")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            raise RuntimeError("Another Tandem desktop service is active") from None
        self.state_path = self.home / "app-state.json"
        self.lock = threading.RLock()
        self.state = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {"sources": {}, "jobs": {}, "settings": {"onboarded": False, "recent_days": 90}}
        )
        self.cancels: dict[str, threading.Event] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tandem-import")
        for job in self.state["jobs"].values():
            if job["status"] in ("queued", "running"):
                job.update(status="interrupted", error={"code": "app_restarted", "retryable": True})
        with Store(self.home) as store:
            if not store.db.execute("SELECT 1 FROM projection_run LIMIT 1").fetchone():
                with ImportService(store).writer():
                    store.rebuild()
        self._save()
        self.stopping = threading.Event()
        self.watcher = threading.Thread(target=self._watch, daemon=True, name="tandem-watch")
        self.watcher.start()

    def _watch(self):
        while not self.stopping.wait(15):
            with self.lock:
                selected = [k for k, s in self.state["sources"].items() if s["enabled"]]
                live = self.state["settings"].get("sync_mode") == "live"
            if live and selected:
                try:
                    self.submit("import", selected)
                except RuntimeError:
                    pass  # Active user jobs take priority over polling.

    def _save(self):
        """Caller holds lock; replacement avoids a half-written lifecycle journal."""
        temporary = self.state_path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(self.state, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.state_path)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def discover(self):
        """Discovery reads names and file stats, not session bodies or credentials."""
        result = []
        for source in candidates():
            key = uid("source", source["agent"], source["root"])
            try:
                count = sum(
                    1
                    for item in inputs(source["agent"], Path(source["root"]))
                    if item.role in ("transcript", "subagent_transcript")
                )
                status = "available" if count else "empty"
            except OSError:
                count, status = None, "permission_denied"
            result.append(
                {
                    **source,
                    "id": key,
                    "files": count,
                    "status": status,
                    "enabled": self.state["sources"].get(key, {}).get("enabled", False),
                }
            )
        return result

    def configure(self, agent: str, root: str, enabled=True):
        from tandem_data.connectors import MAPPERS

        if agent not in MAPPERS:
            raise ValueError("Unsupported agent")
        path = Path(root).expanduser().resolve(strict=enabled)
        if (
            enabled
            and not path.is_dir()
            or path == Path.home()
            or self.home.is_relative_to(path)
            or path.is_relative_to(self.home)
        ):
            raise ValueError(
                "Choose a separate Agent directory, not the user home or Tandem storage"
            )
        key = uid("source", agent, str(path))
        with self.lock:
            self.state["sources"][key] = {
                **self.state["sources"].get(key, {}),
                "id": key,
                "agent": agent,
                "root": str(path),
                "enabled": enabled,
            }
            self._save()
            return dict(self.state["sources"][key])

    def settings(self, values):
        with self.lock:
            self.state["settings"].update(values)
            self._save()
            return dict(self.state["settings"])

    def submit(self, kind: str, source_ids=(), limit=None, files_by_source=None):
        files_by_source = files_by_source or {}
        if set(files_by_source) - set(source_ids):
            raise ValueError("File selection must belong to selected sources")
        with self.lock:
            if any(j["status"] in ("queued", "running") for j in self.state["jobs"].values()):
                raise RuntimeError("An application job is already active")
            sources = [self.state["sources"].get(key) for key in source_ids]
            if kind in ("import", "inventory") and (
                not sources or any(not s or not s["enabled"] for s in sources)
            ):
                raise ValueError("Select at least one enabled source")
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                "kind": kind,
                "status": "queued",
                "created_at": now_ms(),
                "source_ids": list(source_ids),
                "selection": "sample" if limit or files_by_source else "full",
                "limit": limit,
                "files_by_source": files_by_source,
                "progress": {},
                "results": [],
                "error": None,
            }
            self.state["jobs"][job_id] = job
            # Retain a bounded journal; imported records have their own durable ledger.
            terminal = [
                k for k, v in self.state["jobs"].items() if v["status"] not in ("queued", "running")
            ]
            for key in terminal[:-100]:
                del self.state["jobs"][key]
            stop = self.cancels[job_id] = threading.Event()
            self._save()
            self.executor.submit(
                self._run, job_id, kind, [dict(s) for s in sources], limit, stop, files_by_source
            )
            return dict(job)

    def _update(self, job_id, **values):
        with self.lock:
            self.state["jobs"][job_id].update(values)
            self._save()

    def _run(self, job_id, kind, sources, limit, stop, files_by_source):
        self._update(job_id, status="running", started_at=now_ms())
        results = []
        try:
            with Store(self.home) as store:
                service = ImportService(store, progress=lambda p: self._update(job_id, progress=p))
                if kind in ("verify", "rebuild", "backup"):
                    with service.writer():
                        if kind == "verify":
                            results.append(store.verify())
                        elif kind == "rebuild":
                            results.append(store.rebuild())
                        else:
                            results.append(self._backup(store))
                for source in sources:
                    if stop.is_set():
                        break
                    try:
                        if kind == "inventory":
                            from tandem_data.inventory import InventoryRequest, scan_inventory

                            result = scan_inventory(
                                store, InventoryRequest(source["agent"], Path(source["root"]))
                            )
                        else:
                            result = service.import_source(
                                ImportRequest(
                                    source["agent"],
                                    Path(source["root"]),
                                    files=tuple(Path(p) for p in files_by_source[source["id"]])
                                    if source["id"] in files_by_source
                                    else None,
                                    limit=limit,
                                ),
                                stop,
                            )
                        result = {"source_id": source["id"], **result}
                        with self.lock:
                            self.state["sources"][source["id"]].update(
                                last_import_at=now_ms(), last_result=result
                            )
                            self._save()
                        results.append(result)
                    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                        results.append(
                            {
                                "source_id": source["id"],
                                "error": {"code": type(error).__name__, "retryable": True},
                            }
                        )
                    self._update(job_id, results=results)
            partial = any(
                r.get("error")
                or r.get("capture_errors")
                or r.get("current_unparsed")
                or r.get("unparsed")
                or r.get("status") == "partial"
                for r in results
            )
            self._update(
                job_id,
                status="cancelled" if stop.is_set() else "partial" if partial else "completed",
                results=results,
                finished_at=now_ms(),
            )
        except Exception as error:
            self._update(
                job_id,
                status="failed",
                results=results,
                finished_at=now_ms(),
                error={"code": type(error).__name__, "retryable": True},
            )
        finally:
            with self.lock:
                self.cancels.pop(job_id, None)

    def _backup(self, store):
        """Backup while holding the writer lock; include immutable archives and app state."""
        import shutil

        target = self.home / "backups" / str(now_ms())
        target.mkdir(parents=True, mode=0o700)
        with sqlite3.connect(target / "tandem.db") as destination:
            store.db.backup(destination)
        os.chmod(target / "tandem.db", 0o600)
        shutil.copytree(self.home / "raw", target / "raw")
        shutil.copy2(self.state_path, target / "app-state.json")
        return {"path": str(target), "status": "available"}

    def retry(self, job_id):
        with self.lock:
            job = self.state["jobs"].get(job_id)
            if job is None:
                raise KeyError(job_id)
            return self.submit(
                job["kind"], job["source_ids"], job.get("limit"), job.get("files_by_source")
            )

    def cancel(self, job_id):
        with self.lock:
            if job_id not in self.state["jobs"]:
                raise KeyError(job_id)
            if job_id in self.cancels:
                self.cancels[job_id].set()
                self.state["jobs"][job_id]["cancel_requested"] = True
                self._save()
            return dict(self.state["jobs"][job_id])

    def storage(self):
        """Database status remains readable even when a projection needs rebuilding."""
        with readonly_connection(self.home / "tandem.db") as db:
            db.execute("BEGIN")
            try:
                _, run = current_projection(db)
                readiness, revision = "ready", run["run_id"]
            except ValueError:
                readiness, revision = "rebuild_required", None
            tables = (
                "source",
                "source_file",
                "source_revision",
                "raw_record",
                "event",
                "session",
                "turn",
                "tool_call",
                "model_call",
                "archive_blob",
            )
            counts = {
                name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in tables
            }
            sources = [
                dict(r)
                for r in db.execute(
                    "SELECT s.source_id,s.agent,COUNT(t.session_uid) AS sessions FROM source s LEFT JOIN session t USING(source_id) GROUP BY s.source_id"
                )
            ]
            return {
                "readiness": readiness,
                "projection_run_id": revision,
                "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
                "tables": counts,
                "sources": sources,
                "archive_bytes": db.execute(
                    "SELECT COALESCE(SUM(stored_len),0) FROM archive_blob"
                ).fetchone()[0],
                "database_bytes": (self.home / "tandem.db").stat().st_size,
                "home": str(self.home),
            }

    def close(self):
        self.stopping.set()
        self.watcher.join()
        for stop in list(self.cancels.values()):
            stop.set()
        self.executor.shutdown(wait=True)
        self.lock_file.close()
