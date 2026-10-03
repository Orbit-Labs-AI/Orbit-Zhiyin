from __future__ import annotations

import time

import pytest

from tandem_backend import platform as pf
from tandem_backend.platform import telemetry as tm
from tandem_backend.platform.telemetry import HOUR_MS, MINUTE_MS, Telemetry


def enabled(platform) -> Telemetry:
    platform.settings.put_telemetry({"enabled": True})
    platform.refresh()
    tm.install(platform.telemetry)
    return platform.telemetry


def rows(platform, table: str) -> list:
    with platform.appdb.read() as db:
        return db.execute(f"SELECT ts,name,tags,n,sum,min,max,buckets FROM {table}").fetchall()


def test_disabled_is_noop(platform_env):
    tm.install(platform_env.telemetry)
    pf.record("http.request", 5, route="/x")
    platform_env.telemetry.record("http.request", 5)
    assert platform_env.telemetry.current == {}
    assert platform_env.telemetry.flush(force=True) == 0


def test_aggregate_and_flush_merges(platform_env):
    t = enabled(platform_env)
    for value in (1, 3, 40, 700):
        t.record("http.request", value, route="/v1/a", status="2xx")
    t.record("etag.hit")
    assert t.flush(force=True) == 2
    t.record("http.request", 0.5, status="2xx", route="/v1/a")  # Same minute, tag order.
    t.flush(force=True)
    (row,) = [r for r in rows(platform_env, "metric_minute") if r[1] == "http.request"]
    assert row[2] == '{"route":"/v1/a","status":"2xx"}'
    assert (row[3], row[4], row[5], row[6]) == (5, 744.5, 0.5, 700)
    buckets = eval(row[7])  # noqa: S307 - JSON int list
    assert sum(buckets) == 5 and buckets[0] == 2 and buckets[1] == 0 and buckets[2] == 1
    count_row = [r for r in rows(platform_env, "metric_minute") if r[1] == "etag.hit"][0]
    assert count_row[7] is None


def test_flush_keeps_current_minute_unless_forced(platform_env):
    t = enabled(platform_env)
    t.record("x")
    assert t.flush() == 0
    assert t.flush(now=int(time.time() * 1000) + 2 * MINUTE_MS) == 1


def test_rollup_and_prune(platform_env):
    t = enabled(platform_env)
    now = int(time.time() * 1000) // HOUR_MS * HOUR_MS
    old = now - 10 * HOUR_MS
    with platform_env.appdb.write() as db:
        for i in range(3):
            db.execute("INSERT INTO metric_minute VALUES (?,?,?,?,?,?,?,?)",
                       (old + i * MINUTE_MS, "job.duration", "{}", 1, 10.0 * (i + 1), 10.0 * (i + 1),
                        10.0 * (i + 1), None))
        db.execute("INSERT INTO metric_minute VALUES (?,?,?,?,?,?,?,?)",
                   (now, "job.duration", "{}", 1, 5.0, 5.0, 5.0, None))
    assert t.rollup(now) == 1
    hours = rows(platform_env, "metric_hour")
    assert [(r[0], r[3], r[4], r[5], r[6]) for r in hours] == [(old, 3, 60.0, 10.0, 30.0)]
    assert len(rows(platform_env, "metric_minute")) == 1
    # Retention drops old hours, row caps trim oldest.
    with platform_env.appdb.write() as db:
        db.execute("INSERT INTO metric_hour VALUES (?,?,?,?,?,?,?,?)",
                   (now - 40 * 86_400_000, "x", "{}", 1, 1, 1, 1, None))
        for i in range(10):
            db.execute("INSERT INTO metric_minute VALUES (?,?,?,?,?,?,?,?)",
                       (now - (i + 1) * MINUTE_MS, "y", "{}", 1, 1, 1, 1, None))
    t.row_cap = 5
    t.prune(now)
    assert len(rows(platform_env, "metric_minute")) == 5
    assert min(r[0] for r in rows(platform_env, "metric_minute")) == now - 4 * MINUTE_MS
    assert all(r[1] != "x" for r in rows(platform_env, "metric_hour"))
    assert t.stats()["rows"] == 6


def test_tag_cardinality_cap(platform_env):
    t = enabled(platform_env)
    for i in range(250):
        t.record("error", 1, code=f"c{i}")
    t.flush(force=True)
    tags = {r[2] for r in rows(platform_env, "metric_minute")}
    assert len(tags) == 201 and tm.OTHER in tags


def test_query_quantiles_and_tags(platform_env):
    t = enabled(platform_env)
    for v in range(1, 101):
        t.record("http.request", float(v), route="/a")
    t.record("http.request", 1000, route="/b")
    result = t.query("http.request", 3600, "total", {"route": "/a"})
    (series,) = result["series"]
    assert series["count"] == 100 and series["min"] == 1 and series["max"] == 100
    assert 90 <= series["p95"] <= 100  # Within the 50..100 bucket, interpolated.
    assert 40 <= series["p50"] <= 55
    t.flush(force=True)
    minute = t.query("http.request", 3600, "minute")["series"]
    assert len(minute) == 2 and minute[0]["points"][0][1] == 100
    assert t.query("nothing", 3600)["series"] == []


def test_timed_decorator_and_context(platform_env):
    t = enabled(platform_env)

    @pf.timed("recommend.run", scope="all")
    def work():
        return 42

    assert work() == 42 and work() == 42
    with pf.timed("install.apply"):
        pass
    series = {s["name"]: s for s in t.query(None, 600, "total")["series"]}
    assert series["recommend.run"]["count"] == 2
    assert series["install.apply"]["count"] == 1


def test_clear(platform_env):
    t = enabled(platform_env)
    t.record("x")
    t.flush(force=True)
    assert t.clear() == 1 and t.stats()["rows"] == 0


@pytest.mark.serial
def test_record_performance(platform_env):
    t = enabled(platform_env)
    t0 = time.perf_counter()
    for _ in range(100_000):
        t.record("http.request", 3.0, route="/v1/sessions", method="GET", status="2xx")
    elapsed = time.perf_counter() - t0
    print(f"record: {elapsed * 10:.2f} µs/call")
    assert elapsed < 1.0  # Spec target ≤ 3 µs; generous for CI.
    t.enabled = False
    t0 = time.perf_counter()
    for _ in range(100_000):
        tm.record("http.request", 3.0, route="/v1/sessions")
    assert time.perf_counter() - t0 < 0.1


@pytest.mark.serial
def test_flush_2000_series_fast(platform_env):
    t = enabled(platform_env)
    for i in range(2000):
        t.record(f"m{i // 200}", 1.0, route=f"/r{i % 200}")
    t0 = time.perf_counter()
    assert t.flush(force=True) == 2000
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"flush 2000 series: {elapsed:.1f} ms")
    assert elapsed < 500
