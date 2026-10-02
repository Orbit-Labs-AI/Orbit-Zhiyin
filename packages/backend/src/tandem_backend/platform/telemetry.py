"""Local, opt-in telemetry: per-minute aggregates in memory, batched into ``app.db``.

Nothing leaves the machine. Tags must be low-cardinality (route template, status class,
job kind) — never paths, content or prompts. Minute rows are kept for 6 hours, then
rolled up into hour rows kept ``retention_days`` (14 by default, 30 at most); both tables
also have a hard row cap so the footprint stays bounded (~10-15 MB worst case).
"""

from __future__ import annotations

import bisect
import json
import threading
import time
from contextlib import ContextDecorator

BOUNDS_MS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000)
NBUCKETS = len(BOUNDS_MS) + 1  # Last bucket is +inf.
METRICS = {
    "http.request": "ms", "http.slow": "count", "etag.hit": "count", "job.duration": "ms",
    "analysis.duration": "ms", "cache.snapshot": "count", "ai.cost_usd": "usd",
    "ai.tokens": "tokens", "ai.job": "ms", "install.apply": "ms", "recommend.run": "ms",
    "error": "count", "maintenance": "ms", "sse.clients": "gauge",
}
MAX_TAGSETS = 200
OTHER = '{"_":"other"}'
MINUTE_MS = 60_000
HOUR_MS = 3_600_000
MINUTE_KEEP_MS = 6 * HOUR_MS
ROW_CAP = 60_000
BYTES_PER_ROW = 160


def now_ms() -> int:
    return int(time.time() * 1000)


def tag_string(tags: dict) -> str:
    return json.dumps(dict(sorted(tags.items())), separators=(",", ":"), ensure_ascii=False)


def _merge(into: list, other: list) -> list:
    """Merge aggregate ``[n, sum, min, max, buckets|None]`` rows."""
    into[0] += other[0]
    into[1] += other[1]
    into[2] = min(into[2], other[2])
    into[3] = max(into[3], other[3])
    if other[4] is not None:
        into[4] = [a + b for a, b in zip(into[4], other[4], strict=True)] if into[4] else list(
            other[4])
    return into


def quantile(agg: list, q: float) -> float | None:
    """Approximate quantile from log buckets, interpolated and clamped to [min, max]."""
    n, _, lo, hi, buckets = agg
    if not buckets or n <= 0:
        return None
    target = q * n
    seen = 0
    for i, count in enumerate(buckets):
        if count and seen + count >= target:
            lower = BOUNDS_MS[i - 1] if i > 0 else 0.0
            upper = BOUNDS_MS[i] if i < len(BOUNDS_MS) else hi
            value = lower + (upper - lower) * (target - seen) / count
            return round(min(max(value, lo), hi), 3)
        seen += count
    return round(hi, 3)


