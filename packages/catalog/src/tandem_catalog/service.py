"""Small application boundary: public catalog operations and cancellable background jobs."""

import hashlib
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .contracts import (
    Feature,
    LocalItem,
    MatchRequest,
    Resource,
    SourceSpec,
    SyncRequest,
    canonical_json,
)
from .network import HttpClient
from .search import query_text, remember_queries, search
from .sources import default_sources
from .store import CatalogBusy, CatalogStore
from .sync import CatalogSync
from .vectors import LocalE5Encoder, index_embeddings, normalize_vectors


def default_home() -> Path:
    return Path(os.environ.get("TANDEM_HOME", Path.home() / "Library/Application Support/Tandem"))


class CatalogService:
    def __init__(self, path: str | Path, *, model_dir=None, http=None, encoder=None):
        self.store = CatalogStore(path)
        existing = {s["source_id"] for s in self.store.sources()}
        missing = [s for s in default_sources() if s.source_id not in existing]
        if missing:
            try:
                self.store.register(missing)
            except CatalogBusy:  # Another process is syncing; defaults are registered next start.
                pass
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

    def match_many(self, requests: list[MatchRequest]) -> list[dict]:
        """Batch-encode all query texts once, then run searches in parallel; order is preserved."""
        if not requests:
            return []
        try:
            encoder = self.encoder()
        except Exception:
            encoder = None
        if encoder is not None:
            texts = list(dict.fromkeys(query_text(r) for r in requests
                                       if query_text(r) and r.model_id in (None, encoder.model_id)))
            if texts:
                vectors = normalize_vectors(encoder.encode(texts, query=True), len(texts), encoder.dimensions)
                remember_queries(encoder, texts, vectors)
        if len(requests) == 1:
            return [self.match(requests[0])]
        with ThreadPoolExecutor(max_workers=min(4, len(requests)), thread_name_prefix="tandem-match") as pool:
            return list(pool.map(self.match, requests))

    def search_cards(self, q: str, kinds=(), agents=(), limit: int = 20, prefix: bool = True) -> dict:
        """Library search box: hybrid retrieval returned as list cards plus snippet and score."""
        from .query import _cards
        limit = max(1, min(100, limit))
        result = self.match(MatchRequest(text=q, types=list(kinds), agents=list(agents), limit=limit,
                                         per_route=max(50, limit * 3), prefix=prefix))
        with self.store.reader() as conn:
            cards = _cards(conn, [item["item_id"] for item in result["items"]])
        items = [{**cards[item["item_id"]], "snippet": (item["passage"] or {}).get("text", "")[:300],
                  "score": item["score"], "score_parts": item["score_parts"]}
                 for item in result["items"] if item["item_id"] in cards]
        return {"items": items, "generation": result.get("generation"), "routes": result["routes"],
                "vector": result["vector"], "ranking_version": result["ranking_version"]}

    def add_local(self, payload: dict | LocalItem) -> dict:
        """Idempotent local item (AI-generated or user-authored); requires a passing self-check."""
        item = payload if isinstance(payload, LocalItem) else LocalItem.model_validate(payload)
        if item.self_check is None:
            raise ValueError("self_check_required")
        if item.self_check.get("passed") is not True:
            raise ValueError("self_check_failed")
        body = item.body.replace("\r\n", "\n").strip()
        if not body:
            raise ValueError("invalid_query")
        item_id = "local:" + hashlib.sha256(canonical_json({"kind": item.kind, "body": body}).encode()).hexdigest()[:32]
        features = [f for f in item.features if f.feature != "generic"]
        features.append(Feature(feature="generic", value="0", origin="declared", evidence="local item"))
        resource = Resource(item_id=item_id, type=item.kind, name=item.name, summary=item.summary, url="",
                            body=body, body_policy="licensed", license="user-generated", agents=item.agents,
                            features=features, manifest=item.manifest, install=item.install,
                            metadata={"origin": "local", "template_id": item.template_id,
                                      "template_version": item.template_version, "job_id": item.job_id,
                                      "self_check": item.self_check})
        return self.store.upsert_local(resource)

    def remove_local(self, item_id: str) -> bool:
        if not item_id.startswith("local:"):
            raise ValueError("not_a_local_item")
        return self.store.remove_local(item_id)

    def set_enabled(self, source_id: str, enabled: bool):
        if source_id == "local":
            raise ValueError("local_source_not_configurable")
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
