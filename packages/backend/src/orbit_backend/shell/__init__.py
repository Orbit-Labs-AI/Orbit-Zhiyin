"""Shell feeds: read-only aggregates for the menu-bar popover, widgets, onboarding and the
persona reveal, plus the notification producers the shell copy promises (P1 shell-feeds).

Everything here reads published data (orbit.db through ``gw.reads``, analysis snapshots,
app.db) and never starts an analysis on a GET, except ``/v1/shell/reveal`` which submits
one recompute when its inputs are missing (same as the analytics routes).

Shared helpers below: local-day arithmetic, the analysed-main-session filter and cached
snapshot lookups.
"""

from __future__ import annotations

import time
from dataclasses import asdict, replace
from functools import partial

DAY_MS = 86_400_000


def now_ms() -> int:
    return int(time.time() * 1000)


def local_offset_min() -> int:
    """This machine's current UTC offset in minutes (east positive)."""
    offset = time.localtime().tm_gmtoff
    return int(offset // 60)


def day_index(ts_ms: int, tz_offset_min: int) -> int:
    """Local calendar day number (days since 1970-01-01 in that offset)."""
    return (ts_ms + tz_offset_min * 60_000) // DAY_MS


def day_start(index: int, tz_offset_min: int) -> int:
    """UTC ms of local midnight of day ``index``."""
    return index * DAY_MS - tz_offset_min * 60_000


def has_db(gw) -> bool:
    return (gw.home / "orbit.db").is_file()


def reader(gw):
    """``reads()`` callable without the projection check (shell feeds tolerate a pending
    projection; they only count rows)."""
    return partial(gw.reads.read, check=False)


def excluded(gw) -> list[str]:
    from ..sessionops import exclusion

    try:
        return exclusion.excluded_uids(gw.appdb)
    except Exception:  # noqa: BLE001 - app.db without the table: nothing excluded.
        return []


def main_where(gw, alias: str = "s") -> tuple[str, list]:
    """Analysed main sessions: kind main, not excluded, not started by Orbit itself."""
    from ..ai.pack import placeholders, session_filter

    sql, args = f"{alias}.kind='main'", []
    skip = excluded(gw)
    if skip:
        sql += f" AND {alias}.session_uid NOT IN ({placeholders(skip)})"
        args += skip
    extra, extra_args = session_filter(gw.home, alias)
    return sql + extra, args + extra_args


def enabled_source_ids(gw) -> list[str] | None:
    """Enabled configured sources when some are disabled; None means "all" (keeps the
    scope hash equal to the pages' default scope)."""
    sources = gw.state.snapshot()["sources"]
    enabled = sorted(k for k, s in sources.items() if s.get("enabled"))
    if not sources or len(enabled) == len(sources):
        return None
    return enabled


def default_scope(gw, days: int = 30, scope=None) -> dict:
    """Analytics scope dict: ``scope`` (an analytics ``Scope``) or the default, with the
    last ``days`` days and the enabled sources filled in when not given."""
    from ..analytics.inputs import Scope
    from ..services.gateway import default_scope as days_scope
    from ..sessionops.exclusion import merged

    if scope is None:
        scope = Scope(excluded_session_uids=merged(None))
    if scope.from_ts is None and scope.until_ts is None:
        scope = replace(scope, from_ts=days_scope(days)["from_ts"])
    if scope.source_ids is None:
        scope = replace(scope, source_ids=enabled_source_ids(gw))
    return asdict(scope)


def cached_section(gw, name: str, scope_dict: dict, params: dict | None = None):
    """``(body, freshness, key)``: the exact snapshot (fresh), an older one (stale) or None
    (missing / none when nothing is published). Never computes."""
    from ..services.sections import rules_digest
    from ..services.snapshots import SnapshotKey, scope_hash

    rev = gw.revisions.snapshot()
    h = scope_hash(scope_dict, params or {})
    if rev["data_rev"] is None:
        return None, "none", None
    rules = rules_digest()
    key = SnapshotKey(name, h, rev["data_rev"], rev["inventory_rev"], rules)
    snapshot = gw.snapshots.get(key)
    if snapshot is not None:
        return snapshot.body, "fresh", key
    old = gw.snapshots.latest(name, h, rules)
    if old is not None:
        return old.body, "stale", key
    return None, "missing", key


def submit_section(gw, name: str, scope_dict: dict, key) -> str | None:
    """Queue one interactive recompute for a missing section; returns the task id."""
    if key is None:
        return None
    try:
        task = gw.supervisor.analysis.submit(
            name, scope_dict, {}, key.scope_hash, "interactive",
            (key.data_rev, key.inventory_rev), key.rules)
    except Exception:  # noqa: BLE001 - a stopped supervisor leaves the reason "computing".
        return None
    return task.id if task is not None else None