class Telemetry:
    def __init__(self, appdb, settings=None):
        self.appdb = appdb
        self.lock = threading.Lock()
        self.current: dict[int, dict[tuple[str, str], list]] = {}
        self.tag_cache: dict[tuple, str] = {}
        self.tagsets: dict[str, set[str]] = {}
        self.enabled = False
        self.retention_days = 14
        self.row_cap = ROW_CAP
        if settings is not None:
            self.configure(settings.get("telemetry"))

    def configure(self, cfg: dict | None) -> None:
        cfg = cfg or {}
        self.retention_days = int(cfg.get("retention_days") or 14)
        enabled = bool(cfg.get("enabled"))
        if not enabled:
            with self.lock:
                self.current.clear()  # Switching off drops what was not yet written.
        self.enabled = enabled

    # -- hot path ----------------------------------------------------------------------
    def _tags(self, name: str, tags: dict) -> str:
        key = (name, *sorted(tags.items()))
        text = self.tag_cache.get(key)
        if text is None:
            text = tag_string(tags)
            seen = self.tagsets.setdefault(name, set())
            if text not in seen:
                if len(seen) >= MAX_TAGSETS:
                    text = OTHER
                else:
                    seen.add(text)
            if len(self.tag_cache) > 20_000:
                self.tag_cache.clear()
            self.tag_cache[key] = text
        return text

    def record(self, name: str, value: float = 1.0, **tags) -> None:
        if not self.enabled:
            return
        value = float(value)
        minute = int(time.time() * 1000) // MINUTE_MS * MINUTE_MS
        with self.lock:
            key = (name, self._tags(name, tags) if tags else "{}")
            bucket = self.current.get(minute)
            if bucket is None:
                bucket = self.current[minute] = {}
            agg = bucket.get(key)
            if agg is None:
                agg = bucket[key] = [0, 0.0, value, value,
                                     [0] * NBUCKETS if METRICS.get(name) == "ms" else None]
            agg[0] += 1
            agg[1] += value
            if value < agg[2]:
                agg[2] = value
            if value > agg[3]:
                agg[3] = value
            if agg[4] is not None:
                agg[4][bisect.bisect_left(BOUNDS_MS, value)] += 1

    def gauge(self, name: str, value: float, **tags) -> None:
        self.record(name, value, **tags)

    # -- persistence -------------------------------------------------------------------
    def _upsert(self, db, table: str, rows: dict[tuple[str, str, int], list]) -> None:
        for (name, tags, ts), agg in rows.items():
            old = db.execute(f"SELECT n,sum,min,max,buckets FROM {table} WHERE name=? AND tags=?"
                             " AND ts=?", (name, tags, ts)).fetchone()
            if old is not None:
                agg = _merge([old[0], old[1], old[2], old[3],
                              json.loads(old[4]) if old[4] else None], agg)
            db.execute(f"INSERT OR REPLACE INTO {table} (ts,name,tags,n,sum,min,max,buckets)"
                       " VALUES (?,?,?,?,?,?,?,?)",
                       (ts, name, tags, agg[0], agg[1], agg[2], agg[3],
                        json.dumps(agg[4], separators=(",", ":")) if agg[4] else None))

    def flush(self, now: int | None = None, force: bool = False) -> int:
        """Write finished minutes (``force``: also the current one); returns rows written."""
        now = now or now_ms()
        current = now // MINUTE_MS * MINUTE_MS
        with self.lock:
            done = [m for m in self.current if force or m < current]
            taken = {m: self.current.pop(m) for m in done}
        rows = {(name, tags, minute): agg for minute, bucket in taken.items()
                for (name, tags), agg in bucket.items()}
        if rows:
            with self.appdb.write() as db:
                self._upsert(db, "metric_minute", rows)
        return len(rows)

    def rollup(self, now: int | None = None) -> int:
        """Fold minute rows older than 6 h (whole hours only) into ``metric_hour``."""
        now = now or now_ms()
        cutoff = (now - MINUTE_KEEP_MS) // HOUR_MS * HOUR_MS
        with self.appdb.write() as db:
            hours: dict[tuple[str, str, int], list] = {}
            for row in db.execute("SELECT ts,name,tags,n,sum,min,max,buckets FROM metric_minute"
                                  " WHERE ts < ?", (cutoff,)):
                key = (row[1], row[2], row[0] // HOUR_MS * HOUR_MS)
                agg = [row[3], row[4], row[5], row[6], json.loads(row[7]) if row[7] else None]
                hours[key] = _merge(hours[key], agg) if key in hours else agg
            if hours:
                self._upsert(db, "metric_hour", hours)
                db.execute("DELETE FROM metric_minute WHERE ts < ?", (cutoff,))
        return len(hours)

    def prune(self, now: int | None = None) -> int:
        now = now or now_ms()
        days = min(max(self.retention_days, 1), 30)
        deleted = 0
        with self.appdb.write() as db:
            deleted += db.execute("DELETE FROM metric_hour WHERE ts < ?",
                                  (now - days * 86_400_000,)).rowcount
            for table in ("metric_minute", "metric_hour"):
                excess = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] - self.row_cap
                if excess > 0:
                    deleted += db.execute(
                        f"DELETE FROM {table} WHERE (name,tags,ts) IN (SELECT name,tags,ts FROM"
                        f" {table} ORDER BY ts LIMIT ?)", (excess,)).rowcount
        return deleted

    def clear(self) -> int:
        with self.lock:
            self.current.clear()
        with self.appdb.write() as db:
            return (db.execute("DELETE FROM metric_minute").rowcount
                    + db.execute("DELETE FROM metric_hour").rowcount)

    # -- queries -----------------------------------------------------------------------
    def query(self, name: str | None = None, window_s: int = 3600, step: str = "minute",
              tags: dict | None = None, now: int | None = None) -> dict:
        now = now or now_ms()
        since = now - int(window_s) * 1000
        where, params = "ts >= ?", [since]
        if name:
            where += " AND name = ?"
            params.append(name)
        rows: list[tuple] = []
        with self.appdb.read() as db:
            for table in ("metric_hour", "metric_minute"):
                rows += db.execute(f"SELECT ts,name,tags,n,sum,min,max,buckets FROM {table}"
                                   f" WHERE {where}", params).fetchall()
        with self.lock:
            pending = [(m, n, t, *agg[:4], agg[4] and list(agg[4]))
                       for m, bucket in self.current.items() if m >= since
                       for (n, t), agg in bucket.items() if not name or n == name]
        series: dict[tuple[str, str], dict[int, list]] = {}
        for ts, n, t, count, total, lo, hi, buckets in [*rows, *pending]:
            if tags:
                parsed = json.loads(t)
                if any(str(parsed.get(k)) != str(v) for k, v in tags.items()):
                    continue
            if isinstance(buckets, str):
                buckets = json.loads(buckets)
            point = ts if step == "minute" else ts // HOUR_MS * HOUR_MS if step == "hour" else 0
            points = series.setdefault((n, t), {})
            agg = [count, total, lo, hi, buckets]
            points[point] = _merge(points[point], agg) if point in points else agg
        out = []
        for (n, t), points in sorted(series.items()):
            total: list | None = None
            for agg in points.values():
                total = _merge(list(total), agg) if total else list(agg)
            assert total is not None
            out.append({
                "name": n, "tags": json.loads(t), "unit": METRICS.get(n, "count"),
                "count": total[0], "sum": round(total[1], 6),
                "avg": round(total[1] / total[0], 3) if total[0] else None,
                "min": total[2], "max": total[3], "p50": quantile(total, 0.5),
                "p95": quantile(total, 0.95), "p99": quantile(total, 0.99),
                "points": [[ts, a[0], round(a[1], 6), quantile(a, 0.95)]
                           for ts, a in sorted(points.items())] if step != "total" else [],
            })
        return {"series": out}

    def stats(self) -> dict:
        with self.appdb.read() as db:
            result = db.execute(
                "SELECT count(*), count(DISTINCT name || char(0) || tags), min(ts) FROM ("
                "SELECT name,tags,ts FROM metric_minute UNION ALL "
                "SELECT name,tags,ts FROM metric_hour)").fetchone()
        rows, series, since = result
        return {"series": series, "rows": rows, "bytes_est": rows * BYTES_PER_ROW,
                "since": since}


# -- module-level API (no gateway dependency; no-op until a Telemetry is installed) ------
_active: Telemetry | None = None


def install(telemetry: Telemetry | None) -> None:
    global _active
    _active = telemetry


def active() -> Telemetry | None:
    return _active


def record(name: str, value: float = 1.0, **tags) -> None:
    t = _active
    if t is not None and t.enabled:
        try:
            t.record(name, value, **tags)
        except Exception:  # noqa: BLE001 - telemetry never breaks the caller.
            pass


def gauge(name: str, value: float, **tags) -> None:
    record(name, value, **tags)


class timed(ContextDecorator):  # noqa: N801 - reads as a function at call sites.
    """``with timed("x"):`` or ``@timed("x")``: records elapsed milliseconds."""

    def __init__(self, name: str, **tags):
        self.name, self.tags = name, tags
        self.t0 = 0.0

    def _recreate_cm(self):
        return timed(self.name, **self.tags)  # Fresh state per decorated call (thread-safe).

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        record(self.name, (time.perf_counter() - self.t0) * 1000, **self.tags)
        return False
