"""Resumable page staging, atomic publication and app-owned refresh scheduling."""

import time

from .contracts import SourceSpec
from .sources import connector


class CatalogSync:
    def __init__(self, store, http, connector_factory=connector):
        self.store, self.http, self.connector_factory = store, http, connector_factory

    def sync(self, source_ids: list[str] | None = None, *, force=False, max_pages=10000, cancelled=lambda: False):
        if max_pages < 1:
            raise ValueError("max_pages_must_be_positive")
        sources = self.store.sources()
        requested = set(source_ids or [])
        if requested - {s["source_id"] for s in sources}:
            raise ValueError("unknown_source")
        results = []
        with self.store.writer():
            for state in sources:
                if requested and state["source_id"] not in requested:
                    continue
                if not state["enabled"]:
                    continue
                if not force and state["next_due_at"] > int(time.time() * 1000):
                    results.append({"source_id": state["source_id"], "status": "not_due"})
                    continue
                run = self.store.begin_run(state["source_id"])
                try:
                    if run["status"] == "ready":
                        results.append(self.store.publish(run["run_id"]))
                        continue
                    adapter = self.connector_factory(SourceSpec.model_validate(state["spec"]), self.http)
                    checkpoint = run["checkpoint"]
                    published = False
                    for _ in range(max_pages):
                        if cancelled():
                            break
                        page = adapter.fetch_page(checkpoint, state)
                        if not page.complete and page.checkpoint == checkpoint:
                            raise ValueError("source_checkpoint_did_not_advance")
                        self.store.stage(run["run_id"], page)
                        checkpoint = page.checkpoint
                        if page.complete:
                            results.append(self.store.publish(run["run_id"]))
                            published = True
                            break
                    if not published:
                        results.append(self.store.finish_interrupted(run["run_id"]))
                    if cancelled():
                        break
                except Exception as exc:
                    # Adapter errors carry codes, not response bodies or request headers.
                    code = str(exc)[:200] if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                    results.append(self.store.finish_interrupted(run["run_id"], code, getattr(exc, "retry_after", 0)))
        return results
