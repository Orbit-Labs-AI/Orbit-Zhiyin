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
    from ..services.routes_analytics import CLIENT_ERRORS, failure_error

    analysis = gw.supervisor.analysis
    revision = (rev["data_rev"], rev["inventory_rev"])
    old = gw.snapshots.latest(SECTION, h, rules)
    lookup = getattr(analysis, "failure", None)  # minimal test doubles lack it
    failure = lookup(SECTION, h, revision) if lookup is not None else None
    if old is None and failure and (failure["error"].get("code") in CLIENT_ERRORS
                                    or analysis.circuit_open(SECTION, h, revision)):
        raise failure_error(failure["error"])  # A stable error, never an endless 202.
    remember = getattr(getattr(gw, "state", None), "remember_scope", None)
    if remember is not None:
        # The prewarm reuses the client's timezone and filters. The window itself is left
        # out: a dated 7-day scope in the MRU would be prewarmed again tomorrow for nobody.
        remember({**scope_dict, "from_ts": None, "until_ts": None})
    task = analysis.submit(SECTION, scope_dict, {}, h, "interactive", revision, rules)
    if task is not None and wait_ms:
        task.done.wait(wait_ms / 1000)
        if task.status == "completed":
            snapshot = gw.snapshots.get(key)
            if snapshot is not None:
                return _attach(snapshot, h), "fresh", None
    job_id = task.id if task is not None else None
    if old is not None:
        return _attach(old, h), "stale", job_id
    if task is None:  # Circuit open: nothing computes until a manual recompute.
        raise failure_error(((lookup(SECTION, h, revision) if lookup else None) or {})
                            .get("error"))
    if task.status == "failed":
        raise failure_error(task.error)
    return None, "computing", job_id


def _attach(snapshot, h: str) -> dict:
    meta = {**(snapshot.body.get("meta") or {}), "scope_hash": h,
            "data_rev": snapshot.key.data_rev, "inventory_rev": snapshot.key.inventory_rev}
    return {**snapshot.body, "meta": meta}


def default_scope(tz: str | None = None) -> dict:
    """The scope ``/v1/uiview/facts`` uses when only a display timezone is given."""
    from dataclasses import asdict

    from ..services.routes_uiview import facts_scope

    return asdict(facts_scope(display_timezone=tz or "UTC"))


def latest_rows(gw, tz: str | None = None) -> dict[str, dict] | None:
    """Newest cached fact rows by session id (never enqueues a computation)."""
    body = latest_body(gw, tz)
    if body is None:
        return None
    return {r["id"]: r for r in body.get("rows") or [] if not r.get("excluded")}


def mru_timezone(gw) -> str | None:
    """The client timezone the prewarm keys facts by (newest MRU scope that names one)."""
    state = getattr(gw, "state", None)
    try:
        mru = state.snapshot().get("mru_scopes") or [] if state is not None else []
    except Exception:  # noqa: BLE001 - minimal test doubles / unreadable state
        return None
    return next((s.get("display_timezone") for s in mru if s.get("display_timezone")), None)


def latest_snapshot(gw, tz: str | None = None) -> tuple[dict | None, int | None]:
    """(newest cached ``uiview_facts`` body, its window in days; 0 = all time), widest first.

    Looks under the requested timezone, then the MRU timezone the prewarm uses, then UTC, so
    a non-UTC client still finds the snapshot its own overview requests (or the prewarm)
    produced. Never enqueues.
    """
    from ..services.fastpath import windowed
    from ..services.sections import rules_digest
    from ..services.snapshots import scope_hash

    rules = rules_digest()
    zones: list[str] = []
    for zone in (tz, mru_timezone(gw), "UTC"):
        if zone and zone not in zones:
            zones.append(zone)
    for zone in zones:
        try:
            base = default_scope(zone)
        except Exception:  # noqa: BLE001 - an invalid timezone is skipped, like the prewarm
            continue
        for days in (0, 30, 7):  # The widest window computed so far (first-open fast path).
            snapshot = gw.snapshots.latest(SECTION, scope_hash(windowed(base, days), {}), rules)
            if snapshot is not None:
                return snapshot.body, days
    return None, None


def latest_body(gw, tz: str | None = None) -> dict | None:
    """Newest cached ``uiview_facts`` body (rows + aux), widest window first; never enqueues."""
    return latest_snapshot(gw, tz)[0]


def persona_page(gw, scope_dict: dict, params: dict, today, *, wait_ms: int = 0):
    """(A2 persona payload | None, freshness, job_id) — what ``/v1/uiview/persona`` returns."""
    from . import facts, persona

    body, freshness, job_id = fetch(gw, scope_dict, wait_ms=wait_ms)
    if body is None:
        return None, freshness, job_id
    realtime = getattr(gw, "realtime", None)
    body = facts.overlay_live(body, realtime.latest() if realtime is not None else None)
    page = persona.page(body, params, today)
    page["meta"].update({k: body["meta"].get(k) for k in ("data_rev", "scope_hash")})
    return page, freshness, job_id
