"""Small application boundary: public catalog operations and cancellable background jobs."""

import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from orbit_data.paths import default_home as orbit_default_home

from . import embedding_model
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
from .snapshot import OFFLINE_KINDS, bundled_seed, import_snapshot, retire_seeds
from .sources import default_sources
from .store import CatalogBusy, CatalogStore
from .sync import CatalogSync
from .vectors import LocalE5Encoder, embedding_coverage, index_embeddings, normalize_vectors

# Chunks per background embedding job. One slice of the int8 E5 on an M-series CPU takes about
# 10-20 s (validation.md), short enough that a due source sync waits at most one slice.
EMBED_SLICE = 512
DOWNLOAD_RETRY_S = 1800  # a failed opt-in download is retried by the background tick after 30 min


def default_home() -> Path:
    return orbit_default_home()


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
        self.model_roots = embedding_model.default_roots(self.store.path.parent)
        self._encoder = encoder
        self._model_lock = threading.Lock()
        self._model_error = None  # (directory, code): a broken model is not reloaded on every search
        self._download = {"state": "idle", "done_bytes": 0, "total_bytes": embedding_model.DOWNLOAD_BYTES,
                          "error": None, "finished_at": None}
        self._vector_idle_generation = None
        self._jobs_lock = threading.Lock()
        self._jobs = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="orbit-catalog")
        self.on_job_done = None  # Optional callback(job) for telemetry (set by the gateway).
        self._first_sync = {"state": "pending", "job_id": None, "due_at": None}

    def model_directory(self) -> Path | None:
        """The explicit ``model_dir`` or the first complete E5 directory under ``model_roots``."""
        if self.model_dir:
            return Path(self.model_dir)
        return embedding_model.discover(self.model_roots)

    def encoder(self):
        """The loaded encoder, None without a model; raises (once per directory) when it cannot load."""
        with self._model_lock:
            if self._encoder is not None:
                return self._encoder
            directory = self.model_directory()
            if directory is None:
                return None
            if self._model_error and self._model_error[0] == str(directory):
                raise RuntimeError(self._model_error[1])
            try:
                self._encoder = LocalE5Encoder(directory)
            except ImportError:
                self._model_error = (str(directory), "embedding_runtime_missing")
                raise RuntimeError("embedding_runtime_missing") from None
            except Exception as exc:  # noqa: BLE001 - corrupt/foreign files: report, keep lexical search.
                self._model_error = (str(directory), "embedding_model_unloadable")
                raise RuntimeError("embedding_model_unloadable") from exc
            return self._encoder

    def match(self, request: MatchRequest) -> dict:
        try:
            encoder = self.encoder()
        except Exception as exc:
            result = search(self.store, request)
            result["vector"] = {"status": "unavailable",
                                "reason": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}
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
        with ThreadPoolExecutor(max_workers=min(4, len(requests)), thread_name_prefix="orbit-match") as pool:
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

    def library(self, *, profile: dict | None = None, tab: str = "for", kinds=(), agents=(), q: str = "",
                sort: str = "fit", exclude=(), limit: int = 20, cursor: str | None = None) -> dict:
        """A8 library view: hybrid retrieval seeds lexical candidates, query.library scores parts."""
        from . import query
        lexical = {}
        features = [Feature(feature=f["feature"], value=f["value"], weight=max(0.01, min(10, f["weight"])),
                            origin="declared", evidence="profile")
                    for f in sorted((profile or {}).get("features") or [], key=lambda f: -f["weight"])[:40]] \
            if (profile or {}).get("ok") else []
        if tab == "for" and (q.strip() or features):
            kinds_ = [k for k in kinds if k] or list(query.LIBRARY_KINDS)
            ranked = sorted(profile.get("features") or [], key=lambda f: -f["weight"]) if features else []
            labels = " ".join(dict.fromkeys(str(f.get("label") or f["value"]) for f in ranked[:12]))
            result = self.match(MatchRequest(text=(q.strip() or labels)[:8000], features=[] if q.strip() else features,
                                             types=kinds_, agents=list(agents), excluded_ids=list(exclude)[:1000],
                                             purpose="library", limit=100, per_route=200, prefix=bool(q.strip())))
            lexical = {item["item_id"]: float(item["score"]) for item in result["items"]}
        return query.library(self.store, profile=profile, lexical=lexical, tab=tab, kinds=kinds, agents=agents, q=q,
                             sort=sort, exclude=exclude, limit=limit, cursor=cursor)

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
        http = self.http
        if (request.offline or request.ttl is not None) and isinstance(http, HttpClient):
            # Same cache file, per-run policy; the shared client keeps its defaults.
            http = HttpClient(http.cache_dir, github_token=http.github_token, offline=request.offline,
                              ttl=request.ttl, opener=http.opener)

        def run(cancel):
            try:
                results = CatalogSync(self.store, http).sync(request.source_ids, force=request.force,
                                                             max_pages=request.max_pages, cancelled=cancel,
                                                             concurrency=request.concurrency)
                self.retire_seeds(results)
                return results
            finally:
                if http is not self.http:
                    http.close()
        return self._submit("sync", run)

    def retire_seeds(self, results: list[dict]) -> int:
        """Seed rows of sources that just published from the network are no longer needed."""
        done = [r["source_id"] for r in results if r.get("status") == "completed"]
        return retire_seeds(self.store, done) if done else 0

    def bootstrap(self, seed: bytes | None = None, *, import_seed: bool = True,
                  offline_ids=("orbit-seeds", "orbit-kb")) -> dict:
        """First start: publish the offline sources (package data, KB) and the bundled snapshot.

        Never touches the network. Safe to call on every start: offline sources are published
        on every start (no-op when unchanged), the snapshot only while the library has no
        network data and no seed yet (``needs_seed``).
        """
        sources = {s["source_id"]: s for s in self.store.sources()}
        # Re-published every start (an unchanged revision is a cheap no-op), so an app update
        # that ships a new KB or seed list is visible immediately.
        due = [sid for sid in offline_ids if sid in sources and sources[sid]["enabled"]]
        result = {"offline": [], "seed": None}
        if due:
            # Offline kinds read package files only; a failing source is reported, not raised.
            result["offline"] = CatalogSync(self.store, self.http).sync(due, force=True, concurrency=1)
        if import_seed and self.needs_seed():
            seed = bundled_seed() if seed is None else seed
            if seed:
                result["seed"] = import_snapshot(self.store, seed)
        return result

    def needs_seed(self) -> bool:
        """No snapshot imported yet and no network source has ever completed."""
        return not any(s["spec"].get("kind") == "snapshot" or
                       (s["completed_at"] and s["spec"].get("kind") not in OFFLINE_KINDS)
                       for s in self.store.sources())

    def needs_network_sync(self) -> bool:
        """No network source has ever completed: the library holds only offline/seed rows."""
        return not any(s["completed_at"] and s["spec"].get("kind") not in OFFLINE_KINDS for s in self.store.sources())

    def track_first_sync(self, state: str, *, job_id: str | None = None, due_at: int | None = None) -> None:
        """Gateway scheduler hook: pending / scheduled / deferred / disabled / not_needed / job."""
        with self._jobs_lock:
            self._first_sync = {"state": state, "job_id": job_id, "due_at": due_at}

    def first_sync_state(self) -> dict:
        """First-run library sync for the UI: ``state`` is the scheduler state or, once started, the job's."""
        with self._jobs_lock:
            info = dict(self._first_sync)
            job = self._jobs.get(info["job_id"]) if info["job_id"] else None
            if job is not None:
                info["state"] = job["status"]
                info["error"] = job["error"]
                results = job["result"] or []
                info["sources"] = {"completed": sum(r.get("status") == "completed" for r in results),
                                   "failed": sorted(r["source_id"] for r in results if r.get("status") == "failed")}
        return info

    def coverage(self) -> dict:
        """Library coverage for the settings page and the first-start progress bar."""
        stats = self.store.stats()
        with self.store.connect(True) as conn:
            per_source = {r[0]: r[1] for r in conn.execute(
                "SELECT source_id,count(*) FROM item_source WHERE status='active' GROUP BY source_id")}
            open_runs = {r[0] for r in conn.execute(
                "SELECT DISTINCT source_id FROM sync_run WHERE status IN ('running','paused','failed','ready')")}
        by_source, seeded, last_sync, partial = {}, False, None, []
        for source in self.store.sources():
            sid, kind = source["source_id"], source["spec"].get("kind")
            by_source[sid] = {"kind": kind, "items": per_source.get(sid, 0), "last_ok_at": source["completed_at"],
                              "error": source["error"], "enabled": bool(source["enabled"])}
            if kind in ("snapshot", "kb") and source["completed_at"]:
                seeded = True
            if kind in OFFLINE_KINDS:
                continue
            if source["completed_at"]:
                last_sync = max(last_sync or 0, source["completed_at"])
            if source["enabled"] and (sid in open_runs or not source["completed_at"]):
                partial.append(sid)
        return {"by_kind": stats["by_type"], "by_source": by_source, "seeded": seeded,
                "last_sync_at": last_sync, "partial_sources": partial}

    def start_embeddings(self, max_chunks: int | None = None) -> dict:
        if self._encoder is None and self.model_directory() is None:
            raise ValueError("local_embedding_model_not_configured")
        return self._submit("embed", lambda cancel: index_embeddings(self.store, self.encoder(),
                            max_chunks=max_chunks, cancelled=cancel))

    # Semantic model lifecycle: consent -> download -> load -> background slices -> coverage.

    def set_model_download(self, allowed: bool) -> dict:
        """Record the user's choice; allowing it also starts the download right away."""
        embedding_model.set_download_allowed(self.model_roots[0], allowed)
        if allowed and self.model_directory() is None:
            try:
                self.start_model_download()
            except ValueError as exc:  # another catalog job: the background tick starts it later
                if str(exc) != "catalog_job_already_active":
                    raise
        return self.vector_status()

    def start_model_download(self) -> dict:
        if not embedding_model.download_allowed(self.model_roots[0]):
            raise ValueError("model_download_not_allowed")

        def run(cancel):
            def progress(done, total):
                self._download.update(done_bytes=done, total_bytes=total)
            self._download.update(state="downloading", error=None)
            try:
                directory = embedding_model.download(self.model_roots[0], cancelled=cancel, progress=progress)
            except embedding_model.ModelDownloadError as exc:
                state = "cancelled" if str(exc) == "model_download_cancelled" else "failed"
                self._download.update(state=state, error=str(exc), finished_at=time.time())
                raise RuntimeError(str(exc)) from None
            with self._model_lock:
                self._model_error = None
            self._download.update(state="completed", finished_at=time.time())
            return {"model_dir": str(directory), "bytes": embedding_model.DOWNLOAD_BYTES}
        return self._submit("model", run)

    def _active_job(self) -> dict | None:
        with self._jobs_lock:
            return next(({k: v for k, v in j.items() if k != "cancel"} for j in self._jobs.values()
                         if j["status"] in ("queued", "running")), None)

    def vector_tick(self, slice_chunks: int = EMBED_SLICE) -> dict | None:
        """Background step (gateway refresher): download if allowed, else embed one slice.

        Returns the started job or None (busy, nothing to do, or no model). Slices are
        resumable by construction: vectors are committed per batch and keyed by text hash.
        """
        if self._active_job() is not None:
            return None
        if self._encoder is None and self.model_directory() is None:
            retry = (self._download["state"] != "failed" or
                     time.time() - (self._download["finished_at"] or 0) > DOWNLOAD_RETRY_S)
            if retry and self._download["state"] != "cancelled" and embedding_model.download_allowed(self.model_roots[0]):
                return self.start_model_download()
            return None
        with self.store.reader() as conn:
            generation = self.store.generation(conn)
        if generation == self._vector_idle_generation:
            return None  # nothing was published since the last complete pass
        try:
            encoder = self.encoder()
        except Exception:  # noqa: BLE001 - reported by vector_status()
            return None
        if encoder is None:
            return None
        coverage = embedding_coverage(self.store, encoder.model_id)
        if coverage["pending_chunks"] == 0:
            self._vector_idle_generation = generation
            return None
        try:
            return self.start_embeddings(slice_chunks)
        except ValueError:
            return None

    def vector_status(self) -> dict:
        """``vector`` block of /v1/catalog/status: model, download and chunk coverage.

        status: not_configured (no model, no consent) / downloading / download_failed /
        unavailable (model present but cannot load) / not_loaded / indexing / not_indexed /
        partial / ready. Coverage counts embed chunks of active items (overview + first
        chunks, see features.EMBED_CHUNKS) that have a vector for the loaded model.
        """
        root = self.model_roots[0]
        directory = self.model_directory()
        active = self._active_job()
        result = {"status": "not_configured", "model": None, "coverage": None,
                  "download": {**self._download, "allowed": embedding_model.download_allowed(root),
                               "repo": embedding_model.REPO, "revision": embedding_model.REVISION,
                               "precision": embedding_model.PRECISION, "target": str(root / embedding_model.MODEL_NAME)}}
        if directory is None and self._encoder is None:
            if active and active["kind"] == "model":
                result["status"] = "downloading"
            elif self._download["state"] == "failed":
                result["status"] = "download_failed"
            return result
        result["model"] = {"dir": str(directory) if directory else None}
        if self._encoder is None and self._model_error and self._model_error[0] == str(directory):
            result.update(status="unavailable", reason=self._model_error[1])
            return result
        encoder = self._encoder
        if encoder is None:
            result["status"] = "not_loaded"
            return result
        manifest = getattr(encoder, "manifest", {}) or {}
        result["model"].update(model_id=encoder.model_id, precision=encoder.descriptor.get("precision"),
                               revision=manifest.get("revision"), name=manifest.get("name", embedding_model.MODEL_NAME))
        coverage = embedding_coverage(self.store, encoder.model_id)
        result["coverage"] = coverage
        if active and active["kind"] == "embed":
            result["status"] = "indexing"
        elif coverage["embedded_chunks"] == 0:
            result["status"] = "not_indexed"
        else:
            result["status"] = "ready" if coverage["pending_chunks"] == 0 else "partial"
        return result

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
            started = time.perf_counter()
            try:
                result = operation(job["cancel"].is_set)
                failed = kind == "sync" and any(r["status"] == "failed" for r in result)
                with self._jobs_lock:
                    job.update(result=result, status="cancelled" if job["cancel"].is_set() else "failed" if failed else "completed")
            except Exception as exc:
                with self._jobs_lock:
                    job.update(status="failed", error=str(exc)[:200] if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
            with self._jobs_lock:
                job["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            if self.on_job_done is not None:
                try:
                    self.on_job_done(self.job(job["job_id"]))
                except Exception:  # noqa: BLE001 - telemetry never fails a job.
                    pass
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
