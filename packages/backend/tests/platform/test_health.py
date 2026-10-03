from __future__ import annotations

import sqlite3
from collections import namedtuple

from orbit_backend.platform import health as health_mod
from orbit_backend.platform.health import health

Usage = namedtuple("Usage", "total used free")


def status_of(result, cid):
    return next(c["status"] for c in result["checks"] if c["id"] == cid)


def test_shallow_structure(started):
    result = health(started)
    assert result["status"] == "ok"
    assert {c["id"] for c in result["checks"]} == {
        "app_db", "orbit_db", "cache_db", "disk", "workers", "event_bus", "sync_loop",
        "maintenance", "logs"}
    assert set(result["services"]) == {"ingest", "analysis"}
    assert set(result["db"]) == {"orbit_db", "orbit_wal", "app_db", "catalog_db", "analysis",
                                 "snapshot_cache"}
    assert result["disk"]["free_bytes"] > 0 and result["collection"] in (None, {"paused": False})
    assert "metrics_flush" in result["maintenance"]
    assert next(c for c in result["checks"] if c["id"] == "orbit_db")["detail"] == {
        "absent": True}


def test_cache_and_deep(started, monkeypatch):
    first = health(started)
    assert health(started) is first  # Cached for 5 s.
    path = started.home / "orbit.db"
    sqlite3.connect(path).execute("CREATE TABLE t(x)").connection.close()
    deep = health(started, deep=True)
    detail = next(c for c in deep["checks"] if c["id"] == "orbit_db")["detail"]
    assert detail["quick_check"] == "ok"
    assert health(started) is first  # Deep never replaces the shallow cache.


def test_degradations(started, monkeypatch):
    monkeypatch.setattr(health_mod.shutil, "disk_usage",
                        lambda _: Usage(10**12, 10**12, 100 * 1024**2))
    started.gw.supervisor.info["ingest"]["state"] = "degraded"
    result = health(started, deep=True)
    assert status_of(result, "disk") == "fail"
    assert status_of(result, "workers") == "fail"
    assert result["status"] == "fail"

    monkeypatch.setattr(health_mod.shutil, "disk_usage",
                        lambda _: Usage(10**12, 10**12, 1024**3))
    started.gw.supervisor.info["ingest"]["state"] = "running"
    started.gw.supervisor.info["analysis"]["last_hb_age_s"] = 99.0
    result = health(started, deep=True)
    assert status_of(result, "disk") == "warn" and status_of(result, "workers") == "warn"
    assert result["status"] == "degraded"


def test_wal_warning(started, monkeypatch):
    (started.home / "orbit.db").write_bytes(b"")
    (started.home / "orbit.db-wal").write_bytes(b"")
    monkeypatch.setattr(health_mod, "WAL_WARN", -1)
    assert status_of(health(started, deep=False), "orbit_db") == "warn"


def test_bus_closed_fails(started):
    started.gw.bus.close()
    assert status_of(health(started, deep=True), "event_bus") == "fail"
