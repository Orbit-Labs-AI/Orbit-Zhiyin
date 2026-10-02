"""Resumable page staging, atomic publication and app-owned refresh scheduling.

Sources fetch concurrently (network-bound); store writes stay short and serialized in-process
while this process holds `store.writer()`. Benchmark sources run after model sources so that
leaderboard names can resolve against the model ids imported in the same run.
"""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .contracts import SourceSpec
from .models import canonical_model_id
from .sources import connector

MODEL_KINDS = {"models_dev", "litellm"}
# Long paginated scans publish every N pages so a late failure keeps what was already fetched.
PARTIAL_DEFAULTS = {"mcp": (10, 120)}  # kind -> (publish_every_pages, max_pages per sync call)
LATE_KINDS = {"swe_bench"}


class CatalogSync:
    def __init__(self, store, http, connector_factory=connector):
        self.store, self.http, self.connector_factory = store, http, connector_factory
        self._db = threading.Lock()
        self._models: set[str] = set()

    def sync(self, source_ids: list[str] | None = None, *, force=False, max_pages=10000, cancelled=lambda: False,
             concurrency: int = 3):
        if max_pages < 1:
            raise ValueError("max_pages_must_be_positive")
        sources = self.store.sources()
        requested = set(source_ids or [])
        if requested - {s["source_id"] for s in sources}:
            raise ValueError("unknown_source")
        selected = [s for s in sources if (not requested or s["source_id"] in requested) and s["enabled"]
                    and s["spec"].get("kind") != "local"]
        results: list[dict | None] = [None] * len(selected)
        now = int(time.time() * 1000)
        due = []
        for index, state in enumerate(selected):
            if not force and state["next_due_at"] > now:
                results[index] = {"source_id": state["source_id"], "status": "not_due"}
            else:
                due.append(index)
        late = [i for i in due if selected[i]["spec"].get("kind") in LATE_KINDS]
        early = [i for i in due if i not in late]

        def run(index):
            started = time.perf_counter()
            result = self._sync_one(selected[index], max_pages, cancelled)
            results[index] = {**result, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}

        self._models = set()
        with self.store.writer(), ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for phase in (early, late):
                if phase is late and late:
                    self._models |= self._stored_models()
                list(pool.map(run, phase))
        return [r for r in results if r is not None]

    def _sync_one(self, state: dict, max_pages: int, cancelled) -> dict:
        with self._db:
            run = self.store.begin_run(state["source_id"])
        try:
            if run["status"] == "ready":
                with self._db:
                    return self.store.publish(run["run_id"])
            known_resources = getattr(self.store, "known_resources", None)
            if known_resources:
                with self._db:
                    state = {**state, "known": known_resources(state["source_id"]) or {}}
            spec = SourceSpec.model_validate(state["spec"])
            if spec.kind in LATE_KINDS:
                state = {**state, "known_models": set(self._models)}
            adapter = self.connector_factory(spec, self.http)
            checkpoint = run["checkpoint"]
            every, budget = PARTIAL_DEFAULTS.get(spec.kind, (0, max_pages))
            every = int(spec.config.get("publish_every_pages", every) or 0)
            budget = min(max_pages, int(spec.config.get("max_pages", budget) or max_pages))
            partial = getattr(self.store, "publish_partial", None) if every > 0 else None
            for fetched in range(1, budget + 1):
                if cancelled():
                    break
                page = adapter.fetch_page(checkpoint, state)
                if not page.complete and page.checkpoint == checkpoint:
                    raise ValueError("source_checkpoint_did_not_advance")
                if spec.kind in MODEL_KINDS:
                    self._models |= {r.resource.metadata["canonical_id"] for r in page.records
                                     if r.resource.metadata.get("canonical_id")}
                with self._db:
                    self.store.stage(run["run_id"], page)
                checkpoint = page.checkpoint
                if page.complete:
                    with self._db:
                        return self.store.publish(run["run_id"])
                if partial and fetched % every == 0:
                    with self._db:
                        partial(run["run_id"])
            with self._db:
                return self.store.finish_interrupted(run["run_id"])
        except Exception as exc:
            # Adapter errors carry codes, not response bodies or request headers.
            code = str(exc)[:200] if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
            with self._db:
                return self.store.finish_interrupted(run["run_id"], code, getattr(exc, "retry_after", 0))

    def _stored_models(self) -> set[str]:
        """Model ids already published (works for catalog schema v2 and v3); empty when unavailable."""
        connect = getattr(self.store, "connect", None)
        if connect is None:
            return set()
        try:
            with self._db, connect(True) as conn:
                rows = conn.execute("SELECT provider, model_id FROM model_info").fetchall()
        except sqlite3.Error:
            return set()
        ids = {canonical_model_id(model_id, provider) for provider, model_id in rows if model_id}
        return {cid for cid in ids if not cid.startswith("unknown/")}
