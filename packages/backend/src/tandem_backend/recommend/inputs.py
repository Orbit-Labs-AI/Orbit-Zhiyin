"""Gateway side of ``recommend_inputs``: snapshot lookup, else enqueue on the analysis worker.

Mirrors ``routes_analytics.serve``: exact snapshot → fresh; otherwise submit an interactive
job, optionally wait ``wait_ms``, then fall back to the newest older snapshot (stale) or
report ``computing``. With no older snapshot, an open circuit or a failed wait raises the
same retryable 503 as ``routes_analytics.serve`` instead of ``computing`` forever. Never runs
the analysis in the gateway process.
"""

from __future__ import annotations

SECTION = "recommend_inputs"


def fetch(gw, scope_dict: dict, *, wait_ms: int = 0) -> tuple[dict | None, str, str | None]:
    from ..services.sections import rules_digest
    from ..services.snapshots import SnapshotKey, scope_hash

    rev = gw.revisions.snapshot()
    if rev["data_rev"] is None:
        return None, "none", None
    rules = rules_digest()
    h = scope_hash(scope_dict, {})
    key = SnapshotKey(SECTION, h, rev["data_rev"], rev["inventory_rev"], rules)
    snapshot = gw.snapshots.get(key)
    if snapshot is not None:
        return _attach(snapshot, scope_dict, h), "fresh", None
    from ..services.routes_analytics import failure_error

    analysis = gw.supervisor.analysis
    revision = (rev["data_rev"], rev["inventory_rev"])
    task = analysis.submit(SECTION, scope_dict, {}, h, "interactive", revision, rules)
    if task is not None and wait_ms:
        task.done.wait(wait_ms / 1000)
        if task.status == "completed":
            snapshot = gw.snapshots.get(key)
            if snapshot is not None:
                return _attach(snapshot, scope_dict, h), "fresh", None
    job_id = task.id if task is not None else None
    old = gw.snapshots.latest(SECTION, h, rules)
    if old is not None:
        return _attach(old, scope_dict, h), "stale", job_id
    if task is None:  # Circuit open: nothing will ever compute until a manual recompute.
        raise failure_error((analysis.failure(SECTION, h, revision) or {}).get("error"))
    if task.status == "failed":
        raise failure_error(task.error)
    return None, "computing", job_id


def _attach(snapshot, scope_dict: dict, h: str) -> dict:
    return {**snapshot.body, "scope": scope_dict, "scope_hash": h,
            "data_rev": snapshot.key.data_rev, "inventory_rev": snapshot.key.inventory_rev}
