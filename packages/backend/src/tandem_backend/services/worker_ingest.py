"""ingest worker: the only writer of tandem.db and raw/.

Runs one job at a time in a thread while the main thread reads control messages, so
cancel and pause arrive during an import. Import jobs with phase ``auto`` are split into
head / window / rest batches (``ingest_plan``); every batch publishes atomically and is
reported as ``published`` with the new ``data_rev``. ``rest`` waits between chunks while
paused. Cancellation is honoured between files (ImportService semantics).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import traceback
from pathlib import Path

from tandem_data.contract import now_ms
from tandem_data.service import ImportRequest, ImportService
from tandem_data.store import Store, readonly_connection

from .ingest_plan import Batch, plan_batches
from .worker_protocol import WorkerIO, debug_delay


def revision(home: Path) -> dict:
    """Published revision read back after a batch: run id, inventory scan and counts."""
    with readonly_connection(home / "tandem.db") as db:
        data_rev = db.execute("SELECT MAX(run_id) FROM projection_run").fetchone()[0]
        inventory_rev = db.execute("SELECT COALESCE(MAX(scan_id),0) FROM inventory_scan"
                                   ).fetchone()[0]
        counts = {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                  for name in ("session", "event", "project")}
    return {"data_rev": data_rev, "inventory_rev": inventory_rev,
            "counts": {"sessions": counts["session"], "events": counts["event"],
                       "projects": counts["project"]}}


def _partial(results: list[dict]) -> bool:
    return any(r.get("error") or r.get("capture_errors") or r.get("current_unparsed")
               or r.get("unparsed") or r.get("skipped_files") or r.get("status") == "partial"
               for r in results)


class IngestWorker:
    def __init__(self, home: Path, io: WorkerIO):
        self.home = home
        self.io = io
        self.cancel = threading.Event()
        self.resume = threading.Event()
        self.resume.set()
        self.thread: threading.Thread | None = None
        self.phase: str | None = None

    def serve(self) -> None:
        self.io.start_heartbeat()
        self.io.send("ready", role="ingest", pid=os.getpid())
        for message in self.io.ops():
            op = message.get("op")
            if op == "run":
                if self.thread is not None and self.thread.is_alive():
                    self.io.send("done", job=message["job"]["id"], status="failed", results=[],
                                 error={"code": "job_conflict", "message": "worker busy",
                                        "retryable": True})
                    continue
                self.cancel.clear()
                self.thread = threading.Thread(target=self.run, args=(message["job"],),
                                               name="ingest-job")
                self.thread.start()
            elif op == "cancel":
                self.cancel.set()
            elif op == "pause":
                self.resume.clear()
            elif op == "resume":
                self.resume.set()
            elif op == "shutdown":
                break
        # stdin closed or shutdown: stop at the next file boundary; published data stays.
        self.cancel.set()
        self.resume.set()
        if self.thread is not None:
            self.thread.join()

    def _batches(self, job: dict, source: dict) -> list[Batch | None]:
        if source["id"] in job.get("files_by_source", {}):
            return [Batch("selection", tuple(Path(p) for p in job["files_by_source"][source["id"]]))]
        phase = job.get("phase") or "auto"
        if phase == "full" or job.get("limit"):
            return [None]  # One request over every allowlisted file (or the first N).
        plan = plan_batches(source["agent"], Path(source["root"]), **job.get("plan", {}))
        return [b for b in plan if phase == "auto" or b.phase == phase]

    def run(self, job: dict) -> None:
        self.io.current_job = job["id"]
        debug_delay()
        self.io.send("started", job=job["id"])
        results: list[dict] = []
        try:
            with Store(self.home) as store:
                service = ImportService(store, progress=lambda p: self.io.send(
                    "progress", job=job["id"], progress=p, phase=self.phase))
                kind = job["kind"]
                if kind in ("verify", "rebuild", "backup"):
                    with service.writer():
                        if kind == "verify":
                            results.append({"kind": "verify", **store.verify()})
                        elif kind == "rebuild":
                            ids = {s["id"] for s in job.get("sources", [])} or None
                            results.append(store.rebuild(source_ids=ids, progress=service.progress))
                        else:
                            results.append(self._backup(store))
                    if kind == "rebuild":
                        self._publish(job, "rebuild")
                elif kind == "inventory":
                    from tandem_data.inventory import InventoryRequest, scan_inventory

                    for source in job["sources"]:
                        result = scan_inventory(store, InventoryRequest(source["agent"],
                                                                        Path(source["root"])))
                        results.append({"source_id": source["id"], **result})
                    self._publish(job, "inventory")
                else:
                    self._import(job, service, results)
            status = ("cancelled" if self.cancel.is_set() else
                      "partial" if _partial(results) else "completed")
            self.io.send("done", job=job["id"], status=status, results=results, error=None)
        except Exception as error:  # Reported as a failed job; the worker stays alive.
            traceback.print_exc()
            self.io.send("done", job=job["id"], status="failed", results=results, error={
                "code": type(error).__name__, "message": str(error)[:500], "retryable": True})
        finally:
            self.io.current_job = None

    def _import(self, job: dict, service: ImportService, results: list[dict]) -> None:
        for source in job["sources"]:
            for batch in self._batches(job, source):
                if self.cancel.is_set():
                    return
                while batch is not None and batch.phase == "rest" and not self.resume.wait(0.2):
                    if self.cancel.is_set():
                        return  # Paused rest yields to interactive work; cancel still wins.
                self.phase = batch.phase if batch else "full"
                try:
                    result = service.import_source(ImportRequest(
                        source["agent"], Path(source["root"]),
                        files=batch.files if batch is not None else None,
                        limit=job.get("limit")), self.cancel)
                    result = {"source_id": source["id"], "phase": self.phase, **result}
                except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                    result = {"source_id": source["id"], "phase": self.phase, "error": {
                        "code": type(error).__name__, "message": str(error)[:500],
                        "retryable": True}}
                results.append(result)
                if "error" not in result:
                    self._publish(job, self.phase, source["id"])

    def _publish(self, job: dict, phase: str, source_id: str | None = None) -> None:
        try:
            info = revision(self.home)
        except (sqlite3.Error, OSError):
            return
        if info["data_rev"] is not None:
            self.io.send("published", job=job["id"], phase=phase, source_id=source_id, **info)

    def _backup(self, store: Store) -> dict:
        target = self.home / "backups" / str(now_ms())
        target.mkdir(parents=True, mode=0o700)
        with sqlite3.connect(target / "tandem.db") as destination:
            store.db.backup(destination)
        os.chmod(target / "tandem.db", 0o600)
        if (self.home / "raw").exists():
            shutil.copytree(self.home / "raw", target / "raw")
        if (self.home / "app-state.json").exists():
            shutil.copy2(self.home / "app-state.json", target / "app-state.json")
        return {"path": str(target), "status": "available"}


def main(home: Path) -> int:
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    IngestWorker(home, WorkerIO("ingest")).serve()
    return 0
