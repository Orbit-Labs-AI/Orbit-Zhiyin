"""Gateway side of ``uiview_facts``: snapshot lookup, else enqueue on the analysis worker.

Same contract as ``recommend.inputs.fetch``: exact snapshot → fresh; otherwise submit an
interactive job, optionally wait ``wait_ms``, then fall back to the newest older snapshot
(stale) or report ``computing``. Never runs the analysis in the gateway process.
"""

from __future__ import annotations

SECTION = "uiview_facts"


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
        return _attach(snapshot, h), "fresh", None
    task = gw.supervisor.analysis.submit(SECTION, scope_dict, {}, h, "interactive",
                                         (rev["data_rev"], rev["inventory_rev"]), rules)
    if task is not None and wait_ms:
        task.done.wait(wait_ms / 1000)
        if task.status == "completed":
            snapshot = gw.snapshots.get(key)
            if snapshot is not None:
                return _attach(snapshot, h), "fresh", None
    job_id = task.id if task is not None else None
    old = gw.snapshots.latest(SECTION, h, rules)
    if old is not None:
        return _attach(old, h), "stale", job_id
    return None, "computing", job_id


def _attach(snapshot, h: str) -> dict:
    meta = {**(snapshot.body.get("meta") or {}), "scope_hash": h,
            "data_rev": snapshot.key.data_rev, "inventory_rev": snapshot.key.inventory_rev}
    return {**snapshot.body, "meta": meta}
