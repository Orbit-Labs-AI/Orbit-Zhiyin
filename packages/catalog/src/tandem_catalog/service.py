"""Small application boundary: public catalog operations and cancellable background jobs."""

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .contracts import MatchRequest, SourceSpec, SyncRequest
from .network import HttpClient
from .search import search
from .sources import default_sources
from .store import CatalogStore
from .sync import CatalogSync
from .vectors import LocalE5Encoder, index_embeddings


def default_home() -> Path:
    return Path(os.environ.get("TANDEM_HOME", Path.home() / "Library/Application Support/Tandem"))


class CatalogService:
    def __init__(self, path: str | Path, *, model_dir=None, http=None, encoder=None):
        self.store = CatalogStore(path)
        existing = {s["source_id"] for s in self.store.sources()}
        missing = [s for s in default_sources() if s.source_id not in existing]
        if missing:
            self.store.register(missing)
        self.http = http or HttpClient(self.store.path.parent / "catalog-http-cache")
        self.model_dir = model_dir
        self._encoder = encoder
        self._model_lock = threading.Lock()
        self._jobs_lock = threading.Lock()
        self._jobs = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tandem-catalog")

    def encoder(self):
        with self._model_lock:
            if self._encoder is None and self.model_dir:
                self._encoder = LocalE5Encoder(self.model_dir)
            return self._encoder

    def match(self, request: MatchRequest) -> dict:
        try:
            encoder = self.encoder()
        except Exception as exc:
            result = search(self.store, request)
            result["vector"] = {"status": "unavailable", "reason": type(exc).__name__}
            return result
        return search(self.store, request, encoder)

    def set_enabled(self, source_id: str, enabled: bool):
        row = next((s for s in self.store.sources() if s["source_id"] == source_id), None)
        if row is None:
            raise ValueError("unknown_source")
        source = SourceSpec.model_validate(row["spec"]).model_copy(update={"enabled": enabled})
        self.store.register([source])

    def start_sync(self, request: SyncRequest) -> dict:
        known = {s["source_id"] for s in self.store.sources()}
        if set(request.source_ids) - known:
            raise ValueError("unknown_source")
        return self._submit("sync", lambda cancel: CatalogSync(self.store, self.http).sync(
            request.source_ids, force=request.force, max_pages=request.max_pages, cancelled=cancel))

    def start_embeddings(self, max_chunks: int | None = None) -> dict:
        if not self.model_dir and self._encoder is None:
            raise ValueError("local_embedding_model_not_configured")
        return self._submit("embed", lambda cancel: index_embeddings(self.store, self.encoder(),
                            max_chunks=max_chunks, cancelled=cancel))

    def _submit(self, kind, operation):
        with self._jobs_lock:
            active = [j for j in self._jobs.values() if j["status"] in ("queued", "running")]
            if active:
                raise ValueError("catalog_job_already_active")
            # Keep UI job handles bounded; source checkpoints themselves live in SQLite.
            if len(self._jobs) >= 100:
                self._jobs.pop(next(iter(self._jobs)))
            job = {"job_id": uuid.uuid4().hex, "kind": kind, "status": "queued",
                   "created_at": int(time.time() * 1000), "result": None, "error": None, "cancel": threading.Event()}
            self._jobs[job["job_id"]] = job

        def run():
            with self._jobs_lock:
                job["status"] = "running"
            try:
                result = operation(job["cancel"].is_set)
                failed = kind == "sync" and any(r["status"] == "failed" for r in result)
                with self._jobs_lock:
                    job.update(result=result, status="cancelled" if job["cancel"].is_set() else "failed" if failed else "completed")
            except Exception as exc:
                with self._jobs_lock:
                    job.update(status="failed", error=str(exc)[:200] if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
        self._executor.submit(run)
        return self.job(job["job_id"])

    def job(self, job_id):
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            return {k: v for k, v in job.items() if k != "cancel"} if job else None

    def cancel(self, job_id):
        with self._jobs_lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id]["cancel"].set()
            return True

    def close(self):
        with self._jobs_lock:
            for job in self._jobs.values():
                job["cancel"].set()
        self._executor.shutdown(wait=False, cancel_futures=True)
